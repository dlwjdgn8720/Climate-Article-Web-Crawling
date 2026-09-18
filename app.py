import json
import re
import streamlit as st
import requests
import pandas as pd
import urllib.parse
import email.utils
import torch
import os
from datetime import datetime, timezone, timedelta
from bs4 import BeautifulSoup
from transformers import BertForSequenceClassification, BertTokenizerFast
from huggingface_hub import hf_hub_download

from news_config import (
    PERSON_KEYWORDS,
    CATEGORY_MAP,
    CATEGORIES,
    CLIMATE_SUBQUERY,
    CLIMATE_FALLBACK_KEYWORDS,
    EXCLUDE_QUERY,
    STRICT_EXCLUDE_TITLES,
    MAJOR_MEDIA_DICT,
)

# ==========================================
# [0. 기후 AI 모델 로드 및 예측 파이프라인]
# ==========================================
HUB_MODEL_PATH = "dlwjdgn8720/my-climate-kobert"
HUB_MODEL_SUBFOLDER = "climate_model"  # 허브 저장소 루트에는 구버전 파일만 있고, 실제 학습 산출물은 이 하위 폴더에 있음
LOCAL_MODEL_DIR = "climate_model"
DEFAULT_CLIMATE_THRESHOLD = 0.5


def _resolve_model_source():
    """로컬에 재학습된 모델(climate_model/)이 있으면 그것을, 없으면 허브 모델을 사용합니다."""
    required_files = ["config.json", "model.safetensors"]
    if os.path.isdir(LOCAL_MODEL_DIR) and all(
        os.path.exists(os.path.join(LOCAL_MODEL_DIR, f)) for f in required_files
    ):
        return LOCAL_MODEL_DIR, True
    return HUB_MODEL_PATH, False


@st.cache_resource
def load_climate_model():
    """
    로컬 재학습 모델(있으면 우선) 또는 허깅페이스 허브 모델을 로드하여 캐싱합니다.
    두 소스 모두 동일한 파일 구성(config.json/model.safetensors/tokenizer.json/threshold.json)을
    가지고 있어 BertTokenizerFast로 통일해서 로드하며, 허브의 경우 실제 학습 산출물이
    저장된 climate_model/ 하위 폴더를 명시해야 합니다(루트 파일은 구버전이라 사용하면 안 됨).
    """
    source, is_local = _resolve_model_source()
    load_kwargs = {} if is_local else {"subfolder": HUB_MODEL_SUBFOLDER}
    try:
        tokenizer = BertTokenizerFast.from_pretrained(source, **load_kwargs)

        model = BertForSequenceClassification.from_pretrained(
            source,
            use_safetensors=True,
            num_labels=2,                     # 기후뉴스(1)/일반뉴스(0) 이진 분류 규격 강제
            ignore_mismatched_sizes=True,     # 레이블 가중치 크기 불일치 에러 방지
            **load_kwargs,
        )
        model.eval()
        # CPU 추론 전용 동적 양자화(Linear 레이어 INT8) — 예측 결과는 거의 그대로 유지되면서
        # 배치 추론 시간이 약 30% 단축됨(제목 100개 기준 약 3.0s -> 2.0s로 실측 확인).
        model = torch.quantization.quantize_dynamic(model, {torch.nn.Linear}, dtype=torch.qint8)

        threshold = DEFAULT_CLIMATE_THRESHOLD
        try:
            if is_local:
                threshold_path = os.path.join(source, "threshold.json")
            else:
                threshold_path = hf_hub_download(
                    repo_id=source, filename="threshold.json", subfolder=HUB_MODEL_SUBFOLDER
                )
            with open(threshold_path, encoding="utf-8") as f:
                threshold = json.load(f).get("threshold", DEFAULT_CLIMATE_THRESHOLD)
        except Exception:
            pass  # threshold.json이 없으면 기본값(0.5) 사용

        return tokenizer, model, threshold, source
    except Exception as e:
        st.session_state["model_load_error"] = str(e)
        return None, None, DEFAULT_CLIMATE_THRESHOLD, source


# 모델, 토크나이저, 실사용 임계값 초기화
tokenizer, model, CLIMATE_THRESHOLD, MODEL_SOURCE = load_climate_model()


def _keyword_fallback_predict(title: str):
    """AI 모델 로드 실패 시 사용하는 단순 키워드 매칭 폴백."""
    is_climate = any(kw in title for kw in CLIMATE_FALLBACK_KEYWORDS)
    return (1, 0.5) if is_climate else (0, 0.5)


