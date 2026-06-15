import streamlit as st
import requests
from bs4 import BeautifulSoup
import pandas as pd
import urllib.parse
from datetime import datetime, timezone, timedelta
import email.utils
import torch
from transformers import AutoModelForSequenceClassification, BertTokenizer

# ==========================================
# [0. 기후 AI 모델 원격 로드 및 예측 파이프라인]
# ==========================================
MODEL_PATH = "dlwjdgn8720/my-climate-kobert" 

@st.cache_resource
def load_climate_model():
    """
    허깅페이스 허브로부터 모델과 토크나이저를 원격 로드하여 캐싱합니다.
    로컬 경로 체크 로직을 완전히 제거하여 배포 환경(Streamlit Cloud)에서 정상 작동
    """
    try:
        tokenizer = BertTokenizer.from_pretrained(MODEL_PATH, use_fast=False)
        model = AutoModelForSequenceClassification.from_pretrained(MODEL_PATH)
        model.eval()
        return tokenizer, model
    except Exception as e:
        # 허깅페이스 로드 실패 시(네트워크 이슈 또는 비공개 저장소 등) 폴백용으로 None 반환
        st.session_state["model_load_error"] = str(e)
        return None, None

# 모델 및 토크나이저 초기화
tokenizer, model = load_climate_model()

def predict_climate_news(title):
    """
    뉴스 제목 문맥을 분석하여 진짜 기후 뉴스인지 판별합니다.
    리턴값: 1 (기후변화 인과관계 성립), 0 (단순 키워드 겹침/일반 뉴스)
    """
    if tokenizer is None or model is None:
        return 1 # 모델 로드 실패 시 크롤러 기본 필터링에 의존하도록 폴백 채택
        
    inputs = tokenizer(
        title, 
        return_tensors="pt", 
        truncation=True, 
        max_length=128, 
        padding=True
    )
    
    with torch.no_grad():
        outputs = model(**inputs)
        
    logits = outputs.logits
    prediction = torch.argmax(logits, dim=-1).item()
    return prediction


