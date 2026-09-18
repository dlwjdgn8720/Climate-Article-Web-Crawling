"""구글 뉴스 RSS 크롤링 + AI 필터링."""
import email.utils
import urllib.parse
from datetime import datetime, timedelta, timezone

import requests
import streamlit as st
from bs4 import BeautifulSoup

from climate_model import predict_climate_news_batch
from news_config import (
    CATEGORY_MAP,
    CLIMATE_SUBQUERY,
    EXCLUDE_QUERY,
    MAJOR_MEDIA_DICT,
    PERSON_KEYWORDS,
    STRICT_EXCLUDE_TITLES,
)


@st.cache_data(ttl=600, show_spinner=False)
def _fetch_climate_news_cached(keyword, category):
    """
    실제 크롤링+필터링 로직. 같은 (키워드, 카테고리) 조합은 10분간 캐시되어
    재검색 시 네트워크 요청과 AI 추론을 다시 하지 않고 즉시 결과를 반환합니다.
    리턴값: (final_news, period_label, error_message)
    """
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        )
    }

    is_person_keyword = any(p in keyword for p in PERSON_KEYWORDS)
    category_query = CATEGORY_MAP.get(category, "")

    if is_person_keyword:
        if category_query:
            query_text = f'"{keyword}" {CLIMATE_SUBQUERY} {category_query} {EXCLUDE_QUERY}'
        else:
            query_text = f'"{keyword}" {CLIMATE_SUBQUERY} {EXCLUDE_QUERY}'
    elif category_query:
        query_text = f'"{keyword}" {category_query} {EXCLUDE_QUERY}'
    else:
        query_text = f'"{keyword}" {EXCLUDE_QUERY}'

    encoded_query = urllib.parse.quote(query_text)
    url = f"https://news.google.com/rss/search?q={encoded_query}&hl=ko&gl=KR&ceid=KR:ko"

    try:
        response = requests.get(url, headers=headers, timeout=10)
        if response.status_code != 200:
            return None, None, f"구글 뉴스 응답 오류 (HTTP {response.status_code})"

        soup = BeautifulSoup(response.text, "lxml-xml")
        items = soup.find_all("item")
        if not items:
            return None, None, None

        now = datetime.now(timezone.utc)

        # 1차 필터링: 제목/날짜 기준으로 후보만 추려서 모델 추론 대상을 최소화
        candidates = []
        for item in items:
            title = item.title.get_text()
            link  = item.link.get_text()
            pub_date_str = item.pubDate.get_text() if item.pubDate else ""

            if any(bad in title for bad in STRICT_EXCLUDE_TITLES):
                continue

            try:
                parsed_date = email.utils.parsedate_to_datetime(pub_date_str)
                if parsed_date.tzinfo is None:
                    parsed_date = parsed_date.replace(tzinfo=timezone.utc)
            except Exception:
                continue

            if now - parsed_date > timedelta(days=30):
                continue

            candidates.append({"title": title, "link": link, "parsed_date": parsed_date})

        if not candidates:
            return None, None, None

        # 기사 하나씩 순차 추론하지 않고, 후보 제목 전체를 한 번에 배치 추론
        predictions = predict_climate_news_batch([c["title"] for c in candidates])

        major_news_list = []
        general_news_list = []

        for candidate, (is_climate, confidence) in zip(candidates, predictions):
            if is_climate == 0:
                continue

            title = candidate["title"]
            link = candidate["link"]
            parsed_date = candidate["parsed_date"]

            data_row = {
                "기사 제목": title,
                "기사 링크": link,
                "작성일":     parsed_date.strftime("%Y-%m-%d %H:%M"),
                "_raw_date": parsed_date,
                "우선순위":  "일반 기사",
                "AI 신뢰도": f"{confidence:.0%}",
                "_confidence": confidence,
            }

            is_major = False
            lower_title = title.lower()
            lower_link  = link.lower()
            for media_name, kws in MAJOR_MEDIA_DICT.items():
                if any(kw in lower_title or kw in lower_link for kw in kws):
                    is_major = True
                    data_row["우선순위"] = f"⭐ {media_name}"
                    break

            (major_news_list if is_major else general_news_list).append(data_row)

        sorted_major   = sorted(major_news_list,   key=lambda x: x["_raw_date"], reverse=True)
        sorted_general = sorted(general_news_list, key=lambda x: x["_raw_date"], reverse=True)
        final_news = sorted_major + sorted_general

        if final_news:
            has_week = any((now - x["_raw_date"]) <= timedelta(days=7) for x in final_news)
            return final_news, ("1주일" if has_week else "한 달"), None

    except Exception as e:
        print(f"크롤링 에러 추적: {str(e)}")
        return None, None, str(e)

    return None, None, None


def get_climate_news(keyword, category):
    """캐시된 크롤링 결과를 가져오면서, 오류가 있으면 session_state에 기록합니다."""
    final_news, period, error_message = _fetch_climate_news_cached(keyword, category)
    if error_message:
        st.session_state["crawl_error"] = error_message
    else:
        st.session_state.pop("crawl_error", None)
    return final_news, period
