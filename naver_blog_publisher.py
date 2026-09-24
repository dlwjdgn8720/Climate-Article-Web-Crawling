"""
매일 자동 실행되어 오늘 수집된 기후 뉴스 다이제스트를 네이버 블로그에 발행하는 스크립트.
GitHub Actions 등 스케줄러에서 `python naver_blog_publisher.py`로 실행하는 것을 전제로 합니다.

필요한 환경변수:
  NAVER_CLIENT_ID, NAVER_CLIENT_SECRET, NAVER_REFRESH_TOKEN
  (최초 발급은 naver_oauth_setup.py 참고)

원문 기사 전문을 긁어오지 않고, 제목/링크/AI 신뢰도만 모아 다이제스트 형태로 발행합니다
(저작권 문제를 피하고 원 언론사로 트래픽을 보내기 위함).
"""
import os
from datetime import datetime, timedelta, timezone

import requests

from news_crawler import get_climate_news

NAVER_TOKEN_URL = "https://nid.naver.com/oauth2.0/token"
NAVER_WRITE_POST_URL = "https://openapi.naver.com/blog/writePost"

# 다이제스트를 구성할 때 모아볼 키워드들 (news_config.py의 추천 키워드와 동일한 풀)
DIGEST_KEYWORDS = ["기후변화", "탄소중립", "이상기온"]
MAX_ARTICLES = 10
KST = timezone(timedelta(hours=9))


def _get_access_token() -> str:
    """저장해둔 refresh_token으로 매 실행마다 새 access_token을 발급받습니다."""
    resp = requests.get(
        NAVER_TOKEN_URL,
        params={
            "grant_type": "refresh_token",
            "client_id": os.environ["NAVER_CLIENT_ID"],
            "client_secret": os.environ["NAVER_CLIENT_SECRET"],
            "refresh_token": os.environ["NAVER_REFRESH_TOKEN"],
        },
        timeout=10,
    )
    resp.raise_for_status()
    data = resp.json()
    if "access_token" not in data:
        raise RuntimeError(f"네이버 access_token 갱신 실패: {data}")
    return data["access_token"]


def build_digest():
    """여러 키워드로 검색한 결과를 중복 제거 후, 신뢰도/최신순 상위 N건으로 추립니다."""
    seen_links = set()
    collected = []

    for keyword in DIGEST_KEYWORDS:
        articles, _period = get_climate_news(keyword, "전체 보기")
        if not articles:
            continue
        for article in articles:
            link = article["기사 링크"]
            if link in seen_links:
                continue
            seen_links.add(link)
            collected.append(article)

    collected.sort(key=lambda a: (a["_confidence"], a["_raw_date"]), reverse=True)
    return collected[:MAX_ARTICLES]


def render_html(articles) -> str:
    today_str = datetime.now(KST).strftime("%Y년 %m월 %d일")
    lines = [
        f"<p>{today_str} 기준, AI가 선별한 기후 관련 뉴스 {len(articles)}건입니다.</p>",
        "<ol>",
    ]
    for a in articles:
        title = a["기사 제목"].replace("<", "&lt;").replace(">", "&gt;")
        lines.append(
            f'<li><a href="{a["기사 링크"]}" target="_blank" rel="noopener">{title}</a> '
            f'— {a["우선순위"]} · 신뢰도 {a["AI 신뢰도"]} · {a["작성일"]}</li>'
        )
    lines.append("</ol>")
    lines.append(
        "<p>※ 본 게시물은 구글 뉴스 RSS 수집과 AI 분류 모델을 이용해 자동 생성되었습니다. "
        "각 기사의 저작권은 원 언론사에 있습니다.</p>"
    )
    return "\n".join(lines)


def publish_to_naver(title: str, html_body: str):
    access_token = _get_access_token()
    resp = requests.post(
        NAVER_WRITE_POST_URL,
        headers={"Authorization": f"Bearer {access_token}"},
        data={"title": title, "contents": html_body},
        timeout=15,
    )
    resp.raise_for_status()
    result = resp.json()
    print("네이버 블로그 발행 결과:", result)
    return result


def main():
    articles = build_digest()
    if not articles:
        print("오늘 수집된 기후 뉴스가 없어 발행을 건너뜁니다.")
        return

    today_str = datetime.now(KST).strftime("%Y-%m-%d")
    title = f"[자동수집] {today_str} 기후 뉴스 다이제스트"
    html_body = render_html(articles)
    publish_to_naver(title, html_body)


if __name__ == "__main__":
    main()
