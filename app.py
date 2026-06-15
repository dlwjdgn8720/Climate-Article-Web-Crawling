import streamlit as st
import requests
from bs4 import BeautifulSoup
import pandas as pd
import urllib.parse
from datetime import datetime, timezone, timedelta
import email.utils
import os
import json
import torch
from transformers import AutoModelForSequenceClassification, AutoTokenizer

# ==========================================
# [0. 기후 AI 모델 로드 — threshold 포함]
# ==========================================

# 변경 전: 로컬 폴더 경로 탐색
# MODEL_PATH = "./climate_model"

MODEL_PATH = "dlwjdgn8720/my-climate-kobert"

@st.cache_resource
def load_climate_model():
    """ 허깅페이스 저장소로부터 모델과 토크나이저를 원격 뱅크에서 로드 """
    if not os.path.exists(MODEL_PATH):
        return None, None, 0.5   # 모델 없으면 기본 임계값 0.5

    try:
        tokenizer = AutoTokenizer.from_pretrained(MODEL_PATH)
        model = AutoModelForSequenceClassification.from_pretrained(MODEL_PATH)
        model.eval()

        # 학습 시 계산된 최적 threshold 로드 (없으면 기본값)
        ''' threshold = 0.5
        threshold_path = os.path.join(MODEL_PATH, "threshold.json")
        if os.path.exists(threshold_path):
            with open(threshold_path, "r", encoding="utf-8") as f:
                info = json.load(f)
                threshold = info.get("threshold", 0.5) '''

        return tokenizer, model
    except Exception:
        return None, None

tokenizer, model, CLIMATE_THRESHOLD = load_climate_model()


def predict_climate_news(title):
    """
    반환값: (is_climate: bool, confidence: float)
      - is_climate  : True면 기후 기사로 판단
      - confidence  : label=1(기후) 확률 (0~1)
    모델 없으면 키워드 폴백으로 판단.
    """
    if tokenizer is not None and model is not None:
        inputs = tokenizer(
            title,
            return_tensors="pt",
            truncation=True,
            max_length=128,
            padding=True,
        )
        with torch.no_grad():
            logits = model(**inputs).logits
        probs = torch.softmax(logits, dim=-1)[0]
        confidence = probs[1].item()   # label=1(기후) 확률
        return confidence >= CLIMATE_THRESHOLD, confidence

    # ── 모델 없을 때 키워드 기반 폴백 ──────────────────────────────────────
    CLIMATE_KEYWORDS = [
        "기후변화", "탄소중립", "온실가스", "이상기후", "폭염", "한파", "폭우", "가뭄",
        "태풍", "홍수", "산불", "해수면", "빙하", "탄소배출", "신재생에너지", "탄소세",
        "엘니뇨", "라니냐", "열돔", "기후위기", "녹색", "에너지전환", "CCUS", "NDC",
        "적조", "백화현상", "해양산성화", "미세먼지", "대기오염", "ESG",
    ]
    NOISE_KEYWORDS = [
        "오늘날씨", "내일날씨", "날씨예보", "기상예보", "증시", "주가", "펀드",
        "특징주", "테마주", "시황", "장마감", "관련주",
    ]
    title_no_space = title.replace(" ", "")
    if any(nk in title_no_space for nk in NOISE_KEYWORDS):
        return False, 0.0
    hit = sum(1 for kw in CLIMATE_KEYWORDS if kw in title)
    confidence = min(hit / 2.0, 1.0)
    return confidence >= 0.5, confidence


# ─────────────────────────────────────────────────────────────────
# [피드백 수집] — 오분류된 기사를 사용자가 직접 레이블링하여
#                 feedback_data.csv에 쌓은 뒤 재학습에 활용
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

# 유명인·인물 키워드 목록 (모듈 레벨 — UI 섹션과 공유)
PERSON_KEYWORDS = {
    # 해외 정치인
    "트럼프", "바이든", "해리스", "오바마", "클린턴", "부시",
    "시진핑", "리커창", "푸틴", "메드베데프", "젤렌스키",
    "마크롱", "숄츠", "수낙", "존슨", "메르켈", "모디",
    "기시다", "아베", "스가", "이시바",
    "김정은", "김여정",
    # 국내 정치인
    "윤석열", "이재명", "한동훈", "이낙연", "문재인", "박근혜",
    "홍준표", "안철수", "오세훈", "원희룡",
    # 기업인·유명인
    "머스크", "베이조스", "버핏", "게이츠", "저커버그", "팀쿡",
    "이재용", "최태원", "정의선", "구광모",
    # 스포츠·연예
    "손흥민", "류현진", "오타니", "메시", "호날두",
    "BTS", "블랙핑크", "아이유", "뉴진스",
}

