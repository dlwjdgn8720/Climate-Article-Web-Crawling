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
    
    # 💡 [요구사항 2] eco_words에서 'AI' 완전 제거
    eco_words = ["기후", "탄소", "에너지", "온난화", "그린", "배출권", "재생", "CCUS", "발전", "오염", "친환경", "테크"]
    is_pure_eco = any(word in keyword for word in eco_words)
    
    # 💡 [요구사항 4, 5] 구글 검색 엔진용 쿼리 튜닝 및 노이즈 필터링
    # 구글 엔진이 오작동하지 않도록 쿼리를 가장 인지하기 쉬운 형태로 최적화합니다.
    if is_pure_eco:
        query_text = f"{keyword}"
    else:
        # 인물 검색 시 '정치 생태계', '근무 환경' 같은 일반 명사 노이즈를 피하기 위해 확실한 기후 테크 단어를 결합
        query_text = f'"{keyword}" (기후 OR 탄소 OR 친환경 OR "그린 테크")'
        
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
            
            # 인물/기업 검색 시 제목에 해당 검색어가 실물로 들어있는지 정밀 매핑
            if not is_pure_eco:
                if keyword.lower() not in title.lower():
                    continue
            
            # 날짜 파싱 및 동기화
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
            
            # 💡 [요구사항 1] 날짜별 데이터 분류 (1주일 내 데이터를 우선으로 수집)
            if time_delta <= timedelta(days=7):
                news_week.append(data_row)
            if time_delta <= timedelta(days=30):
                news_month.append(data_row)
                
        # 데이터가 많은 순서대로 최신순 정렬 후 반환
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

# 세션 상태 변수 초기화
if "search_word" not in st.session_state: st.session_state.search_word = "기후변화"
if "last_searched" not in st.session_state: st.session_state.last_searched = ""
if "news_df" not in st.session_state: st.session_state.news_df = None
if "p_num" not in st.session_state: st.session_state.p_num = 1
if "period_info" not in st.session_state: st.session_state.period_info = ""

# 💡 [요구사항 1] 헤더에서 '칼같이' 단어 제외 및 문구 정돈
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

# 추천 키워드 영역
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

# 입력창과 일반 검색 버튼 영역
col1, col2 = st.columns([3, 1])
with col1:
    keyword_input = st.text_input("검색어 입력", key="search_word", label_visibility="collapsed")
with col2:
    search_button = st.button("🔍 뉴스 검색", use_container_width=True)

# 💡 [요구사항 3] 엔터(Enter) 키 입력 및 검색 버튼 트리거 작동 원리 복원
# 입력창의 글자가 직전에 검색에 성공했던 단어와 다르면 엔터를 친 것으로 간주하여 크롤링을 수행합니다.
is_enter_pressed = keyword_input and (keyword_input != st.session_state.last_searched)
trigger_search = search_button or is_enter_pressed

if trigger_search:
    with st.spinner(f"'{keyword_input}' 뉴스 매핑 및 정제 중..."):
        res, period = get_climate_news(keyword_input)
        if res:
            st.session_state.news_df = pd.DataFrame(res)
            st.session_state.period_info = period
            st.session_state.last_searched = keyword_input  # 검색 기록 동기화로 무한 루프 방지
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