import streamlit as st
import requests
from bs4 import BeautifulSoup
import pandas as pd
import urllib.parse
from datetime import datetime

# --- [1. 구글 RSS 뉴스 크롤링 함수] ---
def get_climate_news(keyword):
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }
    
    # 인물/기업용 필터 단어 정의
    eco_words = ["기후", "환경", "탄소", "에너지", "온난화", "그린", "배출권", "재생", "CCUS", "발전", "오염", "생태"]
    is_pure_eco = any(word in keyword for word in eco_words)
    
    # 💡 쿼리를 직관적이고 직설적으로 수정 (구글 엔진 인지율 상승)
    if is_pure_eco:
        tech_filter = "기후 환경 탄소"
    else:
        tech_filter = "(기후 OR 환경 OR 탄소 OR 에너지 OR AI OR 기술)"
        
    essential_words = eco_words + ["earth-2", "fourcastnet", "기상", "시뮬레이터", "친환경", "인공지능", "AI", "테크", "녹색"]

    # 1주 -> 2주 -> 3주 순으로 확장 검색
    for weeks in [1, 2, 3]:
        # 구글 RSS가 가장 잘 씹어먹는 쿼리 포맷으로 변경
        query = f"{keyword} {tech_filter} when:{weeks}w"
        encoded_query = urllib.parse.quote(query)
        url = f"https://news.google.com/rss/search?q={encoded_query}&hl=ko&gl=KR&ceid=KR:ko"
        
        try:
            response = requests.get(url, headers=headers, timeout=5)
            if response.status_code != 200:
                continue
                
            soup = BeautifulSoup(response.text, 'lxml-xml')
            items = soup.find_all('item')
            
            if not items:
                continue
                
            news_list = []
            for item in items:
                title = item.title.get_text()
                link = item.link.get_text()
                pub_date_str = item.pubDate.get_text() if item.pubDate else ""
                
                # 제목 검증 느슨하게 조정 (필터링 때문에 데이터가 통째로 사라지는 현상 방지)
                has_essential = any(word.lower() in title.lower() for word in essential_words)
                is_kw_in = keyword.lower() in title.lower()
                
                if not (has_essential or is_kw_in):
                    continue
                
                try:
                    pub_date = datetime.strptime(pub_date_str, "%a, %d %b %Y %H:%M:%S %Z")
                except:
                    pub_date = datetime.now()
                
                formatted_date = pub_date.strftime("%Y-%m-%d %H:%M")
                news_list.append({
                    "기사 제목": title, 
                    "기사 링크": link, 
                    "작성일": formatted_date,
                    "_raw_date": pub_date
                })
                
            if news_list:
                news_list = sorted(news_list, key=lambda x: x["_raw_date"], reverse=True)
                if weeks > 1:
                    st.toast(f"💡 최근 1주일 내 뉴스가 없어 {weeks}주일 전으로 확장했습니다.", icon="ℹ️")
                return news_list
                
        except Exception as e:
            continue
            
    return None

# --- [2. UI 설정 및 세션 상태 관리] ---
st.set_page_config(page_title="실시간 뉴스 수집기", page_icon="🌱", layout="wide")

# 💡 복잡한 세션 변수를 다 걷어내고 딱 3개로만 직관적으로 통제
if "search_word" not in st.session_state: st.session_state.search_word = "기후변화"
if "news_df" not in st.session_state: st.session_state.news_df = None
if "p_num" not in st.session_state: st.session_state.p_num = 1

# CSS 스타일 정의
st.markdown("""
    <style>
        .main-title { font-size: clamp(24px, 5vw, 36px); font-weight: 700; color: #2e7d32; margin-bottom: 5px; }
        .sub-title { font-size: clamp(13px, 3vw, 16px); color: #666666; margin-bottom: 15px; }
        .news-date { font-size: 12px; color: #888888; margin-top: 2px; }
        .keyword-label { font-size: 14px; font-weight: bold; color: #444444; margin-bottom: 5px; }
    </style>
    <div class="main-title">🌱 실시간 기후 뉴스 (최신 1주일)</div>
    <div class="sub-title">최근 7일간의 뉴스를 가장 빠르게 확인하세요.</div>
""", unsafe_allow_html=True)

# 추천 키워드 영역
recommended_keywords = ["기후변화", "탄소중립", "신재생에너지", "CCUS", "지구온난화"]
st.markdown("<div class='keyword-label'>🔥 추천 키워드 바로 검색</div>", unsafe_allow_html=True)

# 💡 추천 키워드 클릭 시 동작 버그 완전 해결
kw_cols = st.columns(len(recommended_keywords))
for i, kw in enumerate(recommended_keywords):
    with kw_cols[i]:
        if st.button(f"#{kw}", use_container_width=True):
            st.session_state.search_word = kw
            # 버튼을 누르는 순간 즉시 크롤링을 수행하여 변수 꼬임을 원천 차단
            with st.spinner(f"'{kw}' 최신 뉴스를 가져오는 중..."):
                res = get_climate_news(kw)
                if res:
                    st.session_state.news_df = pd.DataFrame(res)
                    st.session_state.p_num = 1
                else:
                    st.session_state.news_df = None
                    st.error("뉴스 데이터를 가져오지 못했습니다.")

st.write(" ") 

# 입력창과 검색 버튼 배치
col1, col2 = st.columns([3, 1])
with col1:
    # 세션 변수와 직접 바인딩하여 껍데기와 알맹이를 완벽히 일치시킴
    keyword_input = st.text_input("검색어 입력", key="search_word", label_visibility="collapsed")
with col2:
    search_button = st.button("🔍 뉴스 검색", use_container_width=True)

# 💡 일반 검색 버튼이나 엔터 입력 처리
if search_button:
    with st.spinner(f"'{keyword_input}' 최신 뉴스를 가져오는 중..."):
        res = get_climate_news(keyword_input)
        if res:
            st.session_state.news_df = pd.DataFrame(res)
            st.session_state.p_num = 1
        else:
            st.session_state.news_df = None
            st.error("뉴스 데이터를 가져오지 못했습니다.")

st.write("---")

# --- [3. 결과 레이아웃 화면 출력] ---
if st.session_state.news_df is not None:
    df = st.session_state.news_df
    
    st.success(f"✨ '{st.session_state.search_word}' 관련 최신 뉴스 {len(df)}개")
    
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
            # PC용 페이징 
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
            file_name=f"{st.session_state.search_word}_최신뉴스.csv",
            mime="text/csv",
            use_container_width=True
        )
else:
    st.info("검색어를 입력하거나 위의 추천 키워드를 눌러주세요.")