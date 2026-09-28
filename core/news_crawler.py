"""구글 뉴스 RSS 크롤링 + AI 필터링."""
import email.utils
import urllib.parse
from datetime import datetime, timedelta, timezone

import requests
import streamlit as st
from bs4 import BeautifulSoup

from core.climate_model import predict_climate_news_batch
from core.news_config import (
    CATEGORY_MAP,
    CLIMATE_SUBQUERY,
    EXCLUDE_QUERY,
    MAJOR_MEDIA_DICT,
    PERSON_KEYWORDS,
    STRICT_EXCLUDE_TITLES,
)


WEEK_LIMIT = timedelta(days=7)
MAJOR_EXTENDED_LIMIT = timedelta(days=30)
MAJOR_EXTENDED_MAX = 5  # 1주일 내 주요 언론사 기사가 없을 때 확장 검색으로 보여줄 최대 건수


def _detect_major_media(title, link):
    """제목/링크에 주요 언론사 키워드가 포함되어 있으면 언론사명을, 없으면 None을 반환합니다."""
    lower_title = title.lower()
    lower_link = link.lower()
    for media_name, kws in MAJOR_MEDIA_DICT.items():
        if any(kw in lower_title or kw in lower_link for kw in kws):
            return media_name
    return None


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

        # 1차 필터링: 제목/날짜 기준으로 후보만 추려서 모델 추론 대상을 최소화.
        # 일반 기사는 1주일 이내만, 주요 언론사(⭐) 기사는 1주일 내 결과가 없을 때
        # 대비해 최대 30일까지 후보로 남겨둔다(최종 채택 여부는 분류 이후 결정).
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

            age = now - parsed_date
            media_name = _detect_major_media(title, link)

            if age > MAJOR_EXTENDED_LIMIT:
                continue
            if media_name is None and age > WEEK_LIMIT:
                continue

            candidates.append({
                "title": title, "link": link, "parsed_date": parsed_date, "media_name": media_name,
            })

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
            media_name = candidate["media_name"]

            data_row = {
                "기사 제목": title,
                "기사 링크": link,
                "작성일":     parsed_date.strftime("%Y-%m-%d %H:%M"),
                "_raw_date": parsed_date,
                "우선순위":  f"⭐ {media_name}" if media_name else "일반 기사",
                "AI 신뢰도": f"{confidence:.0%}",
                "_confidence": confidence,
            }

            (major_news_list if media_name else general_news_list).append(data_row)

        # 일반 기사는 이미 1주일 이내로만 후보를 구성했으므로 그대로 사용.
        # 주요 언론사는 1주일 이내 기사가 있으면 그것만, 없으면 30일 범위에서 최대
        # MAJOR_EXTENDED_MAX건까지 확장해서 보여준다.
        major_news_list.sort(key=lambda x: x["_raw_date"], reverse=True)
        general_news_list.sort(key=lambda x: x["_raw_date"], reverse=True)

        major_within_week = [row for row in major_news_list if now - row["_raw_date"] <= WEEK_LIMIT]
        used_extended_major = bool(major_news_list) and not major_within_week
        final_major = major_within_week if major_within_week else major_news_list[:MAJOR_EXTENDED_MAX]

        final_news = final_major + general_news_list
        final_news.sort(key=lambda x: x["_raw_date"], reverse=True)

        if final_news:
            period_label = "1주일 (주요 언론사는 최근 기사가 없어 최대 30일로 확장)" if used_extended_major else "1주일"
            return final_news, period_label, None

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