# --- [1. 지능형 구글 RSS 뉴스 크롤링 함수] ---
def get_climate_news(keyword, category):
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }
    
    category_map = {
        "전체 보기": "",
        "경제": "AND (물가 OR 피해액 OR 손실 OR 가격 OR 폭등)",
        "산업": "AND (정전 OR 조업단축 OR 공장 OR 가동 OR 시설)",
        "무역": "AND (수출 OR 물류 OR 운송 OR 항만 OR 공급망)",
        "국토교통": "AND (도로 OR 철도 OR 침수 OR 붕괴 OR 교통)",
        "농림축산": "AND (작황 OR 흉작 OR 고사 OR 폐사 OR 쌀 OR 과일)",
        "해양수산": "AND (적조 OR 백화 OR 어획량 OR 양식장 OR 바다)",
        "보건복지": "AND (질환 OR 온열 OR 감염병 OR 식중독 OR 환자)",
        "노동": "AND (야외 OR 작업 OR 수칙 OR 휴식 OR 건설)",
        "교육": "AND (휴교 OR 단축 OR 수업 OR 등하교 OR 학교)",
        "위기관리": "AND (홍수 OR 가뭄 OR 폭설 OR 폭우 OR 태풍 OR 산불)",
        "외교안보": "AND (재난 OR 이주민 OR 난민 OR 영토 OR 분쟁)",
        "국제기구": "AND (엘니뇨 OR 라니냐 OR 보고서 OR WMO OR UN)"
    }
    
    category_query = category_map.get(category, "")
    exclude_query = "-주말날씨 -일기예보 -출근길날씨 -오늘날씨 -증시 -펀드 -테마주 -종목 -시황"
    
    if category_query:
        query_text = f'"{keyword}" {category_query} {exclude_query}'
    else:
        query_text = f'"{keyword}" {exclude_query}'
        
    encoded_query = urllib.parse.quote(query_text)
    url = f"https://news.google.com/rss/search?q={encoded_query}&hl=ko&gl=KR&ceid=KR:ko"
    
    try:
        response = requests.get(url, headers=headers, timeout=10)
        if response.status_code != 200:
            return None, None
            
        soup = BeautifulSoup(response.text, 'lxml-xml')
        items = soup.find_all('item')
        
        if not items:
            return None, None
            
        now = datetime.now(timezone.utc)
        major_news_list = []  
        general_news_list = [] 
        
        strict_exclude_titles = [
            "오늘 날씨", "내일 날씨", "주말 날씨", "출근길 날씨", "퇴근길 날씨", 
            "특징주", "증시 리포트", "장마감"
        ]
        
        major_dict = {
            "조선": ["chosun", "조선일보", "조선비즈"],
            "중앙": ["joins", "joongang", "중앙일보"],
            "동아": ["donga", "동아일보"],
            "KBS": ["kbs", "KBS"],
            "MBC": ["imbc", "mbc", "MBC"],
            "SBS": ["sbs", "SBS"],
            "연합": ["yna", "연합뉴스", "연합뉴스TV"],
            "YTN": ["ytn", "YTN"],
            "JTBC": ["jtbc", "JTBC"],
            "한겨레": ["hani", "한겨레"],
            "경향": ["khan", "경향신문"],
            "헤럴드": ["heraldbiz", "헤럴드경제"],
            "국민": ["kmib", "국민일보"],
            "문화": ["munhwa", "문화일보"]
        }
        
        for item in items:
            title = item.title.get_text()
            link = item.link.get_text()
            pub_date_str = item.pubDate.get_text() if item.pubDate else ""
            
            if any(bad_word in title for bad_word in strict_exclude_titles):
                continue
            
            try:
                parsed_date = email.utils.parsedate_to_datetime(pub_date_str)
                if parsed_date.tzinfo is None:
                    parsed_date = parsed_date.replace(tzinfo=timezone.utc)
            except:
                continue
                
            time_delta = now - parsed_date
            if time_delta > timedelta(days=30):
                continue
                
            formatted_date = parsed_date.strftime("%Y-%m-%d %H:%M")
            
            data_row = {
                "기사 제목": title, 
                "기사 링크": link, 
                "작성일": formatted_date,
                "_raw_date": parsed_date,
                "우선순위": "일반 기사"
            }
            
            # [Hugging Face AI 모델 기반 문맥 필터링 작동]
            if predict_climate_news(title) == 0:
                continue
            
            is_major = False
            lower_title = title.lower()
            lower_link = link.lower()
            
            for media_name, keywords in major_dict.items():
                if any(kw in lower_title or kw in lower_link for kw in keywords):
                    is_major = True
                    data_row["우선순위"] = f"⭐ {media_name}"
                    break
            
            if is_major:
                major_news_list.append(data_row)
            else:
                general_news_list.append(data_row)
                
        sorted_major = sorted(major_news_list, key=lambda x: x["_raw_date"], reverse=True)
        sorted_general = sorted(general_news_list, key=lambda x: x["_raw_date"], reverse=True)
        final_news = sorted_major + sorted_general
        
        if final_news:
            has_week = any((now - x["_raw_date"]) <= timedelta(days=7) for x in final_news)
            period_label = "1주일" if has_week else "한 달"
            return final_news, period_label
            
    except Exception as e:
        pass
        
    return None, None


# --- [2. UI 및 세션 상태 동적 초기화] ---
st.set_page_config(page_title="기후 뉴스 수집기", page_icon="🌱", layout="wide")

if "news_df" not in st.session_state: st.session_state.news_df = None
if "p_num" not in st.session_state: st.session_state.p_num = 1
if "period_info" not in st.session_state: st.session_state.period_info = ""
if "current_keyword" not in st.session_state: st.session_state.current_keyword = ""
if "current_category" not in st.session_state: st.session_state.current_category = "전체 보기"
if "input_key_setter" not in st.session_state: st.session_state.input_key_setter = ""