def get_climate_news(keyword, category):
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        )
    }

    category_map = {
        "전체 보기":  "",
        "경제":       "AND (물가 OR 피해액 OR 손실 OR 가격 OR 폭등)",
        "산업":       "AND (정전 OR 조업단축 OR 공장 OR 가동 OR 시설)",
        "무역":       "AND (수출 OR 물류 OR 운송 OR 항만 OR 공급망)",
        "국토교통":   "AND (도로 OR 철도 OR 침수 OR 붕괴 OR 교통)",
        "농림축산":   "AND (작황 OR 흉작 OR 고사 OR 폐사 OR 쌀 OR 과일)",
        "해양수산":   "AND (적조 OR 백화 OR 어획량 OR 양식장 OR 바다)",
        "보건복지":   "AND (질환 OR 온열 OR 감염병 OR 식중독 OR 환자)",
        "노동":       "AND (야외 OR 작업 OR 수칙 OR 휴식 OR 건설)",
        "교육":       "AND (휴교 OR 단축 OR 수업 OR 등하교 OR 학교)",
        "위기관리":   "AND (홍수 OR 가뭄 OR 폭설 OR 폭우 OR 태풍 OR 산불)",
        "외교안보":   "AND (재난 OR 이주민 OR 난민 OR 영토 OR 분쟁)",
        "국제기구":   "AND (엘니뇨 OR 라니냐 OR 보고서 OR WMO OR UN)",
    }

    # ── [A안] 유명인·인물 키워드 감지 → RSS 쿼리에 기후 서브키워드 강제 추가 ──
    # 이름 자체가 검색어일 때 기후 무관 기사가 무더기로 들어오는 문제 해결
    CLIMATE_SUBQUERY = (
        "AND (기후 OR 탄소 OR 환경 OR 에너지 OR 온실 OR 폭염 OR 폭우 OR "
        "태풍 OR 가뭄 OR 홍수 OR 산불 OR 신재생 OR ESG OR 파리협약 OR "
        "탄소중립 OR 기후변화 OR 이상기후 OR 온난화)"
    )

    is_person_keyword = any(p in keyword for p in PERSON_KEYWORDS)

    # 강화된 제외 쿼리
    exclude_query = (
        "-주말날씨 -일기예보 -출근길날씨 -오늘날씨 -오늘의날씨 "
        "-증시 -펀드 -테마주 -종목 -시황 -관련주 -특징주 -상한가 "
        "-장마감 -주가 -매수세 -목표주가 -선거 -대선 -총선 -지지율"
    )

    category_query = category_map.get(category, "")

    if is_person_keyword:
        # 유명인 검색: 기후 서브키워드를 RSS 쿼리에 강제 AND 삽입
        if category_query:
            query_text = f'"{keyword}" {CLIMATE_SUBQUERY} {category_query} {exclude_query}'
        else:
            query_text = f'"{keyword}" {CLIMATE_SUBQUERY} {exclude_query}'
    elif category_query:
        query_text = f'"{keyword}" {category_query} {exclude_query}'
    else:
        query_text = f'"{keyword}" {exclude_query}'

    encoded_query = urllib.parse.quote(query_text)
    url = (
        f"https://news.google.com/rss/search?q={encoded_query}"
        f"&hl=ko&gl=KR&ceid=KR:ko"
    )

    try:
        response = requests.get(url, headers=headers, timeout=10)
        if response.status_code != 200:
            return None, None

        soup = BeautifulSoup(response.text, "lxml-xml")
        items = soup.find_all("item")
        if not items:
            return None, None

        now = datetime.now(timezone.utc)
        major_news_list = []
        general_news_list = []

        # 제목 레벨 강경 제외 패턴
        strict_exclude_titles = [
            "오늘 날씨", "내일 날씨", "주말 날씨", "출근길 날씨", "퇴근길 날씨",
            "기상 예보", "날씨 예보", "특징주", "증시 리포트", "장마감",
            "상한가", "목표주가", "주가 전망", "관련주 분석",
        ]

        major_dict = {
            "조선":   ["chosun", "조선일보", "조선비즈"],
            "중앙":   ["joins", "joongang", "중앙일보"],
            "동아":   ["donga", "동아일보"],
            "KBS":    ["kbs"],
            "MBC":    ["imbc", "mbc"],
            "SBS":    ["sbs"],
            "연합":   ["yna", "연합뉴스"],
            "YTN":    ["ytn"],
            "JTBC":   ["jtbc"],
            "한겨레": ["hani", "한겨레"],
            "경향":   ["khan", "경향신문"],
            "헤럴드": ["heraldbiz", "헤럴드경제"],
            "국민":   ["kmib", "국민일보"],
            "문화":   ["munhwa", "문화일보"],
        }

        for item in items:
            title = item.title.get_text()
            link  = item.link.get_text()
            pub_date_str = item.pubDate.get_text() if item.pubDate else ""

            # 제목 레벨 하드 필터
            if any(bad in title for bad in strict_exclude_titles):
                continue

            try:
                parsed_date = email.utils.parsedate_to_datetime(pub_date_str)
                if parsed_date.tzinfo is None:
                    parsed_date = parsed_date.replace(tzinfo=timezone.utc)
            except Exception:
                continue

            if now - parsed_date > timedelta(days=30):
                continue

            formatted_date = parsed_date.strftime("%Y-%m-%d %H:%M")

            # ── AI 필터링 (confidence score 함께 저장) ──
            is_climate, confidence = predict_climate_news(title)
            if not is_climate:
                continue

            data_row = {
                "기사 제목": title,
                "기사 링크": link,
                "작성일":    formatted_date,
                "_raw_date": parsed_date,
                "우선순위":  "일반 기사",
                "AI 신뢰도": f"{confidence:.0%}",   # 표시용
                "_confidence": confidence,           # 정렬용
            }

            is_major = False
            lower_title = title.lower()
            lower_link  = link.lower()
            for media_name, kws in major_dict.items():
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
            return final_news, "1주일" if has_week else "한 달"

    except Exception:
        pass

    return None, None


