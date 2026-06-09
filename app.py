import streamlit as st
import requests
from bs4 import BeautifulSoup
import pandas as pd
import urllib.parse

# --- [1. 구글 RSS 뉴스 크롤링 함수] ---
def get_climate_news(keyword):
    encoded_keyword = urllib.parse.quote(keyword)
    url = f"https://news.google.com/rss/search?q={encoded_keyword}&hl=ko&gl=KR&ceid=KR:ko"
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
                news_list.append({"기사 제목": title, "기사 링크": link})
            return news_list
        return None
    except Exception as e:
        st.error(f"데이터 오류: {e}")
        return None

# --- [2. Streamlit 반응형 UI 설정] ---
st.set_page_config(page_title="실시간 뉴스 수집기", page_icon="🌱", layout="wide")

# 모바일 눈높이에 맞춘 깔끔한 타이틀
st.title("🌱 실시간 기후 뉴스")
st.caption("PC와 모바일 어디서든 최적화된 화면으로 뉴스를 확인하세요.")

# 입력창과 버튼을 일렬로 배치 (PC에서는 나란히, 모바일에서는 자동으로 위아래로 쪼개짐)
col1, col2 = st.columns([3, 1])
with col1:
    keyword_input = st.text_input("검색어 입력", value="기후변화", label_visibility="collapsed")
with col2:
    search_button = st.button("🔍 뉴스 검색", use_container_width=True)

st.write("---")

# 세션 상태를 이용해 검색 결과 기억하기
if "crawled_df" not in st.session_state:
    st.session_state.crawled_df = None
if "current_keyword" not in st.session_state:
    st.session_state.current_keyword = ""

# 검색 버튼 클릭 시 데이터 작동
if search_button or (keyword_input and keyword_input != st.session_state.current_keyword):
    with st.spinner('최신 뉴스를 가져오는 중...'):
        data = get_climate_news(keyword_input)
        if data:
            st.session_state.crawled_df = pd.DataFrame(data)
            st.session_state.current_keyword = keyword_input
        else:
            st.session_state.crawled_df = None
            st.error("뉴스 피드를 가져오지 못했습니다.")

# --- [3. 반응형 결과 뷰어 레이아웃] ---
if st.session_state.crawled_df is not None:
    df = st.session_state.crawled_df
    keyword = st.session_state.current_keyword
    
    st.success(f"✨ '{keyword}' 관련 뉴스 {len(df)}개")
    
    # 📱 모바일/PC 화면 효율을 위한 탭(Tab) 구성
    tab1, tab2 = st.tabs(["📰 뉴스 목록 보기", "📥 데이터 내보내기"])
    
    with tab1:
        # 💡 [반응형 핵심] 표 형식과 모바일용 카드 형식을 동시에 제공
        # 사용자가 모바일에서 편하게 볼 수 있도록 가독성이 높은 카드 형태(Markdown)로 먼저 뿌려줍니다.
        st.write("📌 **기사 제목을 누르면 해당 언론사로 이동합니다.**")
        
        # 구분선과 여백을 주어 손가락으로 터치하기 쉬운 '뉴스 피드' 형태로 출력
        for idx, row in df.iterrows():
            st.markdown(f"**{idx+1}. [{row['기사 제목']}]({row['기사 링크']})**")
            st.markdown("<div style='margin-bottom: 15px;'></div>", unsafe_allow_html=True) # 줄간격 확보
            
        st.write("---")
        # 데이터가 잘 나오는지 표로도 확인하고 싶은 PC 사용자를 위해 하단에 표 숨겨두기
        with st.expander("📊 원본 데이터 표 형태로 보기 (PC 추천)"):
            st.dataframe(df, use_container_width=True, hide_index=True)
            
    with tab2:
        st.write("📋 수집된 뉴스 리스트를 파일로 저장할 수 있습니다.")
        csv = df.to_csv(index=False).encode('utf-8-sig')
        st.download_button(
            label="📥 엑셀(CSV) 다운로드",
            data=csv,
            file_name=f"{keyword}_뉴스.csv",
            mime="text/csv",
            use_container_width=True # 모바일에서 누르기 좋게 왕버튼으로 변경
        )
else:
    st.info("검색어를 입력하고 검색 버튼을 눌러주세요.")