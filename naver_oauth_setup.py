"""
네이버 블로그 자동 포스팅을 위한 최초 1회 OAuth 인증 스크립트.
로컬 PC에서 딱 한 번만 실행해서 refresh_token을 발급받는 용도입니다.
(발급받은 refresh_token은 GitHub Actions Secrets에 등록해두고, 이후엔 이 스크립트를 다시 실행할 필요 없습니다.)

사전 준비:
  1. https://developers.naver.com 에서 애플리케이션 등록 → 사용 API에 "네이버 아이디로 로그인" 추가
  2. 서비스 URL: http://127.0.0.1 , 콜백 URL: http://127.0.0.1:8080/callback 로 등록
     (네이버는 "localhost"라는 이름을 URL로 허용하지 않고 127.0.0.1 형식만 받습니다)
  3. "로그인 오픈 API 서비스 환경" 심사 신청 → 승인 대기 (약 3일)
  4. 발급받은 Client ID / Secret으로 아래 환경변수를 설정한 뒤 실행:
       (PowerShell)
       $env:NAVER_CLIENT_ID="..."
       $env:NAVER_CLIENT_SECRET="..."
       python naver_oauth_setup.py
"""
import os
import urllib.parse
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer

import requests

REDIRECT_URI = "http://127.0.0.1:8080/callback"
STATE = "climate_news_setup"

_result = {}


class _CallbackHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        query = urllib.parse.urlparse(self.path).query
        params = urllib.parse.parse_qs(query)
        _result["code"] = params.get("code", [None])[0]
        self.send_response(200)
        self.send_header("Content-type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write("인증 완료! 이 창은 닫으셔도 됩니다.".encode("utf-8"))

    def log_message(self, format, *args):
        pass  # 기본 접근 로그 출력 억제


def main():
    client_id = os.environ.get("NAVER_CLIENT_ID")
    client_secret = os.environ.get("NAVER_CLIENT_SECRET")
    if not client_id or not client_secret:
        print("먼저 NAVER_CLIENT_ID / NAVER_CLIENT_SECRET 환경변수를 설정해주세요.")
        return

    auth_url = "https://nid.naver.com/oauth2.0/authorize?" + urllib.parse.urlencode(
        {
            "response_type": "code",
            "client_id": client_id,
            "redirect_uri": REDIRECT_URI,
            "state": STATE,
        }
    )
    print("브라우저에서 네이버 로그인 창을 엽니다. 로그인 후 이 창으로 자동으로 돌아옵니다...")
    webbrowser.open(auth_url)

    server = HTTPServer(("127.0.0.1", 8080), _CallbackHandler)
    server.handle_request()  # 콜백 1건만 받고 서버 종료

    code = _result.get("code")
    if not code:
        print("인증 코드를 받지 못했습니다. 콜백 URL 설정을 다시 확인해주세요.")
        return

    resp = requests.get(
        "https://nid.naver.com/oauth2.0/token",
        params={
            "grant_type": "authorization_code",
            "client_id": client_id,
            "client_secret": client_secret,
            "code": code,
            "state": STATE,
        },
        timeout=10,
    )
    data = resp.json()
    if "refresh_token" not in data:
        print("토큰 발급 실패:", data)
        return

    print("\n발급 성공! 아래 각 줄의 '=' 뒤에 있는 값만(공백 없이) 복사해서")
    print("GitHub 저장소 Settings > Secrets and variables > Actions에 등록하세요.")
    print("(주의: 'NAVER_CLIENT_ID = ' 같은 이름/등호 부분까지 같이 복사하면 인증이 실패합니다)\n")
    print("[NAVER_CLIENT_ID]")
    print(client_id)
    print("\n[NAVER_CLIENT_SECRET]")
    print(client_secret)
    print("\n[NAVER_REFRESH_TOKEN]")
    print(data["refresh_token"])


if __name__ == "__main__":
    main()
