"""
피드백 수집 — 오분류된 기사를 사용자가 직접 레이블링하여 저장.
배포 환경(컨테이너 파일시스템이 재시작 시 초기화됨)에서도 데이터가 남도록
Supabase(REST API) 연동을 우선 사용하고, 연동이 설정되지 않았거나 실패하면
로컬 feedback_data.csv로 자동 폴백합니다.
"""
import os

import pandas as pd
import requests
import streamlit as st

FEEDBACK_FILE = "feedback_data.csv"
SUPABASE_TABLE = "feedback"


def get_supabase_config():
    """
    st.secrets에 supabase_url과 supabase_key가 설정되어 있으면 (url, key)를,
    설정이 없으면 None을 반환합니다. secrets.toml 자체가 없는 기본 로컬 실행에서도
    예외 없이 동작해야 하므로 st.secrets 접근 전체를 try로 감쌉니다.
    """
    try:
        secrets = st.secrets
        if "supabase_url" not in secrets or "supabase_key" not in secrets:
            return None  # 연동 설정을 아예 안 한 기본 상태 — 에러 아님
        return secrets["supabase_url"].rstrip("/"), secrets["supabase_key"]
    except st.errors.StreamlitSecretNotFoundError:
        return None  # secrets.toml 자체가 없는 기본 로컬 실행 — 에러 아님


def save_feedback(title: str, correct_label: int):
    """오분류 기사를 저장합니다. Supabase 연동이 있으면 테이블에, 없으면 로컬 CSV에 저장합니다."""
    config = get_supabase_config()
    if config is not None:
        url, key = config
        try:
            resp = requests.post(
                f"{url}/rest/v1/{SUPABASE_TABLE}",
                headers={
                    "apikey": key,
                    "Authorization": f"Bearer {key}",
                    "Content-Type": "application/json",
                },
                json={"title": title, "label": correct_label},
                timeout=10,
            )
            resp.raise_for_status()
            st.session_state.pop("feedback_store_error", None)
            return
        except Exception as e:
            st.session_state["feedback_store_error"] = str(e)
            # Supabase 저장 실패 시 아래 로컬 CSV 저장으로 폴백

    row = pd.DataFrame([{"title": title, "label": correct_label}])
    if os.path.exists(FEEDBACK_FILE):
        row.to_csv(FEEDBACK_FILE, mode="a", header=False, index=False, encoding="utf-8-sig")
    else:
        row.to_csv(FEEDBACK_FILE, mode="w", header=True, index=False, encoding="utf-8-sig")


def load_feedback_df():
    """Supabase 연동이 있으면 테이블에서, 없으면 로컬 CSV에서 피드백 데이터를 불러옵니다."""
    config = get_supabase_config()
    if config is not None:
        url, key = config
        try:
            resp = requests.get(
                f"{url}/rest/v1/{SUPABASE_TABLE}",
                headers={"apikey": key, "Authorization": f"Bearer {key}"},
                params={"select": "title,label"},
                timeout=10,
            )
            resp.raise_for_status()
            st.session_state.pop("feedback_store_error", None)
            records = resp.json()
            if records:
                return pd.DataFrame(records)
            return None
        except Exception as e:
            st.session_state["feedback_store_error"] = str(e)

    if os.path.exists(FEEDBACK_FILE):
        return pd.read_csv(FEEDBACK_FILE)
    return None
