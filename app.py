"""Streamlit UI — 기후 뉴스 수집 시스템."""
import re

import pandas as pd
import streamlit as st

import climate_model
from feedback_store import get_supabase_config, load_feedback_df, save_feedback
from news_config import CATEGORIES, PERSON_KEYWORDS
from news_crawler import get_climate_news

# ─────────────────────────────────────────────────────────────────
# [UI 블록]
# ─────────────────────────────────────────────────────────────────
st.set_page_config(page_title="기후 뉴스 수집기", page_icon="🌱", layout="wide")

for key, default in [
    ("news_df", None), ("p_num", 1), ("period_info", ""),
    ("current_keyword", ""), ("current_category", "전체 보기"),
    ("input_key_setter", ""), ("show_feedback", False),
]:
    if key not in st.session_state:
        st.session_state[key] = default

st.markdown("""
<style>
    .main-title  { font-size:28px; font-weight:700; color:#1e4620; margin-bottom:5px; }
    .sub-title   { font-size:14px; color:#555; margin-bottom:25px; }
    .news-date   { font-size:12px; color:#888; margin-top:2px; }
    .keyword-label { font-size:14px; font-weight:600; color:#444; margin-bottom:8px; }
    .badge-major   { background:#e8f5e9; color:#2e7d32; padding:2px 6px;
                     border-radius:4px; font-size:11px; font-weight:bold; }
    .badge-general { background:#f5f5f5; color:#666; padding:2px 6px;
                     border-radius:4px; font-size:11px; }
    .badge-conf    { background:#fff3e0; color:#e65100; padding:2px 6px;
                     border-radius:4px; font-size:11px; }
    div.stButton > button { white-space:nowrap !important; min-width:max-content !important; }
</style>
""", unsafe_allow_html=True)

# 모델 상태 배너
if climate_model.tokenizer is None:
    error_detail = st.session_state.get("model_load_error")
    st.warning(
        "⚠️ 학습된 AI 모델이 로드되지 않아 단순 키워드 매칭 폴백 모드로 구동 중입니다."
        + (f" (오류: {error_detail})" if error_detail else "")
    )
else:
    source_label = "로컬 재학습 모델" if climate_model.MODEL_SOURCE == climate_model.LOCAL_MODEL_DIR else "허브 모델"
    st.success(
        f"✅ AI 모델 활성화 중 ({source_label}) — "
        f"신뢰도 임계값 {climate_model.CLIMATE_THRESHOLD:.1%} 이상만 통과"
    )

st.markdown("""
    <div class="main-title">🌱 기후관련 뉴스 수집 시스템</div>
    <div class="sub-title">구글 RSS 뉴스를 실시간 수집하고 AI 가드레일 모델을 통해 관련성을 검증합니다.</div>
""", unsafe_allow_html=True)

# 추천 키워드
recommended_keywords = ["기후변화", "탄소중립", "신재생에너지", "CCUS", "이상기온", "ESG", "에너지"]
st.markdown("<div class='keyword-label'>추천 키워드 검색</div>", unsafe_allow_html=True)

trigger_keyword = None
kw_cols = st.columns(len(recommended_keywords))
for i, kw in enumerate(recommended_keywords):
    with kw_cols[i]:
        if st.button(f"#{kw}", width="stretch", key=f"btn_{kw}"):
            trigger_keyword = kw

st.write(" ")

with st.form("search_form", clear_on_submit=False):
    col_cat, col_inp, col_btn = st.columns([1.2, 2.5, 0.8])
    with col_cat:
        selected_cat = st.selectbox("카테고리 선택", CATEGORIES, label_visibility="collapsed")
    with col_inp:
        keyword_input = st.text_input(
            "검색어 입력창",
            value=st.session_state.input_key_setter,
            placeholder="검색어를 입력하거나 위 추천 태그를 클릭하세요.",
            label_visibility="collapsed",
        )
    with col_btn:
        search_button = st.form_submit_button("뉴스 검색", width="stretch")

# 검색 트리거 — 추천 태그 클릭 또는 폼 제출(버튼/Enter)일 때만 실행되고,
# 글자를 입력하는 도중에는(=폼 제출 전) 재검색이 일어나지 않습니다.
run_search = False
search_target_keyword = ""