# CSS 스타일 정의: 글자 짤림 방지 및 노멀 컴포넌트 정돈
st.markdown("""
    <style>
        .main-title { font-size: 28px; font-weight: 700; color: #1e4620; margin-bottom: 5px; }
        .sub-title { font-size: 14px; color: #555555; margin-bottom: 25px; }
        .news-date { font-size: 12px; color: #888888; margin-top: 2px; }
        .keyword-label { font-size: 14px; font-weight: 600; color: #444444; margin-bottom: 8px; }
        .badge-major { background-color: #e8f5e9; color: #2e7d32; padding: 2px 6px; border-radius: 4px; font-size: 11px; font-weight: bold; }
        .badge-general { background-color: #f5f5f5; color: #666666; padding: 2px 6px; border-radius: 4px; font-size: 11px; }
        
        /* 버튼 텍스트 줄바꿈 강제 금지 및 가로 너비 확보로 글자 짤림 현상 전면 차단 */
        div.stButton > button { white-space: nowrap !important; min-width: max-content !important; }
    </style>
""", unsafe_allow_html=True)

st.markdown("""
    <div class="main-title">기후변화 영향 뉴스 수집 시스템</div>
    <div class="sub-title">구글 RSS 뉴스를 실시간 수집하고 AI 가드레일 모델을 통해 관련성을 검증합니다.</div>
""", unsafe_allow_html=True)

# 로드된 토큰 및 모델 메모리 변수 상태를 감지하여 하단 서브바 출력
if tokenizer is not None and model is not None:
    st.caption("🤖 **AI Guardrail Engine 상태:** `🟢 허깅페이스 원격 KoBERT 필터링 활성화` | 문맥 맞춤형 노이즈 자동 제거 중")
else:
    st.error("⚠️ 학습된 AI 모델이 저장소로부터 로드되지 않았습니다. 현재는 키워드 기반 폴백 모드로 연동 구동 중입니다.")
    if "model_load_error" in st.session_state:
        st.info(f"📋 **실제 모델 로드 에러 로그:** {st.session_state['model_load_error']}")

# 추천 키워드 배열 구조
recommended_keywords = ["기후변화", "탄소중립", "신재생에너지", "CCUS", "식량", "물가", "에너지"]
st.markdown("<div class='keyword-label'>추천 키워드 검색</div>", unsafe_allow_html=True)

trigger_keyword = None
kw_cols = st.columns(len(recommended_keywords))
for i, kw in enumerate(recommended_keywords):
    with kw_cols[i]:
        if st.button(f"#{kw}", use_container_width=True, key=f"btn_{kw}"):
            trigger_keyword = kw

st.write(" ") 

col_cat, col_inp, col_btn = st.columns([1.2, 2.5, 0.8])
categories = ["전체 보기", "경제", "산업", "무역", "국토교통", "농림축산", "해양수산", "보건복지", "노동", "교육", "위기관리", "외교안보", "국제기구"]

with col_cat:
    selected_cat = st.selectbox("카테고리 선택", categories, label_visibility="collapsed")
with col_inp:
    keyword_input = st.text_input(
        "검색어 입력창", 
        value=st.session_state.input_key_setter,
        placeholder="검색어를 입력하거나 위 추천 태그를 클릭하세요.", 
        label_visibility="collapsed"
    )

with col_btn:
    search_button = st.button("뉴스 검색", use_container_width=True)

# 키워드 꼬임 및 루프 간섭 방지 최적화 제어문 구역
run_search = False
search_target_keyword = ""

if trigger_keyword:
    run_search = True
    search_target_keyword = trigger_keyword
    st.session_state.input_key_setter = ""  # 추천 태그 클릭 시 기존 검색 텍스트 필드를 깨끗하게 초기화
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
        
        res, period = get_climate_news(search_target_keyword, selected_cat)
        if res:
            st.session_state.news_df = pd.DataFrame(res)
            st.session_state.period_info = period
            st.session_state.current_keyword = search_target_keyword
            st.session_state.current_category = selected_cat
            st.session_state.p_num = 1
            if "search_failed" in st.session_state: del st.session_state.search_failed
        else:
            st.session_state.news_df = None
            st.session_state.current_keyword = search_target_keyword
            st.session_state.current_category = selected_cat
            st.session_state.search_failed = True
        st.rerun()

st.write("---")

