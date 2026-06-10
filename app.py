import streamlit as st
import requests
from bs4 import BeautifulSoup
import pandas as pd
import urllib.parse
from datetime import datetime, timezone, timedelta
import email.utils

# --- [1. 지능형 구글 RSS 뉴스 크롤링 & 정밀 매핑 함수] ---
def get_climate_news(keyword):
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }
    
    # 순수 기후/환경 기술어 리스트 (여기에 걸리면 1차 단순 쿼리로 변환)
    eco_words = ["기후", "탄소", "에너지", "온난화", "그린", "배출권", "재생", "CCUS", "발전", "오염", "친환경", "테크", "넷제로", "환경"]
    is_pure_eco = any(word in keyword for word in eco_words)
    
    # 💡 [핵심 수정 1] 구글 검색 쿼리 전면 단순화 (구글 엔진 검색 범위 극대화)
    # 구글 RSS 내부 연산자 버그를 막기 위해 특수 기호와 괄호를 없애고 직설적인 키워드로 쏩니다.
    if is_pure_eco:
        if keyword.upper() == "CCUS":
            # CCUS의 경우 관련 핵심 한글 용어를 구글에 직접 던져 검색 풀(Pool)을 3배 이상 넓힙니다.
            query_text = "CCUS 탄소포집"
        else:
            query_text = f"{keyword}"
    else:
        # 인물/기업 검색 시 기후 도메인이 흐려지지 않도록 결합
        query_text = f"{keyword} 기후 탄소"
        
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
        news_week = []  
        news_month = [] 
        
        for item in items:
            title = item.title.get_text()
            link = item.link.get_text()
            pub_date_str = item.pubDate.get_text() if item.pubDate else ""
            
            # 💡 [핵심 수정 2] 2차 제목 매핑 검증의 유연성 확보 (탈락 현상 원천 차단)
            if not is_pure_eco:
                # 인물/기업 검색 시: 제목에 이름과 기후 도메인 단어가 동시에 존재해야 노이즈 차단
                if keyword.lower() not in title.lower():
                    continue
                if not any(w in title for w in ["기후", "환경", "탄소", "에너지", "그린", "친환경", "신재생", "넷제로", "배출권"]):
                    continue
            else:
                # 순수 전문 용어(CCUS, 지구온난화 등) 검색 시:
                # 기사 제목에 원본 키워드가 직접 들어있거나, 기후/환경의 핵심적 맥락 단어가 포함되어 있다면 무조건 통과!
                if keyword.upper() == "CCUS":
                    # CCUS는 영문, 국문 풀이명, 포집 관련 단어 중 하나만 있어도 수집하도록 가드를 활짝 엽니다.
                    ccus_pass = ["ccus", "포집", "저장", "탄소", "이산화탄소", "넷제로"]
                    if not any(syn in title.lower() for syn in ccus_pass):
                        continue
                else:
                    # 지구온난화 등 일반 전문어 역시 검색어 본연의 단어나 핵심 기후 환경어 매칭 시 생존
                    eco_pass = [keyword.lower(), "기후", "탄소", "환경", "온난화", "그린"]
                    if not any(w in title.lower() for w in eco_pass):
                        continue
            
            # 날짜 파싱
            try:
                parsed_date = email.utils.parsedate_to_datetime(pub_date_str)
                if parsed_date.tzinfo is None:
                    parsed_date = parsed_date.replace(tzinfo=timezone.utc)
            except:
                continue
                
            time_delta = now - parsed_date
            formatted_date = parsed_date.strftime("%Y-%m-%d %H:%M")
            
            data_row = {
                "기사 제목": title, 
                "기사 링크": link, 
                "작성일": formatted_date,
                "_raw_date": parsed_date
            }
            
            if time_delta <= timedelta(days=7):
                news_week.append(data_row)
            if time_delta <= timedelta(days=30):
                news_month.append(data_row)
                
        # 데이터 수집 기간 매핑 (1주일 우선 -> 없으면 한 달 연장)
        if news_week:
            final_list = sorted(news_week, key=lambda x: x["_raw_date"], reverse=True)
            return final_list, "1주일"
        elif news_month:
            final_list = sorted(news_month, key=lambda x: x["_raw_date"], reverse=True)
            return final_list, "한 달"
            
    except Exception as e:
        pass
        
    return None, None

# --- [2. UI 및 세션 상태 최적화] ---
st.set_page_config(page_title="실시간 뉴스 수집기", page_icon="🌱", layout="wide")

if "search_word" not in st.session_state: st.session_state.search_word = "기후변화"
if "last_searched" not in st.session_state: st.session_state.last_searched = ""
if "news_df" not in st.session_state: st.session_state.news_df = None
if "p_num" not in st.session_state: st.session_state.p_num = 1
if "period_info" not in st.session_state: st.session_state.period_info = ""

st.markdown("""
    <style>
        .main-title { font-size: clamp(24px, 5vw, 36px); font-weight: 700; color: #2e7d32; margin-bottom: 5px; }
        .sub-title { font-size: clamp(13px, 3vw, 16px); color: #666666; margin-bottom: 15px; }
        .news-date { font-size: 12px; color: #888888; margin-top: 2px; }
        .keyword-label { font-size: 14px; font-weight: bold; color: #444444; margin-bottom: 5px; }
    </style>
    <div class="main-title">🌱 실시간 기후 뉴스 수집기</div>
    <div class="sub-title">검색어와 연관된 최신 기후 및 환경 기술 뉴스를 정확하게 수집합니다.</div>
""", unsafe_allow_html=True)

