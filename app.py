import streamlit as st
import requests
from bs4 import BeautifulSoup
import pandas as pd
import urllib.parse
from datetime import datetime

# --- [1. 구글 RSS 뉴스 크롤링 함수 (기후/환경 노이즈 필터링 강화)] ---
def get_climate_news(keyword):
    # 💡 1차 대책: 구글 검색 연산자 활용
    # 사용자가 친 검색어 외에 환경 관련 핵심 단어들 중 하나가 '반드시(AND)' 포함되도록 검색 쿼리를 짭니다.
    # 예: "키워드 (기후 OR 환경 OR 탄소 OR 에너지 OR 온난화) when:7d"
    refined_query = f"{keyword} (기후 OR 환경 OR 탄소 OR 에너지 OR 온난화) when:7d"
    encoded_query = urllib.parse.quote(refined_query)
    
    url = f"https://news.google.com/rss/search?q={encoded_query}&hl=ko&gl=KR&ceid=KR:ko"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }
    
    # 💡 2차 대책: 파이썬 코드단에서 제목 검사하기 위한 '필수 환경 키워드 세트'
    # 이 단어들이 제목에 '아예' 없는 뚱딴지같은 기사는 과감히 버립니다.
    essential_words = ["기후", "환경", "탄소", "에너지", "온난화", "그린", "배출권", "재생", "CCUS", "발전", "오염", "생태"]
    
    try:
        response = requests.get(url, headers=headers)
        if response.status_code == 200:
            soup = BeautifulSoup(response.text, 'lxml-xml')
            items = soup.find_all('item')
            
            news_list = []
            for item in items:
                title = item.title.get_text()
                link = item.link.get_text()
                pub_date_str = item.pubDate.get_text() if item.pubDate else ""
                
                # 💡 [2차 필터링 로직 작동]
                # 제목에 필수 단어가 하나라도 들어있는지 검사합니다.
                # 단, 사용자가 직접 검색창에 입력한 검색어(keyword)가 들어있는 경우는 예외로 통과시킵니다.
                has_essential_word = any(word in title for word in essential_words)
                is_keyword_included = keyword in title
                
                if not (has_essential_word or is_keyword_included):
                    continue # 둘 다 해당 안 되면 기사 목록에 안 넣고 패스(삭제)!
                
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
            return news_list
        return None
    except Exception as e:
        st.error(f"데이터 오류: {e}")
        return None

# --- [2. Streamlit 반응형 UI 설정] ---
st.set_page_config(page_title="실시간 뉴스 수집기", page_icon="🌱", layout="wide")

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

# 💡 [세션 상태 관리]: 검색어와 데이터 변수들을 미리 초기화합니다.
if "search_keyword" not in st.session_state: st.session_state.search_keyword = "기후변화"
if "crawled_df" not in st.session_state: st.session_state.crawled_df = None
if "current_keyword" not in st.session_state: st.session_state.current_keyword = ""
if "page_number" not in st.session_state: st.session_state.page_number = 1

# 💡 [추천 키워드 학습/설정 파트]: 여기에 원하는 키워드를 마음껏 추가하거나 변경하세요!
recommended_keywords = ["기후변화", "탄소중립", "신재생에너지", "CCUS", "지구온난화"]

st.markdown("<div class='keyword-label'>🔥 추천 키워드 바로 검색</div>", unsafe_allow_html=True)

# 추천 키워드 버튼들을 한 줄로 이쁘게 배치 (모바일에서는 자동으로 흐름 정렬됨)
kw_cols = st.columns(len(recommended_keywords))
for i, kw in enumerate(recommended_keywords):
    with kw_cols[i]:
        # 버튼을 누르면 해당 키워드가 세션 상태에 즉시 반영되고 페이지가 새로고침됩니다.
        if st.button(f"#{kw}", use_container_width=True):
            st.session_state.search_keyword = kw

st.write(" ") # 미세 여백 조절

# 입력창과 버튼 배치 (value 값에 세션에 저장된 검색어가 연동됩니다)
col1, col2 = st.columns([3, 1])
with col1:
    keyword_input = st.text_input("검색어 입력", value=st.session_state.search_keyword, label_visibility="collapsed")
with col2:
    search_button = st.button("🔍 뉴스 검색", use_container_width=True)

st.write("---")

# 검색 실행 로직 체크 (직접 검색 버튼을 누름 / 엔터를 침 / 혹은 추천 키워드 버튼을 클릭해서 세션 값이 바뀜)
trigger_search = search_button or (keyword_input and keyword_input != st.session_state.current_keyword)

if trigger_search:
    with st.spinner(f"'{keyword_input}' 최신 뉴스를 가져오는 중..."):
        data = get_climate_news(keyword_input)
        if data:
            st.session_state.crawled_df = pd.DataFrame(data)
            st.session_state.current_keyword = keyword_input
            st.session_state.search_keyword = keyword_input # 현재 쳐진 텍스트 상태 동기화
            st.session_state.page_number = 1 # 페이지 리셋
        else:
            st.session_state.crawled_df = None
            st.error(f"최근 1주일간의 '{keyword_input}' 뉴스 피드를 가져오지 못했습니다.")

# --- [3. 결과 레이아웃 구성] ---
if st.session_state.crawled_df is not None:
    df = st.session_state.crawled_df
    keyword = st.session_state.current_keyword
    
    st.success(f"✨ '{keyword}' 관련 최신 뉴스 {len(df)}개")
    
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
            
            start_idx = (st.session_state.page_number - 1) * items_per_page
            end_idx = start_idx + items_per_page
            page_df = df.iloc[start_idx:end_idx]
            
            for idx, row in page_df.iterrows():
                st.markdown(f"**{idx+1}. [{row['기사 제목']}]({row['기사 링크']})**")
                st.markdown(f"<div class='news-date'>⏱ 작성일: {row['작성일']}</div>", unsafe_allow_html=True)
                st.markdown("<div style='margin-bottom: 15px;'></div>", unsafe_allow_html=True)
                
            st.write("---") 
            
            p_col1, p_col2, p_col3 = st.columns([1, 2, 1])
            with p_col1:
                if st.button("⬅️ 이전", use_container_width=True, disabled=(st.session_state.page_number == 1)):
                    st.session_state.page_number -= 1
                    st.rerun()
            with p_col2:
                st.markdown(f"<p style='text-align: center; line-height: 38px;'><b>{st.session_state.page_number} / {total_pages} 페이지</b></p>", unsafe_allow_html=True)
            with p_col3:
                if st.button("다음 ➡️", use_container_width=True, disabled=(st.session_state.page_number == total_pages)):
                    st.session_state.page_number += 1
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
            file_name=f"{keyword}_최신뉴스.csv",
            mime="text/csv",
            use_container_width=True
        )
else:
    st.info("검색어를 입력하거나 위의 추천 키워드를 눌러주세요.")