def predict_climate_news_batch(titles):
    """
    여러 개의 뉴스 제목을 한 번에 배치 추론하여 기후 뉴스 여부를 판별합니다.
    리턴값: [(prediction, confidence), ...] -> 입력 순서와 동일한 길이의 리스트.
    prediction=1(기후뉴스)은 신뢰도가 CLIMATE_THRESHOLD 이상일 때만 부여됩니다.
    """
    if not titles:
        return []

    if tokenizer is None or model is None:
        return [_keyword_fallback_predict(t) for t in titles]

    inputs = tokenizer(
        titles,
        return_tensors="pt",
        truncation=True,
        max_length=128,
        padding=True,
    )

    with torch.no_grad():
        outputs = model(**inputs)

    probs = torch.softmax(outputs.logits, dim=-1)

    results = []
    for i in range(len(titles)):
        climate_prob = probs[i][1].item()
        if climate_prob >= CLIMATE_THRESHOLD:
            results.append((1, climate_prob))
        else:
            results.append((0, 1.0 - climate_prob))
    return results


# ─────────────────────────────────────────────────────────────────
# [피드백 수집] — 오분류된 기사를 사용자가 직접 레이블링하여 저장
# ─────────────────────────────────────────────────────────────────
FEEDBACK_FILE = "feedback_data.csv"

def save_feedback(title: str, correct_label: int):
    """오분류 기사를 feedback_data.csv에 저장 (재학습 데이터 축적)"""
    row = pd.DataFrame([{"title": title, "label": correct_label}])
    if os.path.exists(FEEDBACK_FILE):
        row.to_csv(FEEDBACK_FILE, mode="a", header=False, index=False, encoding="utf-8-sig")
    else:
        row.to_csv(FEEDBACK_FILE, mode="w", header=True, index=False, encoding="utf-8-sig")


# ─────────────────────────────────────────────────────────────────
# [1. 구글 RSS 크롤링 + AI 필터링]
# ─────────────────────────────────────────────────────────────────

@st.cache_data(ttl=600, show_spinner=False)
def _fetch_climate_news_cached(keyword, category):
    """
    실제 크롤링+필터링 로직. 같은 (키워드, 카테고리) 조합은 10분간 캐시되어
    재검색 시 네트워크 요청과 AI 추론을 다시 하지 않고 즉시 결과를 반환합니다.
    리턴값: (final_news, period_label, error_message)
    """
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        )
    }

    is_person_keyword = any(p in keyword for p in PERSON_KEYWORDS)
    category_query = CATEGORY_MAP.get(category, "")

    if is_person_keyword:
        if category_query:
            query_text = f'"{keyword}" {CLIMATE_SUBQUERY} {category_query} {EXCLUDE_QUERY}'
        else:
            query_text = f'"{keyword}" {CLIMATE_SUBQUERY} {EXCLUDE_QUERY}'
    elif category_query:
        query_text = f'"{keyword}" {category_query} {EXCLUDE_QUERY}'
    else:
        query_text = f'"{keyword}" {EXCLUDE_QUERY}'

    encoded_query = urllib.parse.quote(query_text)
    url = f"https://news.google.com/rss/search?q={encoded_query}&hl=ko&gl=KR&ceid=KR:ko"

    try:
        response = requests.get(url, headers=headers, timeout=10)
        if response.status_code != 200:
            return None, None, f"구글 뉴스 응답 오류 (HTTP {response.status_code})"

        soup = BeautifulSoup(response.text, "lxml-xml")
        items = soup.find_all("item")
        if not items:
            return None, None, None

        now = datetime.now(timezone.utc)

        # 1차 필터링: 제목/날짜 기준으로 후보만 추려서 모델 추론 대상을 최소화
        candidates = []
        for item in items:
            title = item.title.get_text()
            link  = item.link.get_text()
            pub_date_str = item.pubDate.get_text() if item.pubDate else ""

            if any(bad in title for bad in STRICT_EXCLUDE_TITLES):
                continue

            try:
                parsed_date = email.utils.parsedate_to_datetime(pub_date_str)
                if parsed_date.tzinfo is None:
                    parsed_date = parsed_date.replace(tzinfo=timezone.utc)
            except Exception:
                continue

            if now - parsed_date > timedelta(days=30):
                continue

            candidates.append({"title": title, "link": link, "parsed_date": parsed_date})

        if not candidates:
            return None, None, None

        # 기사 하나씩 순차 추론하지 않고, 후보 제목 전체를 한 번에 배치 추론
        predictions = predict_climate_news_batch([c["title"] for c in candidates])

        major_news_list = []
        general_news_list = []

        for candidate, (is_climate, confidence) in zip(candidates, predictions):
            if is_climate == 0:
                continue

            title = candidate["title"]
            link = candidate["link"]
            parsed_date = candidate["parsed_date"]

            data_row = {
                "기사 제목": title,
                "기사 링크": link,
                "작성일":     parsed_date.strftime("%Y-%m-%d %H:%M"),
                "_raw_date": parsed_date,
                "우선순위":  "일반 기사",
                "AI 신뢰도": f"{confidence:.0%}",
                "_confidence": confidence,
            }

            is_major = False
            lower_title = title.lower()
            lower_link  = link.lower()
            for media_name, kws in MAJOR_MEDIA_DICT.items():
                if any(kw in lower_title or kw in lower_link for kw in kws):
                    is_major = True
                    data_row["우선순위"] = f"⭐ {media_name}"
                    break

            (major_news_list if is_major else general_news_list).append(data_row)

        sorted_major   = sorted(major_news_list,   key=lambda x: x["_raw_date"], reverse=True)
        sorted_general = sorted(general_news_list, key=lambda x: x["_raw_date"], reverse=True)
        final_news = sorted_major + sorted_general

        if final_news:
            has_week = any((now - x["_raw_date"]) <= timedelta(days=7) for x in final_news)
            return final_news, ("1주일" if has_week else "한 달"), None

    except Exception as e:
        print(f"크롤링 에러 추적: {str(e)}")
        return None, None, str(e)

    return None, None, None


