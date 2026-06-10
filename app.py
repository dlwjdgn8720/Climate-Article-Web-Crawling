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
    
    # 지능형 쿼리 분기 알고리즘 (인물/기업 자동 감지)
    eco_words = ["기후", "환경", "탄소", "에너지", "온난화", "그린", "배출권", "재생", "CCUS", "발전", "오염", "생태"]
    is_pure_eco_keyword = any(word in keyword for word in eco_words)
    
    if is_pure_eco_keyword:
        tech_filter = "(기후 OR 환경 OR 탄소 OR 에너지 OR 기술)"
    else:
        tech_filter = "(기후 OR 환경 OR 탄소 OR '그린 테크' OR '친환경 에너지' OR AI OR 기술 OR '시뮬레이터')"
        
    essential_words = eco_words + ["earth-2", "fourcastnet", "기상", "시뮬레이터", "친환경", "인공지능", "AI", "테크", "녹색"]

    # 1주 -> 2주 -> 3주 순으로 기간을 늘려가며 수집
    for weeks in [1, 2, 3]:
        query = f"{keyword} {tech_filter} when:{weeks}w"
        encoded_query = urllib.parse.quote(query)
        url = f"https://news.google.com/rss/search?q={encoded_query}&hl=ko&gl=KR&ceid=KR:ko"
        
        try:
            response = requests.get(url, headers=headers)
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
                
                # 제목 검증 및 필터링
                has_essential_word = any(word.lower() in title.lower() for word in essential_words)
                is_keyword_included = keyword.lower() in title.lower()
                
                if not (has_essential_word or is_keyword_included):
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
                    st.toast(f"💡 최근 1주일 내 뉴스가 없어 {weeks}주일 전 데이터까지 확장 수집했습니다!", icon="ℹ️")
                return news_list
                
        except Exception as e:
            continue
            
    return None

# --- [2. Streamlit UI 및 세션 상태 초기화] ---
st.set_page_config(page_title="실시간 뉴스 수집기", page_icon="🌱", layout="wide")

# 세션 상태 변수 통합 관리 (꼬임 방지)
if "search_keyword" not in st.session_state: st.session_state.search_keyword = "기후변화"
if "crawled_df" not in st.session_state: st.session_state.crawled_df = None
if "page_number" not in st.session_state: st.session_state.page_number = 1
if "do_search" not in st.session_state: st.session_state.do_search = False

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

kw_cols = st.columns(len(recommended_keywords))
for i, kw in enumerate(recommended_keywords):
    with kw_cols[i]:
        # 추천 키워드를 누르면 즉시 세션 값을 바꾸고 무조건 검색을 실행하도록 신호를 줍니다.
        if st.button(f"#{kw}", use_container_width=True):
            st.session_state.search_keyword = kw
            st.session_state.do_search = True
            st.rerun()

st.write(" ") 

# 입력창과 검색 버튼 배치
col1, col2 = st.columns([3, 1])
with col1:
    # key 설정을 통해 세션 상태인 st.session_state.search_keyword와 입력창의 값을 강제로 일치시킵니다.
    keyword_input = st.text_input("검색어 입력", key="search_keyword", label_visibility="collapsed")
with col2:
    search_button = st.button("🔍 뉴스 검색", use_container_width=True)

# 텍스트 입력창에서 엔터를 치거나 일반 검색 버튼을 누른 경우 검색 신호 작동
if search_button or (keyword_input and st.session_state.get("last_searched", "") != keyword_input):
    st.session_state.do_search = True

st.write("---")

# --- [3. 크롤링 실행 트리거 제어] ---
if st.session_state.do_search:
    # 실행 신호가 켜지면 꼬임 없이 현재 입력창에 있는 단어로 크롤링 시작
    current_target = st.session_state.search_keyword
    
    with st.spinner(f"'{current_target}' 최신 뉴스를 가져오는 중..."):
        data = get_climate_news(current_target)
        if data:
            st.session_state.crawled_df = pd.DataFrame(data)
            st.session_state.page_number = 1  # 검색 시 페이지 초기화
            st.session_state.last_searched = current_target  # 무한 루프 방지용 기록
        else:
            st.session_state.crawled_df = None
            st.error(f"최근 3주일간 '{current_target}' 관련 뉴스 피드가 없거나 가져오지 못했습니다.")
            
    # 검색이 완료되었으므로 신호등을 다시 꺼줍니다.
    st.session_state.do_search = False

# --- [4. 결과 레이아웃 화면 출력] ---
if st.session_state.crawled_df is not None:
    df = st.session_state.crawled_df
    current_keyword = st.session_state.get("last_searched", "기후변화")
    
    st.success(f"✨ '{current_keyword}' 관련 최신 뉴스 {len(df)}개")
    
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
            file_name=f"{current_keyword}_최신뉴스.csv",
            mime="text/csv",
            use_container_width=True
        )
else:
    st.info("검색어를 입력하거나 위의 추천 키워드를 눌러주세요.")