# 데이터 동적 렌더링 파트
if st.session_state.news_df is not None:
    df = st.session_state.news_df
    current_kw = st.session_state.current_keyword
    current_cat = st.session_state.current_category
    period_text = st.session_state.period_info
    
    st.success(f"'{current_kw}' [{current_cat}] → 필터링 통과 결과 (최근 {period_text} 이내 총 {len(df)}건 검증 완료)")
    
    tab1, tab2 = st.tabs(["뉴스 목록 보기", "데이터 내보내기"])
    
    with tab1:
        st.write("📌 기사 제목을 누르면 해당 뉴스 원문 페이지로 이동합니다.")
        view_mode = st.radio("보기 모드 선택", ["모바일 피드 (전체 스크롤)", "PC 정돈 모드 (10개씩 보기)"], horizontal=True, key="view_mode_select")
        st.write("---")
        
        if view_mode == "모바일 피드 (전체 스크롤)":
            for idx, row in df.iterrows():
                badge_class = "badge-major" if "⭐" in row['우선순위'] else "badge-general"
                st.markdown(f"**{idx+1}. [{row['기사 제목']}]({row['기사 링크']})**")
                st.markdown(f"<span class='{badge_class}'>{row['우선순위']}</span> &nbsp;&nbsp; <span class='news-date'>⏱ 작성일: {row['작성일']}</span>", unsafe_allow_html=True)
                st.markdown("<div style='margin-bottom: 20px; border-bottom: 1px dashed #eee;'></div>", unsafe_allow_html=True)
        
        else:
            items_per_page = 10
            total_pages = (len(df) - 1) // items_per_page + 1
            st.session_state.p_num = min(st.session_state.p_num, total_pages)
            start_idx = (st.session_state.p_num - 1) * items_per_page
            end_idx = start_idx + items_per_page
            page_df = df.iloc[start_idx:end_idx]
            
            for idx, row in page_df.iterrows():
                badge_class = "badge-major" if "⭐" in row['우선순위'] else "badge-general"
                st.markdown(f"**{idx+1}. [{row['기사 제목']}]({row['기사 링크']})**")
                st.markdown(f"<span class='{badge_class}'>{row['우선순위']}</span> &nbsp;&nbsp; <span class='news-date'>⏱ 작성일: {row['작성일']}</span>", unsafe_allow_html=True)
                st.markdown("<div style='margin-bottom: 15px;'></div>", unsafe_allow_html=True)
                
            st.write("---") 
            p_col1, p_col2, p_col3 = st.columns([1, 2, 1])
            with p_col1:
                if st.button("⬅️ 이전", use_container_width=True, disabled=(st.session_state.p_num == 1), key="btn_prev"):
                    st.session_state.p_num -= 1
                    st.rerun()
            with p_col2:
                st.markdown(f"<p style='text-align: center; line-height: 38px;'><b>{st.session_state.p_num} / {total_pages} 페이지</b></p>", unsafe_allow_html=True)
            with p_col3:
                if st.button("다음 ➡️", use_container_width=True, disabled=(st.session_state.p_num == total_pages), key="btn_next"):
                    st.session_state.p_num += 1
                    st.rerun()
                
        st.write("---")
        with st.expander("원본 데이터 표 형태로 보기"):
            st.dataframe(df.drop(columns=['_raw_date']), use_container_width=True, hide_index=True)
            
    with tab2:
        st.write("📋 추출용 깨끗한 데이터셋을 파일로 저장할 수 있습니다.")
        csv = df.drop(columns=['_raw_date']).to_csv(index=False).encode('utf-8-sig')
        st.download_button(
            label="📥 엑셀(CSV) 다운로드",
            data=csv,
            file_name=f"Verified_{current_kw}_{current_cat}_뉴스데이터.csv",
            mime="text/csv",
            use_container_width=True,
            key="btn_download"
        )
else:
    if st.session_state.get("search_failed", False):
        st.error(f"'{st.session_state.current_keyword}' 관련 뉴스가 없거나 AI가 노이즈로 판단해 제외했습니다.")
    else:
        st.info("검색어를 입력하거나 추천 태그를 클릭해 조사를 시작하세요.")