def get_climate_news(keyword, category):
    """캐시된 크롤링 결과를 가져오면서, 오류가 있으면 session_state에 기록합니다."""
    final_news, period, error_message = _fetch_climate_news_cached(keyword, category)
    if error_message:
        st.session_state["crawl_error"] = error_message
    else:
        st.session_state.pop("crawl_error", None)
    return final_news, period


# ─────────────────────────────────────────────────────────────────
# [2. UI 블록]
# ─────────────────────────────────────────────────────────────────
st.set_page_config(page_title="기후 뉴스 수집기", page_icon="🌱", layout="wide")

for key, default in [
    ("news_df", None), ("p_num", 1), ("period_info", ""),
    ("current_keyword", ""), ("current_category", "전체 보기"),
    ("input_key_setter", ""), ("show_feedback", False),
]:
    if key not in st.session_state:
        st.session_state[key] = default

st.markdown("""
<style>
    .main-title  { font-size:28px; font-weight:700; color:#1e4620; margin-bottom:5px; }
    .sub-title   { font-size:14px; color:#555; margin-bottom:25px; }
    .news-date   { font-size:12px; color:#888; margin-top:2px; }
    .keyword-label { font-size:14px; font-weight:600; color:#444; margin-bottom:8px; }
    .badge-major   { background:#e8f5e9; color:#2e7d32; padding:2px 6px;
                     border-radius:4px; font-size:11px; font-weight:bold; }
    .badge-general { background:#f5f5f5; color:#666; padding:2px 6px;
                     border-radius:4px; font-size:11px; }
    .badge-conf    { background:#fff3e0; color:#e65100; padding:2px 6px;
                     border-radius:4px; font-size:11px; }
    div.stButton > button { white-space:nowrap !important; min-width:max-content !important; }
</style>
""", unsafe_allow_html=True)

# 모델 상태 배너
if tokenizer is None:
    error_detail = st.session_state.get("model_load_error")
    st.warning(
        "⚠️ 학습된 AI 모델이 로드되지 않아 단순 키워드 매칭 폴백 모드로 구동 중입니다."
        + (f" (오류: {error_detail})" if error_detail else "")
    )
else:
    source_label = "로컬 재학습 모델" if MODEL_SOURCE == LOCAL_MODEL_DIR else "허브 모델"
    st.success(f"✅ AI 모델 활성화 중 ({source_label}) — 신뢰도 임계값 {CLIMATE_THRESHOLD:.1%} 이상만 통과")

st.markdown("""
    <div class="main-title">🌱 기후관련 뉴스 수집 시스템</div>
    <div class="sub-title">구글 RSS 뉴스를 실시간 수집하고 AI 가드레일 모델을 통해 관련성을 검증합니다.</div>
""", unsafe_allow_html=True)

# 추천 키워드
recommended_keywords = ["기후변화", "탄소중립", "신재생에너지", "CCUS", "이상기온", "ESG", "에너지"]
st.markdown("<div class='keyword-label'>추천 키워드 검색</div>", unsafe_allow_html=True)

