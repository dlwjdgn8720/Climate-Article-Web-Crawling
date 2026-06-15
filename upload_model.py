# upload_model.py (수정본)
from huggingface_hub import HfApi

api = HfApi()

# ⚠️ 여기에 본인의 정보와 [방금 복사한 토큰]을 정확히 입력하세요!
repo_id = "dlwjdgn8720/my-climate-kobert"
local_file_path = "./climate_model/model.safetensors"
HF_TOKEN = "YOUR_HF_TOKEN_HERE" # 💡 여기에 토큰 입력!

print("🚀 인증을 확인하고 473MB 대용량 가중치 파일 업로드를 시작합니다...")

api.upload_file(
    path_or_fileobj=local_file_path,
    path_in_repo="model.safetensors",
    repo_id=repo_id,
    repo_type="model",
    token=HF_TOKEN # 💡 허깅페이스에게 열쇠를 제출합니다.
)

print("✨ [성공] 업로드가 완료되었습니다! 이제 허깅페이스가 파일 주소를 정상 인식합니다.")