if trigger_keyword:
    run_search = True
    search_target_keyword = trigger_keyword
    st.session_state.input_key_setter = ""
elif search_button and keyword_input.strip():
    run_search = True
    search_target_keyword = keyword_input.strip()
    st.session_state.input_key_setter = keyword_input.strip()

if run_search and search_target_keyword:
    with st.spinner(f"'{search_target_keyword}' 결과 가공 중..."):
        st.session_state.news_df = None
        st.session_state.is_person_search = any(
            p in search_target_keyword for p in PERSON_KEYWORDS
        )
        res, period = get_climate_news(search_target_keyword, selected_cat)
        if res:
            st.session_state.news_df       = pd.DataFrame(res)
            st.session_state.period_info   = period
            st.session_state.current_keyword  = search_target_keyword
            st.session_state.current_category = selected_cat
            st.session_state.p_num         = 1
            st.session_state.pop("search_failed", None)
        else:
            st.session_state.news_df          = None
            st.session_state.current_keyword  = search_target_keyword
            st.session_state.current_category = selected_cat
            st.session_state.search_failed    = True
        st.rerun()

st.write("---")

# ─────────────────────────────────────────────────────────────────
# [결과 렌더링]
# ─────────────────────────────────────────────────────────────────
if st.session_state.news_df is not None:
    df          = st.session_state.news_df
    current_kw  = st.session_state.current_keyword
    current_cat = st.session_state.current_category
    period_text = st.session_state.period_info

    st.success(
        f"'{current_kw}' [{current_cat}] → "
        f"AI 필터링 통과 (최근 {period_text} 이내 총 {len(df)}건)"
    )

    if st.session_state.get("is_person_search", False):
        st.info(
            "👤 **인물 키워드 감지** — RSS 쿼리 단계부터 기후 관련 기사만 수집하도록 자동 필터가 적용되었습니다. "
            "기후 무관 기사(정치·외교·경제 등)는 검색 결과에서 제외됩니다."
        )

    tab1, tab2, tab3 = st.tabs(["뉴스 목록 보기", "데이터 내보내기", "🔁 오분류 피드백"])

    with tab1:
        st.write("📌 기사 제목을 누르면 해당 뉴스 원문 페이지로 이동합니다.")
        view_mode = st.radio(
            "보기 모드 선택",
            ["모바일 피드 (전체 스크롤)", "PC 정돈 모드 (10개씩 보기)"],
            horizontal=True,
            key="view_mode_select",
        )
        st.write("---")

        def render_row(idx, row):
            badge_class = "badge-major" if "⭐" in row["우선순위"] else "badge-general"
            # 마크다운 링크 구문이 제목 속 대괄호로 깨지지 않도록 이스케이프하고,
            # http(s)가 아닌 스킴(예: javascript:)의 링크는 무효화합니다.
            safe_title = row["기사 제목"].replace("[", "\\[").replace("]", "\\]")
            link = row["기사 링크"]
            safe_link = link if re.match(r"^https?://", link, re.IGNORECASE) else "#"
            st.markdown(f"**{idx+1}. [{safe_title}]({safe_link})**")
            st.markdown(
                f"<span class='{badge_class}'>{row['우선순위']}</span> &nbsp; "
                f"<span class='badge-conf'>🤖 {row['AI 신뢰도']}</span> &nbsp;&nbsp; "
                f"<span class='news-date'>⏱ {row['작성일']}</span>",
                unsafe_allow_html=True,
            )
            st.markdown("<div style='margin-bottom:18px; border-bottom:1px dashed #eee;'></div>",
                        unsafe_allow_html=True)

        if view_mode == "모바일 피드 (전체 스크롤)":
            for idx, row in df.iterrows():
                render_row(idx, row)
        else:
            items_per_page = 10
            total_pages    = max(1, (len(df) - 1) // items_per_page + 1)
            st.session_state.p_num = min(st.session_state.p_num, total_pages)
            start_idx = (st.session_state.p_num - 1) * items_per_page
            page_df   = df.iloc[start_idx : start_idx + items_per_page]

            for idx, row in page_df.iterrows():
                render_row(idx, row)

            st.write("---")
            p1, p2, p3 = st.columns([1, 2, 1])
            with p1:
                if st.button("⬅️ 이전", width="stretch",
                             disabled=(st.session_state.p_num == 1), key="btn_prev"):
                    st.session_state.p_num -= 1
                    st.rerun()
            with p2:
                st.markdown(
                    f"<p style='text-align:center;line-height:38px;'>"
                    f"<b>{st.session_state.p_num} / {total_pages} 페이지</b></p>",
                    unsafe_allow_html=True,
                )
            with p3:
                if st.button("다음 ➡️", width="stretch",
                             disabled=(st.session_state.p_num == total_pages), key="btn_next"):
                    st.session_state.p_num += 1
                    st.rerun()

        st.write("---")
        with st.expander("원본 데이터 표 형태로 보기"):
            display_cols = [c for c in df.columns if not c.startswith("_")]
            st.dataframe(df[display_cols], width="stretch", hide_index=True)

    with tab2:
        st.write("📋 추출용 깨끗한 데이터셋을 파일로 저장할 수 있습니다.")
        display_cols = [c for c in df.columns if not c.startswith("_")]
        csv = df[display_cols].to_csv(index=False).encode("utf-8-sig")
        st.download_button(
            label="📥 엑셀(CSV) 다운로드",
            data=csv,
            file_name=f"Verified_{current_kw}_{current_cat}_뉴스데이터.csv",
            mime="text/csv",
            width="stretch",
            key="btn_download",
        )

    with tab3:
        st.write(
            "🔁 AI가 잘못 분류한 기사를 레이블링하면 저장됩니다.  \n"
            "나중에 `train_data_augmented.csv`와 합쳐 재학습하면 정확도가 올라갑니다."
        )

        feedback_title = st.text_input(
            "오분류된 기사 제목 붙여넣기",
            placeholder="예) 코스피, 탄소배출권 관련주 강세로 소폭 상승 마감",
            key="fb_title",
        )
        feedback_label = st.radio(
            "올바른 레이블",
            ["1 — 기후 관련 기사 (AI가 제외했는데 포함시켜야 함)",
             "0 — 비기후 기사 (AI가 통과시켰는데 제외해야 함)"],
            key="fb_label",
        )
        if st.button("💾 피드백 저장", key="btn_feedback"):
            if feedback_title.strip():
                correct_label = int(feedback_label[0])
                save_feedback(feedback_title.strip(), correct_label)
                st.success("✅ 피드백이 저장되었습니다!")
            else:
                st.warning("기사 제목을 입력해주세요.")

        if get_supabase_config() is not None and not st.session_state.get("feedback_store_error"):
            st.caption("💾 저장 위치: Supabase (배포 환경에서도 유지됩니다)")
        elif st.session_state.get("feedback_store_error"):
            st.caption(
                f"⚠️ Supabase 연동 실패로 로컬 CSV에 대신 저장 중입니다. "
                f"(오류: {st.session_state['feedback_store_error']})"
            )
        else:
            st.caption("💾 저장 위치: 로컬 feedback_data.csv (배포 환경에서는 재시작 시 초기화될 수 있습니다)")

        fb_df = load_feedback_df()
        if fb_df is not None and not fb_df.empty:
            st.info(f"현재까지 누적 피드백: {len(fb_df)}건")
            with st.expander("피드백 데이터 확인"):
                st.dataframe(fb_df, width="stretch", hide_index=True)
            st.download_button(
                label="📥 피드백 데이터 다운로드 (재학습용)",
                data=fb_df.to_csv(index=False).encode("utf-8-sig"),
                file_name="feedback_data.csv",
                mime="text/csv",
                key="btn_fb_download",
            )

else:
    if st.session_state.get("search_failed", False):
        crawl_error = st.session_state.get("crawl_error")
        if crawl_error:
            st.error(
                f"'{st.session_state.current_keyword}' 검색 중 오류가 발생했습니다: {crawl_error}"
            )
        else:
            st.error(
                f"'{st.session_state.current_keyword}' 관련 뉴스가 없거나 "
                "AI가 노이즈로 판단해 모두 제외했습니다."
            )
    else:
        st.info("검색어를 입력하거나 추천 태그를 클릭해 조사를 시작하세요.")