trigger_keyword = None
kw_cols = st.columns(len(recommended_keywords))
for i, kw in enumerate(recommended_keywords):
    with kw_cols[i]:
        if st.button(f"#{kw}", width="stretch", key=f"btn_{kw}"):
            trigger_keyword = kw

st.write(" ")

with st.form("search_form", clear_on_submit=False):
    col_cat, col_inp, col_btn = st.columns([1.2, 2.5, 0.8])
    with col_cat:
        selected_cat = st.selectbox("카테고리 선택", CATEGORIES, label_visibility="collapsed")
    with col_inp:
        keyword_input = st.text_input(
            "검색어 입력창",
            value=st.session_state.input_key_setter,
            placeholder="검색어를 입력하거나 위 추천 태그를 클릭하세요.",
            label_visibility="collapsed",
        )
    with col_btn:
        search_button = st.form_submit_button("뉴스 검색", width="stretch")

# 검색 트리거 — 추천 태그 클릭 또는 폼 제출(버튼/Enter)일 때만 실행되고,
# 글자를 입력하는 도중에는(=폼 제출 전) 재검색이 일어나지 않습니다.
run_search = False
search_target_keyword = ""

if trigger_keyword:
    run_search = True
    search_target_keyword = trigger_keyword
    st.session_state.input_key_setter = ""
elif search_button and keyword_input.strip():
    run_search = True
    search_target_keyword = keyword_input.strip()
    st.session_state.input_key_setter = keyword_input.strip()

if run_search and search_target_keyword:
    with st.spinner(f"'{search_target_keyword}' 결과 가공 중..."):
        st.session_state.news_df = None
        st.session_state.is_person_search = any(
            p in search_target_keyword for p in PERSON_KEYWORDS
        )
        res, period = get_climate_news(search_target_keyword, selected_cat)
        if res:
            st.session_state.news_df       = pd.DataFrame(res)
            st.session_state.period_info   = period
            st.session_state.current_keyword  = search_target_keyword
            st.session_state.current_category = selected_cat
            st.session_state.p_num         = 1
            st.session_state.pop("search_failed", None)
        else:
            st.session_state.news_df          = None
            st.session_state.current_keyword  = search_target_keyword
            st.session_state.current_category = selected_cat
            st.session_state.search_failed    = True
        st.rerun()

st.write("---")