# ─────────────────────────────────────────────────────────────────
# [2. UI]
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
    st.warning(
        "⚠️ 학습된 AI 모델이 없습니다. `augment_data.py` → `train.py` 순서로 실행 후 "
        "`./climate_model` 폴더가 생성되면 자동 활성화됩니다. "
        "현재는 키워드 기반 폴백으로 동작 중입니다."
    )
else:
    st.success(f"✅ AI 모델 활성화 중 — 신뢰도 임계값 {CLIMATE_THRESHOLD:.0%} 이상만 통과")

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
        if st.button(f"#{kw}", use_container_width=True, key=f"btn_{kw}"):
            trigger_keyword = kw

st.write(" ")

col_cat, col_inp, col_btn = st.columns([1.2, 2.5, 0.8])
categories = [
    "전체 보기", "경제", "산업", "무역", "국토교통", "농림축산",
    "해양수산", "보건복지", "노동", "교육", "위기관리", "외교안보", "국제기구",
]
with col_cat:
    selected_cat = st.selectbox("카테고리 선택", categories, label_visibility="collapsed")
with col_inp:
    keyword_input = st.text_input(
        "검색어 입력창",
        value=st.session_state.input_key_setter,
        placeholder="검색어를 입력하거나 위 추천 태그를 클릭하세요.",
        label_visibility="collapsed",
    )
with col_btn:
    search_button = st.button("뉴스 검색", use_container_width=True)

# 검색 트리거
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
elif keyword_input.strip() and keyword_input.strip() != st.session_state.current_keyword:
    run_search = True
    search_target_keyword = keyword_input.strip()
    st.session_state.input_key_setter = keyword_input.strip()

if run_search and search_target_keyword:
    with st.spinner(f"'{search_target_keyword}' 결과 가공 중..."):
        st.session_state.news_df = None
        # 유명인 여부 세션에 저장 (결과 화면 안내에 활용)
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

    # 유명인 검색 시 안내 배너
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
            st.markdown(f"**{idx+1}. [{row['기사 제목']}]({row['기사 링크']})**")
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
                if st.button("⬅️ 이전", use_container_width=True,
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
                if st.button("다음 ➡️", use_container_width=True,
                             disabled=(st.session_state.p_num == total_pages), key="btn_next"):
                    st.session_state.p_num += 1
                    st.rerun()

        st.write("---")
        with st.expander("원본 데이터 표 형태로 보기"):
            display_cols = [c for c in df.columns if not c.startswith("_")]
            st.dataframe(df[display_cols], use_container_width=True, hide_index=True)

    with tab2:
        st.write("📋 추출용 깨끗한 데이터셋을 파일로 저장할 수 있습니다.")
        display_cols = [c for c in df.columns if not c.startswith("_")]
        csv = df[display_cols].to_csv(index=False).encode("utf-8-sig")
        st.download_button(
            label="📥 엑셀(CSV) 다운로드",
            data=csv,
            file_name=f"Verified_{current_kw}_{current_cat}_뉴스데이터.csv",
            mime="text/csv",
            use_container_width=True,
            key="btn_download",
        )

    # ── 피드백 탭 ──────────────────────────────────────────────────
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
                st.dataframe(fb_df, use_container_width=True, hide_index=True)
            # 피드백 데이터도 CSV로 다운로드
            st.download_button(
                label="📥 피드백 데이터 다운로드 (재학습용)",
                data=fb_df.to_csv(index=False).encode("utf-8-sig"),
                file_name="feedback_data.csv",
                mime="text/csv",
                key="btn_fb_download",
            )

else:
    if st.session_state.get("search_failed", False):
        st.error(
            f"'{st.session_state.current_keyword}' 관련 뉴스가 없거나 "
            "AI가 노이즈로 판단해 모두 제외했습니다."
        )
    else:
        st.info("검색어를 입력하거나 추천 태그를 클릭해 조사를 시작하세요.")
