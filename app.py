import streamlit as st
import requests
from bs4 import BeautifulSoup
import pandas as pd
import urllib.parse
from datetime import datetime

# --- [1. 구글 RSS 뉴스 크롤링 함수 (인물/기업 자동 감지 및 글로벌 범용 필터)] ---
def get_climate_news(keyword):
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }
    
    # 1. 시스템이 인지할 순수 기후/환경/에너지 핵심 단어 정의
    eco_words = ["기후", "환경", "탄소", "에너지", "온난화", "그린", "배출권", "재생", "CCUS", "발전", "오염", "생태"]
    
    # 2. [지능형 쿼리 분기 알고리즘]
    # 검색어에 순수 환경 단어가 포함되어 있는지 확인합니다.
    is_pure_eco_keyword = any(word in keyword for word in eco_words)
    
    if is_pure_eco_keyword:
        # 사용자가 '탄소중립', 'CCUS' 같은 순수 환경 용어를 쳤다면 해당 도메인을 더 심도 있게 묶어줍니다.
        tech_filter = "(기후 OR 환경 OR 탄소 OR 에너지 OR 기술)"
    else:
        # 💡 [핵심] 사용자가 '젠슨 황', '일론 머스크', '구글', '샘 알트만' 등 
        # 환경 단어가 아닌 인물/기업을 검색했다면, 기후 테크 및 미래 청정에너지 맥락을 대폭 결합합니다.
        tech_filter = "(기후 OR 환경 OR 탄소 OR '그린 테크' OR '친환경 에너지' OR AI OR 기술 OR '시뮬레이터')"
        
    # 2차 대책: 파이썬 코드단에서 제목을 재검증할 '필수 단어 세트' (영문 표기 포함)
    essential_words = eco_words + ["earth-2", "fourcastnet", "기상", "시뮬레이터", "친환경", "인공지능", "AI", "테크", "녹색"]

    # ⏱️ 1주 -> 2주 -> 3주 순으로 기간을 늘려가며 반복 검색
    for weeks in [1, 2, 3]:
        # 어떤 검색어가 들어오든 인물이면 기술/환경 필터가, 환경 용어면 환경 필터가 유기적으로 조합됩니다.
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
                
                # [2차 필터링] 제목 검증
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

# 💡 [세션 상태 관리]
if "search_keyword" not in st.session_state: st.session_state.search_keyword = "기후변화"
if "crawled_df" not in st.session_state: st.session_state.crawled_df = None
if "current_keyword" not in st.session_state: st.session_state.current_keyword = ""
if "page_number" not in st.session_state: st.session_state.page_number = 1
# 💡 추천 키워드 버튼 클릭 여부를 감지하기 위한 트리거 변수 추가
if "trigger_by_button" not in st.session_state: st.session_state.trigger_by_button = False

# 추천 키워드 학습/설정 파트
recommended_keywords = ["기후변화", "탄소중립", "신재생에너지", "CCUS", "지구온난화"]

st.markdown("<div class='keyword-label'>🔥 추천 키워드 바로 검색</div>", unsafe_allow_html=True)

# 추천 키워드 버튼 배치
kw_cols = st.columns(len(recommended_keywords))
for i, kw in enumerate(recommended_keywords):
    with kw_cols[i]:
        # 💡 [수정] 버튼을 누르면 검색어를 세션에 넣고, '버튼으로 트리거됨'을 True로 만든 뒤 강제 새로고침합니다.
        if st.button(f"#{kw}", use_container_width=True):
            st.session_state.search_keyword = kw
            st.session_state.trigger_by_button = True
            st.rerun()

st.write(" ") 

# 입력창과 버튼 배치
col1, col2 = st.columns([3, 1])
with col1:
    keyword_input = st.text_input("검색어 입력", value=st.session_state.search_keyword, label_visibility="collapsed")
with col2:
    search_button = st.button("🔍 뉴스 검색", use_container_width=True)

st.write("---")

# 💡 [수정된 로직]: 
# 1. 오른쪽 '뉴스 검색' 버튼을 눌렀을 때
# 2. 입력창에서 엔터를 쳐서 입력창 내부 값이 기존 검색어와 달라졌을 때
# 3. 혹은 상단 추천 키워드 해시태그 버튼을 클릭해서 trigger_by_button이 True가 되었을 때
is_text_entered = (keyword_input and keyword_input != st.session_state.current_keyword)
trigger_search = search_button or is_text_entered or st.session_state.trigger_by_button

if trigger_search:
    # 어떤 경로로 들어왔든 최종 검색 타겟은 keyword_input(화면에 채워진 단어)으로 통일합니다.
    target_word = keyword_input
    
    with st.spinner(f"'{target_word}' 최신 뉴스를 가져오는 중..."):
        data = get_climate_news(target_word)
        if data:
            st.session_state.crawled_df = pd.DataFrame(data)
            st.session_state.current_keyword = target_word
            st.session_state.search_keyword = target_word
            st.session_state.page_number = 1
        else:
            st.session_state.crawled_df = None
            st.error(f"최근 1주일간의 '{target_word}' 뉴스 피드를 가져오지 못했습니다.")
            
    # 💡 크롤링이 한 번 완료되면 버튼 트리거 상태를 다시 원래대로(False) 꺼줍니다.
    st.session_state.trigger_by_button = False

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