# ─────────────────────────────────────────────────────────────────
# [3. 결과 렌더링]
# ─────────────────────────────────────────────────────────────────
if st.session_state.news_df is not None:
    df          = st.session_state.news_df
    current_kw  = st.session_state.current_keyword
    current_cat = st.session_state.current_category
    period_text = st.session_state.period_info

    st.success(
        f"'{current_kw}' [{current_cat}] → "
        f"AI 필터링 통과 (최근 {period_text} 이내 총 {len(df)}건)"
    )

    if st.session_state.get("is_person_search", False):
        st.info(
            "👤 **인물 키워드 감지** — RSS 쿼리 단계부터 기후 관련 기사만 수집하도록 자동 필터가 적용되었습니다. "
            "기후 무관 기사(정치·외교·경제 등)는 검색 결과에서 제외됩니다."
        )

    tab1, tab2, tab3 = st.tabs(["뉴스 목록 보기", "데이터 내보내기", "🔁 오분류 피드백"])

    with tab1:
        st.write("📌 기사 제목을 누르면 해당 뉴스 원문 페이지로 이동합니다.")
        view_mode = st.radio(
            "보기 모드 선택",
            ["모바일 피드 (전체 스크롤)", "PC 정돈 모드 (10개씩 보기)"],
            horizontal=True,
            key="view_mode_select",
        )
        st.write("---")

        def render_row(idx, row):
            badge_class = "badge-major" if "⭐" in row["우선순위"] else "badge-general"
            # 마크다운 링크 구문이 제목 속 대괄호로 깨지지 않도록 이스케이프하고,
            # http(s)가 아닌 스킴(예: javascript:)의 링크는 무효화합니다.
            safe_title = row["기사 제목"].replace("[", "\\[").replace("]", "\\]")
            link = row["기사 링크"]
            safe_link = link if re.match(r"^https?://", link, re.IGNORECASE) else "#"
            st.markdown(f"**{idx+1}. [{safe_title}]({safe_link})**")
            st.markdown(
                f"<span class='{badge_class}'>{row['우선순위']}</span> &nbsp; "
                f"<span class='badge-conf'>🤖 {row['AI 신뢰도']}</span> &nbsp;&nbsp; "
                f"<span class='news-date'>⏱ {row['작성일']}</span>",
                unsafe_allow_html=True,
            )
            st.markdown("<div style='margin-bottom:18px; border-bottom:1px dashed #eee;'></div>",
                        unsafe_allow_html=True)

        if view_mode == "모바일 피드 (전체 스크롤)":
            for idx, row in df.iterrows():
                render_row(idx, row)
        else:
            items_per_page = 10
            total_pages    = max(1, (len(df) - 1) // items_per_page + 1)
            st.session_state.p_num = min(st.session_state.p_num, total_pages)
            start_idx = (st.session_state.p_num - 1) * items_per_page
            page_df   = df.iloc[start_idx : start_idx + items_per_page]

            for idx, row in page_df.iterrows():
                render_row(idx, row)

            st.write("---")
            p1, p2, p3 = st.columns([1, 2, 1])
            with p1:
                if st.button("⬅️ 이전", width="stretch",
                             disabled=(st.session_state.p_num == 1), key="btn_prev"):
                    st.session_state.p_num -= 1
                    st.rerun()
            with p2:
                st.markdown(
                    f"<p style='text-align:center;line-height:38px;'>"
                    f"<b>{st.session_state.p_num} / {total_pages} 페이지</b></p>",
                    unsafe_allow_html=True,
                )
            with p3:
                if st.button("다음 ➡️", width="stretch",
                             disabled=(st.session_state.p_num == total_pages), key="btn_next"):
                    st.session_state.p_num += 1
                    st.rerun()

        st.write("---")
        with st.expander("원본 데이터 표 형태로 보기"):
            display_cols = [c for c in df.columns if not c.startswith("_")]
            st.dataframe(df[display_cols], width="stretch", hide_index=True)

    with tab2:
        st.write("📋 추출용 깨끗한 데이터셋을 파일로 저장할 수 있습니다.")
        display_cols = [c for c in df.columns if not c.startswith("_")]
        csv = df[display_cols].to_csv(index=False).encode("utf-8-sig")
        st.download_button(
            label="📥 엑셀(CSV) 다운로드",
            data=csv,
            file_name=f"Verified_{current_kw}_{current_cat}_뉴스데이터.csv",
            mime="text/csv",
            width="stretch",
            key="btn_download",
        )

    with tab3:
        st.write(
            "🔁 AI가 잘못 분류한 기사를 레이블링하면 `feedback_data.csv`에 저장됩니다.  \n"
            "나중에 `train_data_augmented.csv`와 합쳐 재학습하면 정확도가 올라갑니다."
        )

        feedback_title = st.text_input(
            "오분류된 기사 제목 붙여넣기",
            placeholder="예) 코스피, 탄소배출권 관련주 강세로 소폭 상승 마감",
            key="fb_title",
        )
        feedback_label = st.radio(
            "올바른 레이블",
            ["1 — 기후 관련 기사 (AI가 제외했는데 포함시켜야 함)",
             "0 — 비기후 기사 (AI가 통과시켰는데 제외해야 함)"],
            key="fb_label",
        )
        if st.button("💾 피드백 저장", key="btn_feedback"):
            if feedback_title.strip():
                correct_label = int(feedback_label[0])
                save_feedback(feedback_title.strip(), correct_label)
                st.success("✅ 피드백이 저장되었습니다!")
            else:
                st.warning("기사 제목을 입력해주세요.")

        if os.path.exists(FEEDBACK_FILE):
            fb_df = pd.read_csv(FEEDBACK_FILE)
            st.info(f"현재까지 누적 피드백: {len(fb_df)}건")
            with st.expander("피드백 데이터 확인"):
                st.dataframe(fb_df, width="stretch", hide_index=True)
            st.download_button(
                label="📥 피드백 데이터 다운로드 (재학습용)",
                data=fb_df.to_csv(index=False).encode("utf-8-sig"),
                file_name="feedback_data.csv",
                mime="text/csv",
                key="btn_fb_download",
            )

else:
    if st.session_state.get("search_failed", False):
        crawl_error = st.session_state.get("crawl_error")
        if crawl_error:
            st.error(
                f"'{st.session_state.current_keyword}' 검색 중 오류가 발생했습니다: {crawl_error}"
            )
        else:
            st.error(
                f"'{st.session_state.current_keyword}' 관련 뉴스가 없거나 "
                "AI가 노이즈로 판단해 모두 제외했습니다."
            )
    else:
        st.info("검색어를 입력하거나 추천 태그를 클릭해 조사를 시작하세요.")