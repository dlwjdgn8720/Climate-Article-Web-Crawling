"""
train.py (업그레이드 버전)
===========================
주요 개선 사항:
  1. train_data_augmented.csv 사용 (약 1,500건)
  2. Trainer에 compute_metrics 추가 → F1/정확도 에폭별 출력
  3. 클래스 불균형 대비 WeightedRandomSampler 적용
  4. 최적 신뢰도 임계값(threshold) 자동 탐색 후 climate_model/threshold.json 저장
     → app.py에서 predict_climate_news()가 이 값을 읽어 정밀 필터링
  5. early_stopping_patience=3 으로 과적합 방지
"""

import os
import json
import numpy as np
import pandas as pd
import torch
from torch.utils.data import Dataset, WeightedRandomSampler
from transformers import (
    AutoTokenizer,
    AutoModelForSequenceClassification,
    Trainer,
    TrainingArguments,
    EarlyStoppingCallback,
)
from sklearn.model_selection import train_test_split
from sklearn.metrics import f1_score, accuracy_score, precision_recall_curve

# ─────────────────────────────────────────────
# 1. 데이터 로드 (증강 데이터 우선, 없으면 원본)
# ─────────────────────────────────────────────
DATA_FILE = "train_data_augmented.csv" if os.path.exists("train_data_augmented.csv") else "train_data.csv"
print(f"📂 학습 데이터: {DATA_FILE}")

df = pd.read_csv(DATA_FILE)
train_df, val_df = train_test_split(df, test_size=0.2, random_state=42, stratify=df["label"])

print(f"   전체 {len(df)}건 → 학습 {len(train_df)}건 / 검증 {len(val_df)}건")
print(f"   label 분포 — 학습: {train_df['label'].value_counts().to_dict()}")

# ─────────────────────────────────────────────
# 2. 토크나이저 & 모델
# ─────────────────────────────────────────────
MODEL_NAME = "kykim/bert-kor-base"
tokenizer = AutoTokenizer.from_pretrained(MODEL_NAME)
model = AutoModelForSequenceClassification.from_pretrained(MODEL_NAME, num_labels=2)

# ─────────────────────────────────────────────
# 3. PyTorch Dataset
# ─────────────────────────────────────────────
class NewsDataset(Dataset):
    def __init__(self, dataframe, tokenizer, max_len=128):
        self.data = dataframe.reset_index(drop=True)
        self.tokenizer = tokenizer
        self.max_len = max_len

    def __len__(self):
        return len(self.data)

    def __getitem__(self, index):
        title = str(self.data.iloc[index]["title"])
        label = int(self.data.iloc[index]["label"])

        inputs = self.tokenizer(
            title,
            add_special_tokens=True,
            max_length=self.max_len,
            padding="max_length",
            truncation=True,
            return_token_type_ids=False,
            return_attention_mask=True,
            return_tensors="pt",
        )
        return {
            "input_ids": inputs["input_ids"].flatten(),
            "attention_mask": inputs["attention_mask"].flatten(),
            "labels": torch.tensor(label, dtype=torch.long),
        }

train_dataset = NewsDataset(train_df, tokenizer)
val_dataset   = NewsDataset(val_df,   tokenizer)

# ─────────────────────────────────────────────
# 4. 클래스 불균형 대비 WeightedRandomSampler
# ─────────────────────────────────────────────
label_counts = train_df["label"].value_counts()
class_weights = 1.0 / torch.tensor([label_counts[0], label_counts[1]], dtype=torch.float)
sample_weights = [class_weights[label] for label in train_df["label"]]
sampler = WeightedRandomSampler(sample_weights, num_samples=len(sample_weights), replacement=True)

# ─────────────────────────────────────────────
# 5. 평가 메트릭 (F1 + 정확도)
# ─────────────────────────────────────────────
def compute_metrics(eval_pred):
    logits, labels = eval_pred
    preds = np.argmax(logits, axis=-1)
    return {
        "accuracy": accuracy_score(labels, preds),
        "f1":       f1_score(labels, preds, average="binary"),
    }

# ─────────────────────────────────────────────
# 6. TrainingArguments
# ─────────────────────────────────────────────
training_args = TrainingArguments(
    output_dir="./results",
    num_train_epochs=8,              # 증강 데이터로 충분히 학습
    per_device_train_batch_size=16,
    per_device_eval_batch_size=16,
    warmup_ratio=0.1,                # 전체 스텝의 10% warmup
    weight_decay=0.01,
    learning_rate=2e-5,
    logging_dir="./logs",
    logging_steps=20,
    eval_strategy="epoch",
    save_strategy="epoch",
    load_best_model_at_end=True,
    metric_for_best_model="f1",      # F1 기준으로 최고 모델 선택
    greater_is_better=True,
    fp16=torch.cuda.is_available(),  # GPU 있으면 혼합 정밀도 학습
    dataloader_num_workers=0,
)

# ─────────────────────────────────────────────
# 7. Trainer (EarlyStopping 포함)
# ─────────────────────────────────────────────
class SamplerTrainer(Trainer):
    """WeightedRandomSampler를 적용한 커스텀 Trainer"""
    def get_train_dataloader(self):
        from torch.utils.data import DataLoader
        return DataLoader(
            self.train_dataset,
            batch_size=self.args.per_device_train_batch_size,
            sampler=sampler,
            collate_fn=self.data_collator,
            drop_last=self.args.dataloader_drop_last,
            num_workers=self.args.dataloader_num_workers,
        )

trainer = SamplerTrainer(
    model=model,
    args=training_args,
    train_dataset=train_dataset,
    eval_dataset=val_dataset,
    compute_metrics=compute_metrics,
    callbacks=[EarlyStoppingCallback(early_stopping_patience=3)],
)

# ─────────────────────────────────────────────
# 8. 학습
# ─────────────────────────────────────────────
print("\n🚀 AI 모델 기후 도메인 파인튜닝 시작...")
trainer.train()

# ─────────────────────────────────────────────
# 9. 최적 신뢰도 임계값 탐색 & 저장
#    — Precision-Recall 커브로 F1 최대화 지점 탐색
# ─────────────────────────────────────────────
print("\n🔍 최적 confidence threshold 탐색 중...")
pred_output = trainer.predict(val_dataset)
logits = pred_output.predictions                            # (N, 2)
probs  = torch.softmax(torch.tensor(logits), dim=-1).numpy()
pos_probs = probs[:, 1]                                    # label=1(기후) 확률
labels_true = pred_output.label_ids

precision, recall, thresholds = precision_recall_curve(labels_true, pos_probs)
f1_scores = 2 * precision * recall / (precision + recall + 1e-8)
best_idx   = np.argmax(f1_scores[:-1])
best_threshold = float(thresholds[best_idx])
best_f1        = float(f1_scores[best_idx])
print(f"   → 최적 threshold: {best_threshold:.4f}  (F1: {best_f1:.4f})")

# ─────────────────────────────────────────────
# 10. 모델 & 임계값 저장
# ─────────────────────────────────────────────
os.makedirs("./climate_model", exist_ok=True)
model.save_pretrained("./climate_model")
tokenizer.save_pretrained("./climate_model")

threshold_info = {
    "threshold": best_threshold,
    "best_val_f1": best_f1,
    "data_file": DATA_FILE,
    "num_train": len(train_df),
}
with open("./climate_model/threshold.json", "w", encoding="utf-8") as f:
    json.dump(threshold_info, f, ensure_ascii=False, indent=2)

print("\n✅ 기후 전용 AI 모델 저장 완료! (./climate_model)")
print(f"   threshold.json → {threshold_info}")
