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
        st.error(f"데이터를 가져오는 중 오류가 발생했습니다: {e}")
        return None

# --- [2. Streamlit 모바일/웹 UI 구성] ---

# 페이지 설정 (스마트폰 해상도에 맞게 와이드 모드 적용)
st.set_page_config(page_title="실시간 뉴스 수집기", page_icon="🌱", layout="wide")

st.title("🌱 실시간 기후 뉴스 수집기")
st.markdown("모바일과 PC 어디서나 키워드를 입력해 최신 환경 뉴스를 확인해 보세요.")

# 검색창과 버튼 배치 (모바일 가독성을 위해 한 줄씩 깔끔하게 배치)
keyword_input = st.text_input("검색할 키워드를 입력하세요", value="기후변화")
search_button = st.button("🔍 뉴스 검색하기", use_container_width=True) # 버튼을 화면에 꽉 차게 설정 (모바일 터치용)

# --- [3. 버튼 클릭 시 작동 로직] ---
if search_button:
    with st.spinner('실시간 뉴스 피드를 읽어오는 중...'):
        data = get_climate_news(keyword_input)
        
    if data:
        df = pd.DataFrame(data)
        
        st.success(f"✨ '{keyword_input}' 관련 최신 뉴스 {len(df)}개를 찾았습니다!")
        
        # 모바일에서도 링크를 터치해 바로 이동할 수 있도록 표 설정
        st.dataframe(
            df, 
            column_config={
                "기사 링크": st.column_config.LinkColumn("기사 이동 링크")
            },
            use_container_width=True,
            hide_index=True
        )
        
        # 엑셀 다운로드 버튼 (핸드폰에서도 CSV 다운로드 가능)
        csv = df.to_csv(index=False).encode('utf-8-sig')
        st.download_button(
            label="📥 수집된 뉴스 엑셀(CSV) 다운로드",
            data=csv,
            file_name=f"{keyword_input}_뉴스_리스트.csv",
            mime="text/csv",
            use_container_width=True
        )
    else:
        st.info(f"'{keyword_input}' 관련 최신 뉴스가 없거나 가져오지 못했습니다.")