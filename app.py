import streamlit as st
import requests
from bs4 import BeautifulSoup
import pandas as pd
import urllib.parse
from datetime import datetime

# --- [1. 구글 RSS 뉴스 크롤링 함수 (1주일 제한 및 최신순 정렬)] ---
def get_climate_news(keyword):
    # 한글 검색어 인코딩 및 1주일 이내 필터(when:7d) 추가
    query = f"{keyword} when:7d"
    encoded_query = urllib.parse.quote(query)
    
    url = f"https://news.google.com/rss/search?q={encoded_query}&hl=ko&gl=KR&ceid=KR:ko"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }
    try:
        response = requests.get(url, headers=headers)
        if response.status_code == 200:
            soup = BeautifulSoup(response.text, 'lxml-xml')
            items = soup.find_all('item')
            
            news_list = []
            for item in items:
                title = item.title.get_text()
                link = item.link.get_text()
                
                # 구글 RSS가 제공하는 기사 작성일(pubDate) 파싱
                pub_date_str = item.pubDate.get_text() if item.pubDate else ""
                
                # 정렬을 위해 datetime 객체로 변환 시도 (안 되면 현재 시간 기본값)
                try:
                    # 예: "Tue, 09 Jun 2026 06:00:00 GMT" 포맷 파싱
                    pub_date = datetime.strptime(pub_date_str, "%a, %d %b %Y %H:%M:%S %Z")
                except:
                    pub_date = datetime.now()
                
                # 가독성을 위해 보기 좋은 날짜 포맷으로 변경
                formatted_date = pub_date.strftime("%Y-%m-%d %H:%M")
                
                news_list.append({
                    "기사 제목": title, 
                    "기사 링크": link, 
                    "작성일": formatted_date,
                    "_raw_date": pub_date # 정렬용 숨김 데이터
                })
            
            if news_list:
                # 💡 [핵심] 최근 데이터가 맨 위로 오도록 내림차순 정렬
                news_list = sorted(news_list, key=lambda x: x["_raw_date"], reverse=True)
                
            return news_list
        return None
    except Exception as e:
        st.error(f"데이터 오류: {e}")
        return None

# --- [2. Streamlit 반응형 UI 설정] ---
st.set_page_config(page_title="실시간 뉴스 수집기", page_icon="🌱", layout="wide")

# CSS 스타일 (타이틀 크기 및 레이아웃 최적화)
st.markdown("""
    <style>
        .main-title { font-size: clamp(24px, 5vw, 36px); font-weight: 700; color: #2e7d32; margin-bottom: 5px; }
        .sub-title { font-size: clamp(13px, 3vw, 16px); color: #666666; margin-bottom: 20px; }
        .news-date { font-size: 12px; color: #888888; margin-top: 2px; }
    </style>
    <div class="main-title">🌱 실시간 기후 뉴스 (최신 1주일)</div>
    <div class="sub-title">최근 7일간의 뉴스를 가장 빠르게 확인하세요.</div>
""", unsafe_allow_html=True)

# 입력창과 버튼 배치
col1, col2 = st.columns([3, 1])
with col1:
    keyword_input = st.text_input("검색어 입력", value="기후변화", label_visibility="collapsed")
with col2:
    search_button = st.button("🔍 뉴스 검색", use_container_width=True)

st.write("---")

# 세션 상태 초기화 (검색 결과 및 페이지 번호 기억)
if "crawled_df" not in st.session_state: st.session_state.crawled_df = None
if "current_keyword" not in st.session_state: st.session_state.current_keyword = ""
if "page_number" not in st.session_state: st.session_state.page_number = 1

# 검색 작동 로직 (새 검색 시 페이지를 1페이지로 리셋)
if search_button or (keyword_input and keyword_input != st.session_state.current_keyword):
    with st.spinner('최신 뉴스를 가져오는 중...'):
        data = get_climate_news(keyword_input)
        if data:
            st.session_state.crawled_df = pd.DataFrame(data)
            st.session_state.current_keyword = keyword_input
            st.session_state.page_number = 1 # 페이지 리셋
        else:
            st.session_state.crawled_df = None
            st.error("최근 1주일간의 뉴스 피드를 가져오지 못했습니다.")