recommended_keywords = ["기후변화", "탄소중립", "신재생에너지", "CCUS", "지구온난화"]
st.markdown("<div class='keyword-label'>🔥 추천 키워드 바로 검색</div>", unsafe_allow_html=True)

kw_cols = st.columns(len(recommended_keywords))
for i, kw in enumerate(recommended_keywords):
    with kw_cols[i]:
        if st.button(f"#{kw}", use_container_width=True):
            st.session_state.search_word = kw
            with st.spinner(f"'{kw}' 최신 뉴스를 수집 중..."):
                res, period = get_climate_news(kw)
                if res:
                    st.session_state.news_df = pd.DataFrame(res)
                    st.session_state.period_info = period
                    st.session_state.last_searched = kw
                    st.session_state.p_num = 1
                else:
                    st.session_state.news_df = None
                    st.error("최근 수집된 뉴스 데이터가 없습니다.")

st.write(" ") 

col1, col2 = st.columns([3, 1])
with col1:
    keyword_input = st.text_input("검색어 입력", key="search_word", label_visibility="collapsed")
with col2:
    search_button = st.button("🔍 뉴스 검색", use_container_width=True)

# 엔터 키 및 검색 버튼 트리거 작동
is_enter_pressed = keyword_input and (keyword_input != st.session_state.last_searched)
trigger_search = search_button or is_enter_pressed

if trigger_search:
    with st.spinner(f"'{keyword_input}' 뉴스 매핑 및 정제 중..."):
        res, period = get_climate_news(keyword_input)
        if res:
            st.session_state.news_df = pd.DataFrame(res)
            st.session_state.period_info = period
            st.session_state.last_searched = keyword_input  
            st.session_state.p_num = 1
        else:
            st.session_state.news_df = None
            st.session_state.last_searched = keyword_input
            st.error(f"'{keyword_input}' 관련 최신 기후 뉴스가 없거나 수집에 실패했습니다.")

st.write("---")

# --- [3. 결과 레이아웃 디스플레이] ---
if st.session_state.news_df is not None:
    df = st.session_state.news_df
    current_kw = st.session_state.last_searched if st.session_state.last_searched else st.session_state.search_word
    period_text = st.session_state.period_info
    
    st.success(f"✨ '{current_kw}' 관련 {period_text} 이내 최신 뉴스 {len(df)}개 (최신순 정렬)")
    
    tab1, tab2 = st.tabs(["📰 뉴스 목록 보기", "📥 데이터 내보내기"])
    
    with tab1:
        st.write("📌 **기사 제목을 누르면 해당 언론사로 이동합니다.**")
        view_mode = st.radio("보기 모드 선택", ["모바일 피드 (전체 스크롤)", "PC 정돈 모드 (10개씩 보기)"], horizontal=True)
        st.write("---")
        
        if view_mode == "모바일 피드 (전체 스크롤)":
            for idx, row in df.iterrows():
                st.markdown(f"**{idx+1}. [{row['기사 제목']}]({row['기사 링크']})**")
                st.markdown(f"<div class='news-date'>⏱ 작성일: {row['작성일']}</div>", unsafe_allow_html=True)
                st.markdown("<div style='margin-bottom: 20px; border-bottom: 1px dashed #eee;'></div>", unsafe_allow_html=True)
        
        else:
            items_per_page = 10
            total_pages = (len(df) - 1) // items_per_page + 1
            
            st.session_state.p_num = min(st.session_state.p_num, total_pages)
            start_idx = (st.session_state.p_num - 1) * items_per_page
            end_idx = start_idx + items_per_page
            page_df = df.iloc[start_idx:end_idx]
            
            for idx, row in page_df.iterrows():
                st.markdown(f"**{idx+1}. [{row['기사 제목']}]({row['기사 링크']})**")
                st.markdown(f"<div class='news-date'>⏱ 작성일: {row['작성일']}</div>", unsafe_allow_html=True)
                st.markdown("<div style='margin-bottom: 15px;'></div>", unsafe_allow_html=True)
                
            st.write("---") 
            
            p_col1, p_col2, p_col3 = st.columns([1, 2, 1])
            with p_col1:
                if st.button("⬅️ 이전", use_container_width=True, disabled=(st.session_state.p_num == 1)):
                    st.session_state.p_num -= 1
                    st.rerun()
            with p_col2:
                st.markdown(f"<p style='text-align: center; line-height: 38px;'><b>{st.session_state.p_num} / {total_pages} 페이지</b></p>", unsafe_allow_html=True)
            with p_col3:
                if st.button("다음 ➡️", use_container_width=True, disabled=(st.session_state.p_num == total_pages)):
                    st.session_state.p_num += 1
                    st.rerun()
                
        st.write("---")
        with st.expander("📊 원본 데이터 표 형태로 보기"):
            st.dataframe(df.drop(columns=['_raw_date']), use_container_width=True, hide_index=True)
            
    with tab2:
        st.write("📋 수집된 뉴스 리스트를 파일로 저장할 수 있습니다.")
        csv = df.drop(columns=['_raw_date']).to_csv(index=False).encode('utf-8-sig')
        st.download_button(
            label="📥 엑셀(CSV) 다운로드",
            data=csv,
            file_name=f"{current_kw}_최신뉴스.csv",
            mime="text/csv",
            use_container_width=True
        )
else:
    st.info("검색어를 입력하거나 위의 추천 키워드를 눌러주세요.")