# --- [3. 결과 레이아웃 구성] ---
if st.session_state.crawled_df is not None:
    df = st.session_state.crawled_df
    keyword = st.session_state.current_keyword
    
    st.success(f"✨ '{keyword}' 관련 최신 뉴스 {len(df)}개")
    
    tab1, tab2 = st.tabs(["📰 뉴스 목록 보기", "📥 데이터 내보내기"])
    
    with tab1:
        st.write("📌 **기사 제목을 누르면 해당 언론사로 이동합니다.**")
        
        # 💡 [반응형 UI 선택 버튼] 사용자가 PC 환경인지 모바일 환경인지 선택하게 하거나, 디폴트로 제공
        # Streamlit은 접속 기기를 자동 감지하기 어렵기 때문에, 깔끔하게 보기를 나눕니다.
        view_mode = st.radio("보기 모드 선택", ["모바일 피드 (전체 스크롤)", "PC 정돈 모드 (10개씩 보기)"], horizontal=True)
        st.write("---")
        
        if view_mode == "모바일 피드 (전체 스크롤)":
            # 📱 모바일용: 한 장의 피드처럼 모든 데이터 정렬 출력
            for idx, row in df.iterrows():
                st.markdown(f"**{idx+1}. [{row['기사 제목']}]({row['기사 링크']})**")
                st.markdown(f"<div class='news-date'>⏱ 작성일: {row['작성일']}</div>", unsafe_allow_html=True)
                st.markdown("<div style='margin-bottom: 20px; border-bottom: 1px dashed #eee;'></div>", unsafe_allow_html=True)
        
        else:
            # 💻 PC용: 10개씩 페이징 처리
            items_per_page = 10
            total_pages = (len(df) - 1) // items_per_page + 1
            
            # 페이지 이동 컨트롤러
            p_col1, p_col2, p_col3 = st.columns([1, 2, 1])
            with p_col1:
                if st.button("⬅️ 이전", disable_processing=True, use_container_width=True) and st.session_state.page_number > 1:
                    st.session_state.page_number -= 1
                    st.rerun()
            with p_col2:
                st.markdown(f"<p style='text-align: center;'><b>{st.session_state.page_number} / {total_pages} 페이지</b></p>", unsafe_allow_html=True)
            with p_col3:
                if st.button("다음 ➡️", disable_processing=True, use_container_width=True) and st.session_state.page_number < total_pages:
                    st.session_state.page_number += 1
                    st.rerun()
            
            # 현재 페이지에 해당하는 데이터 계산 슬라이싱
            start_idx = (st.session_state.page_number - 1) * items_per_page
            end_idx = start_idx + items_per_page
            page_df = df.iloc[start_idx:end_idx]
            
            # 현재 페이지 데이터 출력
            for idx, row in page_df.iterrows():
                st.markdown(f"**{idx+1}. [{row['기사 제목']}]({row['기사 링크']})**")
                st.markdown(f"<div class='news-date'>⏱ 작성일: {row['작성일']}</div>", unsafe_allow_html=True)
                st.markdown("<div style='margin-bottom: 15px;'></div>", unsafe_allow_html=True)
                
        st.write("---")
        with st.expander("📊 원본 데이터 표 형태로 보기"):
            st.dataframe(df.drop(columns=['_raw_date']), use_container_width=True, hide_index=True)
            
    with tab2:
        st.write("📋 수집된 뉴스 리스트를 파일로 저장할 수 있습니다.")
        csv = df.drop(columns=['_raw_date']).to_csv(index=False).encode('utf-8-sig')
        st.download_button(
            label="📥 엑셀(CSV) 다운로드",
            data=csv,
            file_name=f"{keyword}_최신뉴스.csv",
            mime="text/csv",
            use_container_width=True
        )
else:
    st.info("검색어를 입력하고 검색 버튼을 눌러주세요.")