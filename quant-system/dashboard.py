"""
퀀트 투자 운용 법인 - 통합 대시보드
Streamlit 기반 실시간 모니터링 및 제어 인터페이스
"""

import json
import logging
import os
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

# 경로 설정
sys.path.insert(0, str(Path(__file__).parent))

from config_loader import load_config
from database import QuantDatabase
from DQNChief import DQNChief, ACTIONS, N_ACTIONS, build_state, compute_reward
import KakaoAuth

# ── 코스피 30종목 종목코드 → 회사명 매핑 ─────────────────────
STOCK_NAMES: dict[str, str] = {
    "005930": "삼성전자",
    "000660": "SK하이닉스",
    "373220": "LG에너지솔루션",
    "207940": "삼성바이오로직스",
    "005380": "현대차",
    "000270": "기아",
    "005490": "POSCO홀딩스",
    "051910": "LG화학",
    "006400": "삼성SDI",
    "068270": "셀트리온",
    "035720": "카카오",
    "035420": "NAVER",
    "105560": "KB금융",
    "055550": "신한지주",
    "086790": "하나금융지주",
    "316140": "우리금융지주",
    "017670": "SK텔레콤",
    "030200": "KT",
    "066570": "LG전자",
    "012450": "한화에어로스페이스",
    "034020": "두산에너빌리티",
    "033780": "KT&G",
    "015760": "한국전력",
    "010130": "고려아연",
    "028260": "삼성물산",
    "012330": "현대모비스",
    "034730": "SK",
    "003550": "LG",
    "090430": "아모레퍼시픽",
    "259960": "크래프톤",
}

def ticker_label(code: str) -> str:
    """종목코드 → '삼성전자 (005930)' 형식 반환. 미등록 코드는 코드만 반환."""
    name = STOCK_NAMES.get(str(code).zfill(6))
    return f"{name} ({code})" if name else str(code)

logging.basicConfig(level=logging.WARNING)

st.set_page_config(
    page_title="Alpha Quant — AI Investment Platform",
    page_icon=None,
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── Design System CSS — Alpha Quant Light ───────────────────
st.markdown(
    """
    <style>
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700;800&display=swap');

    html, body, p, label, button, input, select, textarea,
    h1, h2, h3, h4, h5, h6, .stMarkdown, [class*="stText"] {
        font-family: 'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif !important;
    }
    [data-testid="stExpanderToggleIcon"] span,
    [data-baseweb="icon"] span,
    .material-symbols-rounded, .material-symbols-outlined {
        font-family: 'Material Symbols Rounded', 'Material Symbols Outlined', serif !important;
    }
    #MainMenu, footer, [data-testid="stDecoration"], [data-testid="stToolbar"] {
        display: none !important;
    }

    /* ── Base ── */
    html, body, [data-testid="stAppViewContainer"], .main,
    [data-testid="stMainBlockContainer"] {
        background-color: #f0f0f2 !important;
    }
    .block-container {
        padding: 1.5rem 2rem 3rem !important;
        max-width: 100% !important;
        background-color: #f0f0f2 !important;
    }

    /* ── Typography ── */
    h1 {
        font-size: 1.5rem !important;
        font-weight: 700 !important;
        letter-spacing: -0.03em !important;
        color: #111111 !important;
        margin-bottom: 0.25rem !important;
        line-height: 1.3 !important;
    }
    h2 {
        font-size: 1.125rem !important;
        font-weight: 600 !important;
        color: #111111 !important;
        margin: 1.75rem 0 0.875rem !important;
        letter-spacing: -0.02em !important;
    }
    h3 {
        font-size: 0.75rem !important;
        font-weight: 600 !important;
        letter-spacing: 0.08em !important;
        text-transform: uppercase !important;
        color: #555555 !important;
        margin: 1.25rem 0 0.5rem !important;
    }
    p {
        font-size: 0.9375rem !important;
        line-height: 1.7 !important;
        color: #333333 !important;
    }

    /* ── Metric cards ── */
    [data-testid="stMetric"] {
        background: #ffffff !important;
        border: none !important;
        border-radius: 14px !important;
        padding: 1.25rem 1.5rem !important;
        box-shadow: 0 1px 4px rgba(0,0,0,0.07), 0 1px 2px rgba(0,0,0,0.04) !important;
    }
    [data-testid="stMetricLabel"] > div {
        font-size: 0.75rem !important;
        font-weight: 600 !important;
        letter-spacing: 0.06em !important;
        text-transform: uppercase !important;
        color: #666666 !important;
    }
    [data-testid="stMetricValue"] {
        font-size: 1.625rem !important;
        font-weight: 700 !important;
        color: #111111 !important;
        letter-spacing: -0.03em !important;
    }
    [data-testid="stMetricDelta"] {
        font-size: 0.8125rem !important;
        font-weight: 500 !important;
    }

    /* ── Sidebar ── */
    [data-testid="stSidebar"] {
        background: #ffffff !important;
        border-right: 1px solid #e4e4e7 !important;
        box-shadow: 2px 0 8px rgba(0,0,0,0.04) !important;
    }
    [data-testid="stSidebar"] .block-container {
        padding: 1.5rem 1.1rem !important;
        background: #ffffff !important;
    }
    [data-testid="stSidebar"] h2 {
        font-size: 0.9375rem !important;
        color: #111111 !important;
        margin: 0 0 0.2rem !important;
        letter-spacing: -0.01em !important;
        font-weight: 700 !important;
    }
    [data-testid="stSidebar"] h3 {
        margin-top: 1.5rem !important;
        color: #888888 !important;
        font-size: 0.6875rem !important;
        font-weight: 600 !important;
        letter-spacing: 0.1em !important;
    }
    [data-testid="stSidebar"] p,
    [data-testid="stSidebar"] .stMarkdown {
        font-size: 0.875rem !important;
        color: #444444 !important;
    }
    [data-testid="stSidebar"] label {
        color: #333333 !important;
        font-size: 0.875rem !important;
        font-weight: 500 !important;
    }
    [data-testid="stSidebar"] small,
    [data-testid="stSidebar"] .stCaption {
        color: #777777 !important;
        font-size: 0.8rem !important;
    }

    /* ── Tab — pill style ── */
    .stTabs [data-baseweb="tab-list"] {
        background: #e4e4e7 !important;
        border-bottom: none !important;
        border-radius: 10px !important;
        gap: 2px !important;
        padding: 3px !important;
        width: fit-content !important;
        margin-bottom: 1.25rem !important;
    }
    .stTabs [data-baseweb="tab"] {
        background: transparent !important;
        border: none !important;
        border-radius: 8px !important;
        color: #555555 !important;
        font-size: 0.875rem !important;
        font-weight: 500 !important;
        padding: 0.4rem 1rem !important;
        transition: all 0.15s !important;
    }
    .stTabs [data-baseweb="tab"]:hover { color: #111111 !important; }
    .stTabs [aria-selected="true"] {
        background: #ffffff !important;
        color: #111111 !important;
        font-weight: 600 !important;
        box-shadow: 0 1px 4px rgba(0,0,0,0.12) !important;
    }
    .stTabs [data-baseweb="tab-panel"] { padding-top: 0 !important; }

    /* ── Buttons ── */
    .stButton > button {
        background: #ffffff !important;
        border: 1px solid #d4d4d8 !important;
        border-radius: 8px !important;
        color: #222222 !important;
        font-size: 0.875rem !important;
        font-weight: 500 !important;
        padding: 0.5rem 1.1rem !important;
        transition: all 0.15s ease !important;
        box-shadow: 0 1px 2px rgba(0,0,0,0.06) !important;
    }
    .stButton > button:hover {
        background: #f5f5f5 !important;
        border-color: #aaaaaa !important;
        color: #111111 !important;
        box-shadow: 0 2px 6px rgba(0,0,0,0.1) !important;
    }
    .stButton > button[kind="primary"] {
        background: #111111 !important;
        border-color: #111111 !important;
        color: #ffffff !important;
        font-weight: 600 !important;
        box-shadow: 0 2px 6px rgba(0,0,0,0.2) !important;
    }
    .stButton > button[kind="primary"]:hover {
        background: #333333 !important;
        border-color: #333333 !important;
    }

    /* ── Expander ── */
    [data-testid="stExpander"] {
        background: #ffffff !important;
        border: 1px solid #e4e4e7 !important;
        border-radius: 12px !important;
        box-shadow: 0 1px 3px rgba(0,0,0,0.05) !important;
        overflow: hidden !important;
    }
    [data-testid="stExpander"] summary {
        color: #111111 !important;
        font-weight: 500 !important;
        font-size: 0.9375rem !important;
    }

    /* ── Inputs ── */
    [data-baseweb="select"] > div:first-child {
        background: #ffffff !important;
        border: 1px solid #d4d4d8 !important;
        border-radius: 8px !important;
        font-size: 0.875rem !important;
        color: #111111 !important;
    }
    [data-baseweb="input"] input {
        background: #ffffff !important;
        border: 1px solid #d4d4d8 !important;
        border-radius: 8px !important;
        font-size: 0.875rem !important;
        color: #111111 !important;
    }

    /* ── DataFrame ── */
    [data-testid="stDataFrame"] > div {
        border-radius: 12px !important;
        border: 1px solid #e4e4e7 !important;
        overflow: hidden !important;
        font-size: 0.875rem !important;
        background: #ffffff !important;
        box-shadow: 0 1px 3px rgba(0,0,0,0.05) !important;
    }

    /* ── Alert ── */
    [data-testid="stAlert"] {
        border-radius: 10px !important;
        font-size: 0.875rem !important;
        padding: 0.875rem 1.125rem !important;
        line-height: 1.65 !important;
        border: 1px solid rgba(0,0,0,0.06) !important;
    }

    /* ── Divider ── */
    hr {
        border: none !important;
        border-top: 1px solid #e4e4e7 !important;
        margin: 1.25rem 0 !important;
    }

    /* ── Caption ── */
    .stCaption, [data-testid="stCaptionContainer"] {
        font-size: 0.8125rem !important;
        color: #666666 !important;
    }

    /* ── Scrollbar ── */
    ::-webkit-scrollbar { width: 5px; height: 5px; }
    ::-webkit-scrollbar-track { background: transparent; }
    ::-webkit-scrollbar-thumb { background: #cccccc; border-radius: 6px; }
    ::-webkit-scrollbar-thumb:hover { background: #999999; }

    /* ── Toggle ── */
    [data-testid="stToggle"] label {
        color: #222222 !important;
        font-size: 0.875rem !important;
        font-weight: 500 !important;
    }

    /* ── Slider ── */
    [data-testid="stSlider"] [data-baseweb="slider"] [role="slider"] {
        background: #111111 !important;
        border-color: #111111 !important;
    }

    /* ── Custom cards ── */
    .metric-card {
        background: #ffffff;
        border: 1px solid #e4e4e7;
        border-radius: 14px;
        padding: 1.25rem 1.5rem;
        margin: 0.25rem 0;
        box-shadow: 0 1px 4px rgba(0,0,0,0.06);
    }
    .metric-card-dark {
        background: #111111;
        border-radius: 14px;
        padding: 1.25rem 1.5rem;
        margin: 0.25rem 0;
        box-shadow: 0 4px 12px rgba(0,0,0,0.2);
    }
    .regime-offensive { border-left: 3px solid #111111; }
    .regime-defensive { border-left: 3px solid #888888; }
    .regime-wartime   { border-left: 3px solid #cccccc; }
    .status-ok   { color: #166534; font-weight: 600; }
    .status-warn { color: #92400e; font-weight: 600; }
    .status-crit { color: #991b1b; font-weight: 600; }
    </style>
    """,
    unsafe_allow_html=True,
)



# ── 세션 상태 초기화 ─────────────────────────────────────────
def _init_session():
    if "engine" not in st.session_state:
        st.session_state.engine = None
    if "kill_switch_active" not in st.session_state:
        st.session_state.kill_switch_active = False
    if "circuit_breaker" not in st.session_state:
        st.session_state.circuit_breaker = False
    if "last_cycle_result" not in st.session_state:
        st.session_state.last_cycle_result = None
    if "config" not in st.session_state:
        st.session_state.config = load_config()
    if "db" not in st.session_state:
        cfg = st.session_state.config
        st.session_state.db = QuantDatabase(cfg["system"]["db_path"])


_init_session()
config = st.session_state.config
db: QuantDatabase = st.session_state.db





# ═══════════════════════════════════════════════════════════
# 로그인 페이지 (이메일/비밀번호 — iframe 없는 순수 st.markdown)
# ═══════════════════════════════════════════════════════════
def _show_login_page():
    """랜딩 페이지 — iframe 없이 st.markdown 전용 (iframe 잔류 버그 방지)"""

    _is_first = db.count_users() == 0

    # ── 전역 스타일 (로그인 페이지 전용 scope) ──────────────
    st.markdown("""
    <style>
      [data-testid="stAppViewContainer"],
      [data-testid="stAppViewContainer"] > .main,
      [data-testid="stMainBlockContainer"],
      .main .block-container {
        background:#0a0f1e !important;
      }
      [data-testid="stHeader"] { background:#0a0f1e !important; }
      .block-container {
        padding-top:0 !important;
        padding-bottom:0 !important;
        max-width:100% !important;
      }
      /* 폼 카드 */
      div[data-testid="stForm"] {
        background:rgba(13,26,58,0.85) !important;
        border:1px solid rgba(59,130,246,0.25) !important;
        border-radius:16px !important;
        padding:1.25rem !important;
      }
    </style>""", unsafe_allow_html=True)

    # ── HERO ────────────────────────────────────────────────
    st.markdown("""
    <div style="background:linear-gradient(160deg,#0a0f1e 0%,#0d1a3a 60%,#0a2040 100%);
                padding:5rem 2rem 3rem;text-align:center;position:relative;overflow:hidden;">
      <div style="position:absolute;top:-80px;left:50%;transform:translateX(-50%);
                  width:600px;height:400px;border-radius:50%;
                  background:radial-gradient(ellipse,rgba(59,130,246,0.18) 0%,transparent 70%);
                  pointer-events:none;"></div>
      <div style="display:inline-flex;align-items:center;gap:0.5rem;
                  background:rgba(59,130,246,0.15);border:1px solid rgba(59,130,246,0.35);
                  border-radius:100px;padding:0.35rem 1rem;margin-bottom:1.75rem;">
        <div style="width:7px;height:7px;border-radius:50%;background:#3b82f6;
                    box-shadow:0 0 8px #3b82f6;"></div>
        <span style="font-size:0.75rem;font-weight:600;color:#93c5fd;letter-spacing:0.08em;">
          AI · KOSPI 30 · 4중 리스크 방어
        </span>
      </div>
      <div style="font-size:clamp(2rem,5vw,3.5rem);font-weight:900;color:#ffffff;
                  letter-spacing:-0.04em;line-height:1.08;margin-bottom:1.25rem;">
        감정을 배제한<br>
        <span style="background:linear-gradient(90deg,#60a5fa,#a78bfa);
                     -webkit-background-clip:text;-webkit-text-fill-color:transparent;">
          완벽한 데이터 투자
        </span>
      </div>
      <div style="font-size:1.125rem;color:#94a3b8;max-width:540px;margin:0 auto 2.5rem;
                  line-height:1.7;font-weight:400;">
        수면제 대신 AI를 켜두세요.<br>
        <strong style="color:#cbd5e1;">1명의 비서실장</strong>과
        <strong style="color:#cbd5e1;">4명의 전문 에이전트</strong>가
        24시간 당신의 자산을 지키고 불려드립니다.
      </div>
      <div style="display:flex;justify-content:center;gap:2rem;flex-wrap:wrap;">
        <div style="text-align:center;">
          <div style="font-size:1.75rem;font-weight:800;color:#60a5fa;">4중</div>
          <div style="font-size:0.75rem;color:#64748b;margin-top:2px;">리스크 방어막</div>
        </div>
        <div style="width:1px;background:#1e293b;"></div>
        <div style="text-align:center;">
          <div style="font-size:1.75rem;font-weight:800;color:#a78bfa;">5명</div>
          <div style="font-size:0.75rem;color:#64748b;margin-top:2px;">AI 비서진</div>
        </div>
        <div style="width:1px;background:#1e293b;"></div>
        <div style="text-align:center;">
          <div style="font-size:1.75rem;font-weight:800;color:#34d399;">100%</div>
          <div style="font-size:0.75rem;color:#64748b;margin-top:2px;">결정론적 판단</div>
        </div>
      </div>
    </div>""", unsafe_allow_html=True)

    # ── 로그인 / 회원가입 폼 ─────────────────────────────────
    st.markdown("<div style='background:#0a0f1e;padding:2rem 0 0.5rem;'></div>", unsafe_allow_html=True)
    _lf_l, _lf_m, _lf_r = st.columns([1, 2, 1])
    with _lf_m:
        if _is_first:
            st.success("🎉 첫 번째 가입 — 자동으로 관리자가 됩니다.")
        _tab_login, _tab_reg = st.tabs(["🔑 로그인", "📝 회원가입"])

        with _tab_login:
            with st.form("login_form"):
                _li_email = st.text_input("이메일", placeholder="example@email.com")
                _li_pw    = st.text_input("비밀번호", type="password", placeholder="비밀번호 입력")
                _li_sub   = st.form_submit_button("로그인", use_container_width=True, type="primary")
            if _li_sub:
                if not _li_email or not _li_pw:
                    st.error("이메일과 비밀번호를 입력해주세요.")
                else:
                    _found = db.login_user(_li_email, _li_pw)
                    if _found is None:
                        st.error("이메일 또는 비밀번호가 올바르지 않습니다.")
                    else:
                        st.session_state["user"]      = _found
                        st.session_state["logged_in"] = True
                        if _found.get("is_approved"):
                            st.session_state["pending_approval"] = False
                            st.session_state.config["system"]["mode"] = QuantDatabase.user_mode(_found["id"])
                        else:
                            st.session_state["pending_approval"] = True
                        st.rerun()

        with _tab_reg:
            if not _is_first:
                st.info("📋 가입 후 관리자 승인을 받으면 서비스를 이용할 수 있습니다.")
            with st.form("register_form"):
                _rg_name  = st.text_input("이름", placeholder="홍길동")
                _rg_email = st.text_input("이메일", placeholder="example@email.com")
                _rg_pw    = st.text_input("비밀번호 (8자 이상)", type="password")
                _rg_pw2   = st.text_input("비밀번호 확인", type="password")
                _rg_sub   = st.form_submit_button("회원가입", use_container_width=True, type="primary")
            if _rg_sub:
                if not _rg_name or not _rg_email or not _rg_pw:
                    st.error("모든 항목을 입력해주세요.")
                elif len(_rg_pw) < 8:
                    st.error("비밀번호는 8자 이상이어야 합니다.")
                elif _rg_pw != _rg_pw2:
                    st.error("비밀번호가 일치하지 않습니다.")
                else:
                    try:
                        _nu = db.register_user(_rg_email, _rg_pw, _rg_name)
                        if _nu.get("is_admin"):
                            st.session_state["user"]             = _nu
                            st.session_state["logged_in"]        = True
                            st.session_state["pending_approval"] = False
                            st.session_state.config["system"]["mode"] = QuantDatabase.user_mode(_nu["id"])
                            st.rerun()
                        else:
                            st.success("🎉 회원가입 완료! 관리자 승인 후 로그인하세요.")
                    except ValueError as _ve:
                        st.error(str(_ve))

    # ── SECTION 2: Pain Point ────────────────────────────────
    st.markdown("""
    <div style="background:#0d1117;padding:4rem 2rem;">
    <div style="max-width:800px;margin:0 auto;text-align:center;">
      <div style="font-size:.75rem;font-weight:700;letter-spacing:.12em;text-transform:uppercase;
                  color:#3b82f6;margin-bottom:1rem;">WHY ALPHA QUANT</div>
      <div style="font-size:clamp(1.4rem,3vw,2rem);font-weight:800;color:#f1f5f9;
                  letter-spacing:-.03em;line-height:1.15;margin-bottom:1rem;">
        아직도 차트 앞에서<br>밤을 새우고 계신가요?</div>
      <div style="font-size:.9rem;color:#64748b;margin-bottom:2.5rem;line-height:1.7;">
        시세에 휘둘리고, 손실에 감정이 흔들리는 '틀리는 법'에서 벗어나세요.</div>
      <div style="display:grid;grid-template-columns:1fr 1fr;gap:1.5rem;text-align:left;">
        <div style="background:#1a0a0a;border:1px solid #3d1515;border-radius:16px;padding:1.75rem;">
          <div style="font-size:.9rem;font-weight:700;color:#f87171;margin-bottom:1.25rem;">개인 투자자의 하루</div>
          <div style="display:flex;gap:.6rem;margin-bottom:.75rem;align-items:flex-start;">
            <span style="color:#ef4444;font-size:.8rem;font-weight:700;flex-shrink:0;">✕</span>
            <span style="color:#94a3b8;font-size:.875rem;line-height:1.5;">공포에 팔고 탐욕에 사는 뇌동매매</span></div>
          <div style="display:flex;gap:.6rem;margin-bottom:.75rem;align-items:flex-start;">
            <span style="color:#ef4444;font-size:.8rem;font-weight:700;flex-shrink:0;">✕</span>
            <span style="color:#94a3b8;font-size:.875rem;line-height:1.5;">밤새 차트 확인 → 수면 부족 → 판단력 저하</span></div>
          <div style="display:flex;gap:.6rem;margin-bottom:.75rem;align-items:flex-start;">
            <span style="color:#ef4444;font-size:.8rem;font-weight:700;flex-shrink:0;">✕</span>
            <span style="color:#94a3b8;font-size:.875rem;line-height:1.5;">손절 타이밍 놓쳐 손실 눈덩이처럼 불어남</span></div>
          <div style="display:flex;gap:.6rem;align-items:flex-start;">
            <span style="color:#ef4444;font-size:.8rem;font-weight:700;flex-shrink:0;">✕</span>
            <span style="color:#94a3b8;font-size:.875rem;line-height:1.5;">자만 편향 — 몇 번의 성공에 과도한 베팅</span></div>
        </div>
        <div style="background:#020f0f;border:1px solid #0d3d3d;border-radius:16px;padding:1.75rem;">
          <div style="font-size:.9rem;font-weight:700;color:#34d399;margin-bottom:1.25rem;">Alpha Quant의 하루</div>
          <div style="display:flex;gap:.6rem;margin-bottom:.75rem;align-items:flex-start;">
            <span style="color:#34d399;font-size:.8rem;font-weight:700;flex-shrink:0;">✓</span>
            <span style="color:#94a3b8;font-size:.875rem;line-height:1.5;">VIX · 이평선 · MACD 3중 분석으로 냉철한 레짐 판단</span></div>
          <div style="display:flex;gap:.6rem;margin-bottom:.75rem;align-items:flex-start;">
            <span style="color:#34d399;font-size:.8rem;font-weight:700;flex-shrink:0;">✓</span>
            <span style="color:#94a3b8;font-size:.875rem;line-height:1.5;">목표 수익 달성 시 즉시 익절 후 당일 거래 종료</span></div>
          <div style="display:flex;gap:.6rem;margin-bottom:.75rem;align-items:flex-start;">
            <span style="color:#34d399;font-size:.8rem;font-weight:700;flex-shrink:0;">✓</span>
            <span style="color:#94a3b8;font-size:.875rem;line-height:1.5;">스탑로스 자동 실행 — 감정 없이 룰대로만</span></div>
          <div style="display:flex;gap:.6rem;align-items:flex-start;">
            <span style="color:#34d399;font-size:.8rem;font-weight:700;flex-shrink:0;">✓</span>
            <span style="color:#94a3b8;font-size:.875rem;line-height:1.5;">이메일로 아침마다 오늘의 전략 브리핑 수신</span></div>
        </div>
      </div>
    </div></div>""", unsafe_allow_html=True)

    # ── SECTION 3: AI 비서진 ─────────────────────────────────
    st.markdown("""
    <div style="background:#0a0f1e;padding:4rem 2rem;">
    <div style="max-width:900px;margin:0 auto;">
      <div style="text-align:center;margin-bottom:2.5rem;">
        <div style="font-size:.75rem;font-weight:700;letter-spacing:.12em;text-transform:uppercase;
                    color:#a78bfa;margin-bottom:1rem;">THE AI TEAM</div>
        <div style="font-size:clamp(1.4rem,3vw,2rem);font-weight:800;color:#f1f5f9;
                    letter-spacing:-.03em;">1명의 비서실장 + 4명의 전문 에이전트</div>
      </div>
      <!-- 비서실장 -->
      <div style="position:relative;overflow:hidden;border-radius:16px;padding:1.5rem;
                  background:rgba(148,163,184,0.06);border:1px solid rgba(167,139,250,.18);
                  margin-bottom:1rem;">
        <div style="position:absolute;top:0;left:0;right:0;height:3px;border-radius:16px 16px 0 0;
                    background:linear-gradient(90deg,#7c3aed,#a78bfa);"></div>
        <div style="display:inline-block;font-size:.62rem;font-weight:700;letter-spacing:.1em;
                    text-transform:uppercase;padding:.18rem .55rem;border-radius:4px;
                    border:1px solid rgba(167,139,250,.3);color:#a78bfa;margin-bottom:.6rem;">CHIEF OF STAFF</div>
        <div style="font-size:1rem;font-weight:800;color:#e2e8f0;margin-bottom:.2rem;">통합 비서실장</div>
        <div style="font-size:.73rem;font-weight:500;color:#a78bfa;margin-bottom:.45rem;">시장 레짐 분석 · 예산 배분 총괄</div>
        <div style="font-size:.72rem;color:#475569;line-height:1.5;">VIX ≥ 30이면 분석 무관하게 전시 레짐 강제 선포. 이동평균 정배열 + MACD 동조 시 공격 모드 전환. 레짐별로 4개 에이전트 예산 비율을 자동 재조정합니다.</div>
      </div>
      <!-- 4 에이전트 그리드 -->
      <div style="display:grid;grid-template-columns:1fr 1fr;gap:1rem;">
        <div style="position:relative;overflow:hidden;border-radius:16px;padding:1.5rem;
                    background:rgba(148,163,184,0.06);border:1px solid rgba(96,165,250,.15);">
          <div style="position:absolute;top:0;left:0;right:0;height:3px;
                      background:linear-gradient(90deg,#1d4ed8,#60a5fa);"></div>
          <div style="display:inline-block;font-size:.62rem;font-weight:700;letter-spacing:.1em;
                      text-transform:uppercase;padding:.18rem .55rem;border-radius:4px;
                      border:1px solid rgba(96,165,250,.28);color:#60a5fa;margin-bottom:.6rem;">VALUE FINDER</div>
          <div style="font-size:1rem;font-weight:800;color:#e2e8f0;margin-bottom:.2rem;">밸류파인더</div>
          <div style="font-size:.73rem;color:#60a5fa;margin-bottom:.45rem;">가치 함정 판독기</div>
          <div style="font-size:.72rem;color:#475569;line-height:1.5;">마법공식 → 소르티노 &lt; 0.2 영구 배제 → 피오트로스키 F-스코어 필터</div>
        </div>
        <div style="position:relative;overflow:hidden;border-radius:16px;padding:1.5rem;
                    background:rgba(148,163,184,0.06);border:1px solid rgba(52,211,153,.15);">
          <div style="position:absolute;top:0;left:0;right:0;height:3px;
                      background:linear-gradient(90deg,#065f46,#34d399);"></div>
          <div style="display:inline-block;font-size:.62rem;font-weight:700;letter-spacing:.1em;
                      text-transform:uppercase;padding:.18rem .55rem;border-radius:4px;
                      border:1px solid rgba(52,211,153,.28);color:#34d399;margin-bottom:.6rem;">TREND RIDER</div>
          <div style="font-size:1rem;font-weight:800;color:#e2e8f0;margin-bottom:.2rem;">트렌드라이더</div>
          <div style="font-size:.73rem;color:#34d399;margin-bottom:.45rem;">추세 파도타기</div>
          <div style="font-size:.72rem;color:#475569;line-height:1.5;">골든/데드크로스 + MACD 모멘텀 동시 확인 후 추세 추종</div>
        </div>
        <div style="position:relative;overflow:hidden;border-radius:16px;padding:1.5rem;
                    background:rgba(148,163,184,0.06);border:1px solid rgba(192,132,252,.15);">
          <div style="position:absolute;top:0;left:0;right:0;height:3px;
                      background:linear-gradient(90deg,#6d28d9,#c084fc);"></div>
          <div style="display:inline-block;font-size:.62rem;font-weight:700;letter-spacing:.1em;
                      text-transform:uppercase;padding:.18rem .55rem;border-radius:4px;
                      border:1px solid rgba(192,132,252,.28);color:#c084fc;margin-bottom:.6rem;">SWING MASTER</div>
          <div style="font-size:1rem;font-weight:800;color:#e2e8f0;margin-bottom:.2rem;">스윙마스터</div>
          <div style="font-size:.73rem;color:#c084fc;margin-bottom:.45rem;">박스권 방어자</div>
          <div style="font-size:.72rem;color:#475569;line-height:1.5;">볼린저 밴드 하단 돌파 + RSI 과매도 핀포인트 역추세 매매</div>
        </div>
        <div style="position:relative;overflow:hidden;border-radius:16px;padding:1.5rem;
                    background:rgba(148,163,184,0.06);border:1px solid rgba(248,113,113,.15);">
          <div style="position:absolute;top:0;left:0;right:0;height:3px;
                      background:linear-gradient(90deg,#991b1b,#f87171);"></div>
          <div style="display:inline-block;font-size:.62rem;font-weight:700;letter-spacing:.1em;
                      text-transform:uppercase;padding:.18rem .55rem;border-radius:4px;
                      border:1px solid rgba(248,113,113,.28);color:#f87171;margin-bottom:.6rem;">MICRO SNIPER</div>
          <div style="font-size:1rem;font-weight:800;color:#e2e8f0;margin-bottom:.2rem;">마이크로스나이퍼</div>
          <div style="font-size:.73rem;color:#f87171;margin-bottom:.45rem;">1분봉 초단타 스캘핑</div>
          <div style="font-size:.72rem;color:#475569;line-height:1.5;">정액(500만 원) 독립 예산 · ADX+BB+RSI+Stoch 4중 확인 · 목표 달성 즉시 퇴근</div>
        </div>
      </div>
    </div></div>""", unsafe_allow_html=True)

    # ── SECTION 4: 4중 방어 ──────────────────────────────────
    st.markdown("""
    <div style="background:#060b14;padding:4rem 2rem;">
    <div style="max-width:680px;margin:0 auto;">
      <div style="text-align:center;margin-bottom:2rem;">
        <div style="font-size:.75rem;font-weight:700;letter-spacing:.12em;text-transform:uppercase;
                    color:#ef4444;margin-bottom:.75rem;">IRONCLAD DEFENSE</div>
        <div style="font-size:clamp(1.4rem,3vw,2rem);font-weight:800;color:#f1f5f9;
                    letter-spacing:-.03em;">4중 철통 방어 시스템</div>
        <div style="font-size:.875rem;color:#475569;margin-top:.75rem;">돈이 걸린 문제입니다. 단 1원도 허투루 잃지 않습니다.</div>
      </div>
      <div style="display:flex;gap:1rem;align-items:flex-start;margin-bottom:1.25rem;">
        <div style="width:36px;height:36px;border-radius:50%;display:flex;align-items:center;
                    justify-content:center;font-weight:800;font-size:.875rem;flex-shrink:0;
                    background:rgba(239,68,68,.15);color:#f87171;border:1px solid rgba(239,68,68,.3);">1</div>
        <div><div style="font-weight:700;color:#f1f5f9;margin-bottom:.25rem;">VIX 서킷브레이커</div>
        <div style="font-size:.875rem;color:#64748b;line-height:1.6;">공포지수(VIX)가 30을 돌파하면 분석 결과와 무관하게 <b style="color:#94a3b8;">전시 레짐 강제 선포</b>. 모든 신규 진입을 차단하고 관망 태세로 전환합니다.</div></div>
      </div>
      <div style="display:flex;gap:1rem;align-items:flex-start;margin-bottom:1.25rem;">
        <div style="width:36px;height:36px;border-radius:50%;display:flex;align-items:center;
                    justify-content:center;font-weight:800;font-size:.875rem;flex-shrink:0;
                    background:rgba(251,146,60,.15);color:#fb923c;border:1px solid rgba(251,146,60,.3);">2</div>
        <div><div style="font-weight:700;color:#f1f5f9;margin-bottom:.25rem;">일일 MDD 한도</div>
        <div style="font-size:.875rem;color:#64748b;line-height:1.6;">하루 최대 손실 한도(-5%) 도달 시 <b style="color:#94a3b8;">모든 포지션 즉시 청산</b>하고 당일 거래를 완전히 종료합니다.</div></div>
      </div>
      <div style="display:flex;gap:1rem;align-items:flex-start;margin-bottom:1.25rem;">
        <div style="width:36px;height:36px;border-radius:50%;display:flex;align-items:center;
                    justify-content:center;font-weight:800;font-size:.875rem;flex-shrink:0;
                    background:rgba(168,85,247,.15);color:#c084fc;border:1px solid rgba(168,85,247,.3);">3</div>
        <div><div style="font-weight:700;color:#f1f5f9;margin-bottom:.25rem;">물리적 킬스위치</div>
        <div style="font-size:.875rem;color:#64748b;line-height:1.6;">대시보드 내 <b style="color:#94a3b8;">Kill Switch 버튼 1회 클릭</b>으로 모든 자동 거래가 즉시 중단됩니다.</div></div>
      </div>
      <div style="display:flex;gap:1rem;align-items:flex-start;">
        <div style="width:36px;height:36px;border-radius:50%;display:flex;align-items:center;
                    justify-content:center;font-weight:800;font-size:.875rem;flex-shrink:0;
                    background:rgba(20,184,166,.15);color:#2dd4bf;border:1px solid rgba(20,184,166,.3);">4</div>
        <div><div style="font-weight:700;color:#f1f5f9;margin-bottom:.25rem;">개별 종목 스탑로스 / 익절</div>
        <div style="font-size:.875rem;color:#64748b;line-height:1.6;">종목별 손절(-3%)과 익절(+5%) 라인을 <b style="color:#94a3b8;">사전 하드코딩</b>하여 어떤 상황에서도 기계적으로 실행.</div></div>
      </div>
    </div></div>""", unsafe_allow_html=True)

    # ── Bottom CTA & Footer ──────────────────────────────────
    st.markdown("""
    <div style="background:linear-gradient(160deg,#0a0f1e,#0d1a3a);
                padding:5rem 2rem 4rem;text-align:center;border-top:1px solid #1e293b;">
      <div style="font-size:clamp(1.25rem,3vw,1.875rem);font-weight:800;color:#f1f5f9;
                  letter-spacing:-0.03em;margin-bottom:0.75rem;">
        더 이상 시장의 파도에<br>감정을 낭비하지 마십시오.
      </div>
      <div style="font-size:1rem;color:#475569;">
        위 로그인 또는 회원가입으로 지금 바로 시작하세요.
      </div>
    </div>
    <div style="background:#060b14;padding:2rem;text-align:center;border-top:1px solid #0f172a;">
      <div style="font-size:0.75rem;color:#334155;line-height:1.8;">
        Alpha Quant · AI 퀀트 자동 운용 플랫폼 · 모의투자 전용 시스템<br>
        본 서비스는 투자 권유가 아닌 알고리즘 연구 목적의 모의 시스템입니다.<br>
        비밀번호는 PBKDF2-SHA256으로 암호화 저장되며 외부에 공유되지 않습니다.
      </div>
    </div>""", unsafe_allow_html=True)


# 로그인 체크 — 미인증 시 로그인 페이지 표시 후 중단
if not st.session_state.get("logged_in"):
    _show_login_page()
    st.stop()

# 승인 대기 중인 사용자
if st.session_state.get("pending_approval"):
    _pa_user = st.session_state.get("user", {})
    st.markdown("""
    <style>
    [data-testid="stAppViewContainer"],[data-testid="stHeader"]{background:#060b14!important;}
    </style>""", unsafe_allow_html=True)
    st.markdown("""
    <div style="max-width:480px;margin:5rem auto;text-align:center;padding:2.5rem;
                background:#0d1a3a;border:1px solid #1e3a5f;border-radius:20px;">
      <div style="font-size:3rem;margin-bottom:1rem;">⏳</div>
      <div style="font-size:1.5rem;font-weight:800;color:#f1f5f9;margin-bottom:0.75rem;">승인 대기 중</div>
      <div style="color:#64748b;font-size:0.9rem;line-height:1.7;">
        <b style="color:#3b82f6">{name}</b>님, 회원가입이 완료되었습니다.<br>
        관리자가 계정을 승인하면 서비스를 이용할 수 있습니다.
      </div>
    </div>""".format(name=_pa_user.get("name", "사용자")), unsafe_allow_html=True)
    _pa_c1, _pa_c2 = st.columns(2)
    with _pa_c1:
        if st.button("🔄 승인 확인", use_container_width=True, key="pending_refresh"):
            _fresh = db.get_user_by_id(_pa_user.get("id", 0))
            if _fresh and _fresh.get("is_approved"):
                st.session_state["user"]             = _fresh
                st.session_state["pending_approval"] = False
                st.session_state.config["system"]["mode"] = QuantDatabase.user_mode(_fresh["id"])
                st.rerun()
            else:
                st.info("아직 승인되지 않았습니다.")
    with _pa_c2:
        if st.button("로그아웃", use_container_width=True, key="pending_logout"):
            for _k in ["logged_in", "user", "pending_approval"]:
                st.session_state.pop(_k, None)
            st.rerun()
    st.stop()

_admin_user: dict = st.session_state["user"]

# ── 마스커레이딩(원격 지원) 로직 ─────────────────────────────
_impersonate_uid: int | None = st.session_state.get("impersonate_uid")
if _impersonate_uid and _admin_user.get("is_admin"):
    _impersonated = db.get_user_by_id(int(_impersonate_uid))
    _u: dict = _impersonated if _impersonated else _admin_user
    _is_masquerading: bool = True
else:
    _u = _admin_user
    _is_masquerading = False


# ── 헬퍼 함수 ────────────────────────────────────────────────
def fmt_krw(val: float) -> str:
    if abs(val) >= 1e8:
        return f"{val/1e8:+.2f}억" if val != 0 else "0"
    return f"{val:,.0f}"


def fmt_pct(val: float) -> str:
    return f"{val:+.2%}"


def regime_color(regime: str) -> str:
    m = {"공격": "#111111", "방어": "#555555", "전시": "#999999"}
    return m.get(regime, "#a0aec0")


def regime_class(regime: str) -> str:
    m = {"공격": "regime-offensive", "방어": "regime-defensive", "전시": "regime-wartime"}
    return m.get(regime, "")


# ── 사이드바 ─────────────────────────────────────────────────
with st.sidebar:
    # 로그인 사용자 정보 헤더
    _risk_label = {
        "conservative": "안정형",
        "balanced":     "균형형",
        "aggressive":   "공격형",
    }.get(_u.get("risk_profile", "balanced"), "⚖️ 균형형")
    _u_capital = _u.get("initial_capital", config["paper_trading"]["initial_capital"])
    st.markdown(
        f"""
        <div style="padding:0 0 1rem 0;border-bottom:1px solid #e4e4e7;margin-bottom:0.5rem;">
            <div style="font-size:0.9375rem;font-weight:700;color:#111111;letter-spacing:-0.01em;">
                {_u.get('name','투자자')}
            </div>
            <div style="font-size:0.8125rem;color:#666666;margin-top:3px;">
                {_u.get('email','')}
            </div>
            <div style="font-size:0.8125rem;color:#444444;margin-top:4px;display:flex;gap:8px;">
                <span>{_risk_label}</span>
                <span>·</span>
                <span>목표 {_u.get('target_return',0.15):.0%}</span>
                <span>·</span>
                <span>{_u_capital/1e8:.0f}억</span>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    mode = config["system"]["mode"].upper()
    mode_color = "#10b981" if mode == "PAPER" else "#ef4444"

    # 킬스위치 섹션 (DB 영구 상태 기반)
    st.markdown("### 긴급 제어")
    st.markdown("""
    <style>
    /* 킬스위치 발동 버튼 — 진한 빨간 배경, 흰 텍스트 */
    div[data-testid="stButton"]:has(button[kind="primaryFormSubmit"]),
    div[data-testid="stButton"] > button[kind="primary"],
    div[data-testid="stButton"] > button[kind="primaryFormSubmit"] {
        background-color: #b91c1c !important;
        color: #ffffff !important;
        border: none !important;
        font-weight: 700 !important;
        letter-spacing: 0.02em !important;
    }
    div[data-testid="stButton"] > button[kind="primary"]:hover,
    div[data-testid="stButton"] > button[kind="primaryFormSubmit"]:hover {
        background-color: #991b1b !important;
        color: #ffffff !important;
    }
    div[data-testid="stButton"] > button[kind="primary"] p,
    div[data-testid="stButton"] > button[kind="primaryFormSubmit"] p {
        color: #ffffff !important;
    }
    </style>
    """, unsafe_allow_html=True)
    ks_state = db.get_kill_switch()
    ks_active = ks_state["emergency_stop"]
    # session_state와 DB 동기화
    st.session_state.kill_switch_active = ks_active

    if not ks_active:
        if st.button("킬스위치 발동", use_container_width=True, type="primary"):
            db.set_kill_switch(True, "대시보드 수동 발동")
            db.log_system_event("CRITICAL", "Dashboard", "킬스위치 수동 발동 - 대시보드")
            st.session_state.kill_switch_active = True
            try:
                from TradingEngine import TradingEngine
                if st.session_state.engine is None:
                    st.session_state.engine = TradingEngine(config)
                st.session_state.engine.activate_kill_switch("대시보드 수동 발동")
            except Exception:
                pass
            # 카카오톡 긴급 알림 (4️⃣ 킬스위치 보고)
            if _u.get("kakao_notify") and _u.get("kakao_access_token"):
                KakaoAuth.send_kill_switch_kakao(
                    _u["kakao_access_token"],
                    reason="대시보드 수동 발동",
                )
            st.rerun()
    else:
        ks_reason = ks_state.get("kill_switch_reason", "")
        st.error(f"킬스위치 발동 중 — 모든 거래 정지\n사유: {ks_reason}")
        if st.button("킬스위치 해제", use_container_width=True):
            db.set_kill_switch(False, "대시보드 수동 해제")
            db.log_system_event("WARNING", "Dashboard", "킬스위치 수동 해제 - 대시보드")
            st.session_state.kill_switch_active = False
            try:
                if st.session_state.engine is not None:
                    st.session_state.engine.deactivate_kill_switch()
            except Exception:
                pass
            st.rerun()

    st.markdown("---")

    # ── 자동매매 엔진 상태 ────────────────────────────────
    st.markdown("### 자동매매 상태")
    _status_file = Path(__file__).parent / ".trader_status.json"
    try:
        _ts = json.loads(_status_file.read_text(encoding="utf-8")) if _status_file.exists() else {}
    except Exception:
        _ts = {}

    if _ts.get("running"):
        st.success("가동 중")
        _lc = _ts.get("last_cycle_at", "")
        _nc = _ts.get("next_cycle_at", "")
        if _lc:
            try:
                _lc_str = datetime.fromisoformat(_lc).strftime("%m/%d %H:%M")
            except Exception:
                _lc_str = _lc[:16]
            st.caption(f"마지막 사이클: {_lc_str}")
        if _nc:
            try:
                _nc_str = datetime.fromisoformat(_nc).strftime("%m/%d %H:%M")
            except Exception:
                _nc_str = _nc[:16]
            st.caption(f"다음 사이클: {_nc_str}")
        st.caption(f"사이클 {_ts.get('cycle_count', 0)}회 · 레짐: {_ts.get('last_regime','—')}")
    else:
        st.warning("정지됨")
        st.caption("퀀트 자동매매 워크플로우를 시작하세요")

    st.markdown("---")

    # ── 자동 새로고침 ─────────────────────────────────────
    st.markdown("### 자동 새로고침")
    auto_refresh = st.toggle("자동 새로고침", value=True, key="auto_refresh_toggle")
    if auto_refresh:
        refresh_sec = st.select_slider(
            "주기",
            options=[30, 60, 120, 300],
            value=60,
            format_func=lambda x: f"{x}초",
            key="refresh_interval",
        )
        st.caption(f"{refresh_sec}초마다 자동 갱신")
    st.markdown("---")

    # ── 카카오톡 알림 설정 ────────────────────────────────
    st.markdown("### 카카오톡 알림")
    _notify_on = bool(_u.get("kakao_notify", 1))
    _has_token = bool(_u.get("kakao_access_token", ""))
    if _has_token:
        _new_notify = st.toggle(
            "거래/리스크 알림 수신",
            value=_notify_on,
            key="kakao_notify_toggle",
        )
        if _new_notify != _notify_on:
            db.set_kakao_notify(_u["id"], _new_notify)
            st.session_state["user"]["kakao_notify"] = int(_new_notify)
            st.rerun()
        if st.button("테스트 메시지 발송", use_container_width=True, key="kakao_test"):
            _ok = KakaoAuth.send_message(
                _u["kakao_access_token"],
                "🤖 AI 퀀트 연결 확인",
                "카카오톡 알림이 정상적으로 연결되었습니다!",
            )
            st.success("발송 완료 ✅") if _ok else st.error("발송 실패 — 토큰 만료 시 재로그인 필요")
    else:
        st.caption("카카오 로그인 후 자동 활성화됩니다.")

    st.markdown("---")

    # 수동 사이클 실행
    st.markdown("### 수동 제어")
    if st.button("분석 사이클 실행", use_container_width=True):
        with st.spinner("분석 중... (수 분 소요)"):
            try:
                from TradingEngine import TradingEngine
                if st.session_state.engine is None:
                    st.session_state.engine = TradingEngine(config)
                engine = st.session_state.engine
                if st.session_state.kill_switch_active:
                    engine.activate_kill_switch("대시보드 수동 발동")
                result = engine.run_cycle()
                st.session_state.last_cycle_result = result
                st.success(f"완료 · 신호 {result.get('signals_generated', 0)}개")
                # 카카오톡 사이클 요약 알림
                if _u.get("kakao_notify") and _u.get("kakao_access_token"):
                    KakaoAuth.send_cycle_summary(_u["kakao_access_token"], result)
            except Exception as e:
                st.error(f"오류: {e}")

    st.markdown("---")

    # 백테스트
    if st.button("백테스트 실행", use_container_width=True):
        with st.spinner("백테스트 실행 중... (5–10분 소요)"):
            try:
                from SimulationEngine import BacktestEngine
                bt = BacktestEngine(config, db=db)
                results = bt.run_all_strategies(save_to_db=True)
                st.session_state["backtest_results"] = results
                st.success(f"완료 · {len(results)}개 전략 저장됨")
            except Exception as e:
                st.error(f"오류: {e}")

    st.markdown("---")
    if st.button("새로고침", use_container_width=True):
        st.rerun()

    st.caption(f"최종 갱신: {datetime.now().strftime('%H:%M:%S')}")

    # 관제센터 버튼 (관리자 전용)
    if _admin_user.get("is_admin"):
        st.markdown("---")
        _in_cc = st.session_state.get("control_center_mode", False)
        if _in_cc:
            if st.button("🏠 일반 대시보드", use_container_width=True):
                st.session_state["control_center_mode"] = False
                st.session_state.pop("impersonate_uid", None)
                st.rerun()
        else:
            if st.button("👑 관제센터 진입", use_container_width=True, type="primary"):
                st.session_state["control_center_mode"] = True
                st.session_state.pop("impersonate_uid", None)
                st.rerun()

    # 로그아웃
    st.markdown("---")
    if st.button("🚪 로그아웃", use_container_width=True):
        st.session_state["logged_in"]  = False
        st.session_state["user"]       = None
        st.session_state["control_center_mode"] = False
        st.session_state.pop("impersonate_uid", None)
        st.session_state.config["system"]["mode"] = "paper"
        st.rerun()


# ═══════════════════════════════════════════════════════════
# 👑 통합 관제센터 렌더링 함수
# ═══════════════════════════════════════════════════════════
def _render_control_center():
    """총관리자 전용 통합 관제센터 — 모든 사용자 모니터링 + 계정 접속"""
    st.markdown(
        """
        <div style="padding:0.5rem 0 1.25rem 0;border-bottom:1px solid rgba(255,255,255,0.06)">
          <div style="font-size:1.35rem;font-weight:700;color:#f1f5f9;letter-spacing:-0.03em">
            👑 통합 관제센터
          </div>
          <div style="font-size:0.8rem;color:#64748b;margin-top:4px">
            실시간 사용자 포트폴리오 모니터링 &nbsp;·&nbsp; 원클릭 계정 접속(CS 지원)
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    all_users = db.get_all_users()
    if not all_users:
        st.info("등록된 사용자가 없습니다. 회원가입 후 다시 확인하세요.")
        return

    # 요약 지표
    _total   = len(all_users)
    _active  = sum(1 for u in all_users if not u.get("emergency_stop"))
    _stopped = _total - _active

    _sc1, _sc2, _sc3 = st.columns(3)
    for _col, _lbl, _val, _clr in [
        (_sc1, "전체 고객",   _total,   "#0ea5e9"),
        (_sc2, "운용 중",     _active,  "#48bb78"),
        (_sc3, "긴급정지",    _stopped, "#e53e3e"),
    ]:
        with _col:
            st.markdown(
                f"<div style='background:#1a3350;border:1px solid #1e4a78;border-radius:8px;"
                f"padding:0.9rem;text-align:center'>"
                f"<div style='color:#718096;font-size:0.72rem'>{_lbl}</div>"
                f"<div style='color:{_clr};font-size:1.6rem;font-weight:700'>{_val}</div></div>",
                unsafe_allow_html=True,
            )

    st.markdown("<br>", unsafe_allow_html=True)
    st.markdown("### 📋 고객 현황")

    # 컬럼 헤더
    _hc = st.columns([2, 2, 1.5, 1.5, 1.5, 1.5, 1.5])
    for _h, _col in zip(
        ["고객명", "이메일", "성향 / 목표", "자산 규모", "수익률", "상태", "원격 지원"],
        _hc,
    ):
        _col.markdown(
            f"<div style='font-size:0.72rem;color:#475569;font-weight:600;padding:4px 0'>{_h}</div>",
            unsafe_allow_html=True,
        )

    st.markdown("<hr style='margin:4px 0 8px 0;border-color:rgba(255,255,255,0.06)'>",
                unsafe_allow_html=True)

    _risk_map  = {"conservative": "🛡️ 안정", "balanced": "⚖️ 균형", "aggressive": "⚔️ 공격"}
    for _usr in all_users:
        _uid     = _usr["id"]
        _umode   = QuantDatabase.user_mode(_uid)
        _pf      = db.get_portfolio(_umode)
        _initial = _usr.get("initial_capital", 1e8)
        _total_c = _pf.get("total_capital", _initial)
        _ret_pct = (_total_c - _initial) / _initial if _initial else 0

        # 이상 감지
        _ks  = _usr.get("emergency_stop")
        _mdd = _pf.get("max_drawdown", 0) or 0
        if _ks:
            _anomaly, _a_clr = "🔴 긴급정지", "#fc8181"
        elif _mdd < -0.1:
            _anomaly, _a_clr = "🟠 MDD 경고", "#f6ad55"
        elif _ret_pct < -0.05:
            _anomaly, _a_clr = "🟡 손실 주의", "#fef08a"
        else:
            _anomaly, _a_clr = "🟢 정상", "#48bb78"

        _ret_clr = "#48bb78" if _ret_pct >= 0 else "#fc8181"
        _adm_ico = "👑 " if _usr.get("is_admin") else ""

        _rc = st.columns([2, 2, 1.5, 1.5, 1.5, 1.5, 1.5])
        _rc[0].markdown(
            f"<div style='padding:6px 0;font-size:0.9rem;color:#f1f5f9'>"
            f"{_adm_ico}{_usr['name']}</div>",
            unsafe_allow_html=True,
        )
        _rc[1].markdown(
            f"<div style='padding:6px 0;font-size:0.78rem;color:#718096'>"
            f"{_usr['email']}</div>",
            unsafe_allow_html=True,
        )
        _rc[2].markdown(
            f"<div style='padding:6px 0;font-size:0.82rem;color:#cbd5e1'>"
            f"{_risk_map.get(_usr.get('risk_profile','balanced'),'⚖️ 균형')}"
            f"<br><span style='color:#64748b;font-size:0.72rem'>"
            f"목표 {_usr.get('target_return',0.15):.0%}</span></div>",
            unsafe_allow_html=True,
        )
        _rc[3].markdown(
            f"<div style='padding:6px 0;font-size:0.82rem;color:#cbd5e1'>"
            f"{_total_c/1e8:.2f}억</div>",
            unsafe_allow_html=True,
        )
        _rc[4].markdown(
            f"<div style='padding:6px 0;font-size:0.88rem;font-weight:600;color:{_ret_clr}'>"
            f"{_ret_pct:+.2%}</div>",
            unsafe_allow_html=True,
        )
        _rc[5].markdown(
            f"<div style='padding:6px 0;font-size:0.82rem;color:{_a_clr}'>"
            f"{_anomaly}</div>",
            unsafe_allow_html=True,
        )
        with _rc[6]:
            _btn_label = "🔁 현재 접속 중" if st.session_state.get("impersonate_uid") == _uid else "🔍 계정 접속"
            _btn_type  = "primary" if st.session_state.get("impersonate_uid") != _uid else "secondary"
            if st.button(_btn_label, key=f"dive_{_uid}", type=_btn_type, use_container_width=True):
                st.session_state["impersonate_uid"]    = _uid
                st.session_state["control_center_mode"] = False
                st.rerun()

        st.markdown("<hr style='margin:2px 0;border-color:rgba(255,255,255,0.04)'>",
                    unsafe_allow_html=True)

    # 전체 병렬 사이클 실행
    st.markdown("---")
    st.markdown("#### ⚡ 전체 사용자 병렬 매매 사이클")
    if st.button("🚀 전체 사용자 동시 실행", key="cc_multi_cycle", type="primary"):
        with st.spinner(f"{_active}명 병렬 사이클 실행 중..."):
            try:
                from TradingEngine import TradingEngine as _TE
                _mt = _TE(config)
                _results = _mt.run_multi_user_cycle(max_workers=4)
                _ok  = sum(1 for r in _results if not r.get("error"))
                _err = sum(1 for r in _results if r.get("error"))
                st.success(f"✅ 완료 — 성공 {_ok}명 / 실패 {_err}명")
            except Exception as _me:
                st.error(f"오류: {_me}")


# ── 관제센터 모드 인터셉트 ─────────────────────────────────
if st.session_state.get("control_center_mode") and _admin_user.get("is_admin"):
    # 관제센터 전용 헤더
    st.markdown(
        """<div style="padding:0 0 0.5rem 0">
          <span style="font-size:0.72rem;color:#f6ad55;background:rgba(246,173,85,0.12);
          border:1px solid rgba(246,173,85,0.3);border-radius:4px;padding:2px 8px">
          👑 관리자 관제센터 모드
          </span>
        </div>""",
        unsafe_allow_html=True,
    )
    _render_control_center()
    st.stop()


# ── 메인 영역 ────────────────────────────────────────────────
st.markdown(
    """
    <div style="display:flex;align-items:center;gap:12px;padding:0 0 1rem 0;
                border-bottom:1px solid rgba(255,255,255,0.06);margin-bottom:1.25rem;">
        <div>
            <div style="font-size:1.125rem;font-weight:600;color:#f1f5f9;letter-spacing:-0.02em;">
                AI 퀀트 투자 운용 시스템
            </div>
            <div style="font-size:0.75rem;color:#475569;margin-top:2px;letter-spacing:0.02em;">
                KOSPI 30 &nbsp;·&nbsp; 모의투자 &nbsp;·&nbsp; 자동 레짐 분석
            </div>
        </div>
    </div>
    """,
    unsafe_allow_html=True,
)

# ── 마스커레이딩 배너 ─────────────────────────────────────
if _is_masquerading:
    st.markdown(
        f"""
        <div style="background:rgba(245,101,101,0.12);border:1px solid rgba(245,101,101,0.4);
                    border-radius:8px;padding:0.7rem 1rem;margin-bottom:1rem;
                    display:flex;align-items:center;justify-content:space-between">
          <span style="color:#fc8181;font-size:0.9rem;font-weight:600">
            🚨 현재 <b>{_u['name']}</b>({_u['email']})님 계정 원격 지원 중
          </span>
        </div>
        """,
        unsafe_allow_html=True,
    )
    if st.button("🔙 관제센터로 돌아가기", key="return_to_cc"):
        st.session_state.pop("impersonate_uid", None)
        st.session_state["control_center_mode"] = True
        st.rerun()

_tab_list = [
    "포트폴리오", "종목 차트", "레짐 분석", "에이전트",
    "리스크", "거래 내역", "백테스트", "시스템 로그", "설정",
]
if _u.get("is_admin"):
    _tab_list.append("👥 사용자 관리")

tabs = st.tabs(_tab_list)


# ═══════════════════════════════════════════════════════════
# 탭 1: 포트폴리오 현황
# ═══════════════════════════════════════════════════════════
# 마스커레이딩 시 impersonate 사용자의 mode 사용
_cur_mode = QuantDatabase.user_mode(_u["id"])

with tabs[0]:
    portfolio = db.get_portfolio(_cur_mode)
    initial_cap = config["paper_trading"]["initial_capital"]
    total_cap = portfolio.get("total_capital", initial_cap)
    cash = portfolio.get("cash", initial_cap)
    invested = portfolio.get("invested", 0)
    total_pnl = portfolio.get("total_pnl", 0)
    total_pnl_pct = total_pnl / initial_cap if initial_cap > 0 else 0

    # ══════════════════════════════════════════════════════════
    # 🌅 아침 브리핑 패널 (비서실장 모닝 브리핑)
    # ══════════════════════════════════════════════════════════
    try:
        _brief_regime_hist = db.get_regime_history(limit=1)
        _brief_regime = _brief_regime_hist[0] if _brief_regime_hist else {}
        _brief_regime_name = _brief_regime.get("regime", "방어")
        _brief_vix         = float(_brief_regime.get("vix", 0.0) or 0.0)
        _brief_conf        = float(_brief_regime.get("confidence", 0.0) or 0.0)
        _brief_ma          = _brief_regime.get("ma_alignment", "")
        _brief_macd        = _brief_regime.get("macd_signal", "")

        _br_colors = {"공격": ("#22c55e", "#052e16", "🟢"), "방어": ("#f59e0b", "#1c1003", "🟡"), "전시": ("#ef4444", "#1a0000", "🔴")}
        _br_clr, _br_bg, _br_icon = _br_colors.get(_brief_regime_name, ("#94a3b8", "#0f172a", "⚪"))

        _brief_sn_fixed = int(float(
            st.session_state.get("user", {}).get("sniper_fixed_budget", 5_000_000) or 5_000_000
        ))
        _brief_alloc = config["chief_of_staff"]["regime_allocation"].get(
            {"공격": "OFFENSIVE", "방어": "DEFENSIVE", "전시": "WARTIME"}.get(_brief_regime_name, "DEFENSIVE"), {}
        )
        _br_alloc_txt = (
            f"밸류 {_brief_alloc.get('value_finder',0):.0%} / "
            f"트렌드 {_brief_alloc.get('trend_rider',0):.0%} / "
            f"스윙 {_brief_alloc.get('swing_master',0):.0%} / "
            f"스나이퍼 정액 {_brief_sn_fixed:,}원"
        )
        if _brief_regime_name == "전시":
            _br_status_msg = "VIX 급등으로 전시 레짐 — 거래 제한, 스나이퍼 예산 자동 회수됩니다."
        elif _brief_regime_name == "방어":
            _br_status_msg = f"VIX {_brief_vix:.1f} 경계 구간 — 핵심 자본 보수적 운용. 스나이퍼는 정액 {_brief_sn_fixed:,}원 독립 가동."
        else:
            _br_status_msg = f"VIX {_brief_vix:.1f} 안정 — 전략 전면 가동. 스나이퍼는 정액 {_brief_sn_fixed:,}원 독립 스캘핑."

        st.markdown(
            f"<div style='background:{_br_bg};border-left:5px solid {_br_clr};"
            f"border-radius:10px;padding:1rem 1.4rem;margin-bottom:0.6rem;'>"
            f"<div style='display:flex;align-items:center;gap:0.6rem;margin-bottom:0.5rem;'>"
            f"<span style='font-size:1.1rem;'>🌅</span>"
            f"<span style='color:{_br_clr};font-weight:700;font-size:0.9rem;letter-spacing:0.04em;'>"
            f"비서실장 브리핑</span>"
            f"<span style='margin-left:auto;background:{_br_clr}22;color:{_br_clr};"
            f"border-radius:20px;padding:0.15rem 0.7rem;font-size:0.75rem;font-weight:700;'>"
            f"{_br_icon} {_brief_regime_name} 레짐</span></div>"
            f"<div style='color:#e2e8f0;font-size:0.85rem;line-height:1.6;'>"
            f"<b>시장 상태:</b> {_br_status_msg}<br>"
            f"<b>자산 배분:</b> {_br_alloc_txt}<br>"
            f"<b>지표:</b> MA배열={_brief_ma} · MACD={_brief_macd} · 신뢰도={_brief_conf:.0%}"
            f"</div></div>",
            unsafe_allow_html=True,
        )
        # 카카오톡 아침 브리핑 발송 버튼
        if _u.get("kakao_notify") and _u.get("kakao_access_token"):
            if st.button("📱 카카오톡으로 아침 브리핑 발송", key="btn_kakao_brief"):
                _brief_ok = KakaoAuth.send_morning_briefing(
                    _u["kakao_access_token"],
                    regime     = _brief_regime_name,
                    vix        = _brief_vix,
                    confidence = _brief_conf,
                    ma_alignment = str(_brief_ma),
                    macd_signal  = str(_brief_macd),
                    alloc_txt    = _br_alloc_txt,
                    sniper_fixed = _brief_sn_fixed,
                )
                if _brief_ok:
                    st.toast("📱 카카오톡으로 아침 브리핑이 발송되었습니다!", icon="✅")
                else:
                    st.toast("발송 실패 — 토큰 만료 시 재로그인 필요", icon="❌")
    except Exception:
        pass

    # 상단 KPI
    c1, c2, c3, c4, c5 = st.columns(5)
    with c1:
        st.metric("총 자산", f"{total_cap:,.0f}원", f"{total_pnl:+,.0f}원")
    with c2:
        st.metric("누적 수익률", fmt_pct(total_pnl_pct),
                  delta_color="normal")
    with c3:
        st.metric("투자 금액", f"{invested:,.0f}원")
    with c4:
        st.metric("현금 보유", f"{cash:,.0f}원",
                  f"{cash/total_cap:.1%} 비중" if total_cap > 0 else "")
    with c5:
        invest_ratio = invested / total_cap if total_cap > 0 else 0
        st.metric("투자 비중", f"{invest_ratio:.1%}")

    st.markdown("---")

    col_l, col_r = st.columns([2, 1])

    with col_l:
        # 수익 곡선
        perf_history = db.get_performance_history(_cur_mode, 90)
        if perf_history:
            df_perf = pd.DataFrame(perf_history)
            df_perf["date"] = pd.to_datetime(df_perf["date"])
            df_perf = df_perf.sort_values("date")

            fig = go.Figure()
            fig.add_trace(go.Scatter(
                x=df_perf["date"],
                y=df_perf["cumulative_return"] * 100,
                name="포트폴리오",
                line=dict(color="#00d4ff", width=2),
                fill="tozeroy",
                fillcolor="rgba(0,212,255,0.08)",
            ))
            fig.add_trace(go.Scatter(
                x=df_perf["date"],
                y=df_perf["benchmark_return"] * 100,
                name="벤치마크(S&P500)",
                line=dict(color="#f6ad55", width=1.5, dash="dot"),
            ))
            fig.update_layout(
                title="누적 수익률 (%)",
                paper_bgcolor="rgba(0,0,0,0)",
                plot_bgcolor="rgba(0,0,0,0)",
                font=dict(color="#e2e8f0"),
                legend=dict(orientation="h", y=1.02),
                margin=dict(l=0, r=0, t=40, b=0),
                xaxis=dict(gridcolor="#2d3748"),
                yaxis=dict(gridcolor="#2d3748", ticksuffix="%"),
                height=320,
            )
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.info("수익 히스토리가 없습니다. 사이클을 실행하면 데이터가 쌓입니다.")

    with col_r:
        # 자산 배분 도넛
        labels = ["현금", "투자"]
        values = [cash, invested]
        if sum(values) > 0:
            fig_pie = go.Figure(go.Pie(
                labels=labels,
                values=values,
                hole=0.6,
                marker_colors=["#4a5568", "#00d4ff"],
            ))
            fig_pie.update_layout(
                title="자산 배분",
                paper_bgcolor="rgba(0,0,0,0)",
                font=dict(color="#e2e8f0"),
                margin=dict(l=0, r=0, t=40, b=0),
                height=280,
                showlegend=True,
                legend=dict(orientation="h", y=-0.1),
            )
            st.plotly_chart(fig_pie, use_container_width=True)

    st.markdown("### 보유 포지션")
    positions = db.get_positions(_cur_mode)
    if positions:
        df_pos = pd.DataFrame(positions)
        df_pos["종목명"] = df_pos["ticker"].apply(ticker_label)
        display_cols = {
            "종목명": "종목",
            "agent_name": "에이전트",
            "quantity": "수량",
            "avg_cost": "평균단가",
            "current_price": "현재가",
            "market_value": "평가액",
            "unrealized_pnl": "평가손익",
            "unrealized_pnl_pct": "수익률",
        }
        df_display = df_pos[["종목명"] + [c for c in display_cols if c in df_pos.columns and c != "종목명"]].rename(columns=display_cols)
        if "수익률" in df_display.columns:
            df_display["수익률"] = df_display["수익률"].apply(lambda x: f"{x:+.2%}")
        if "평가손익" in df_display.columns:
            df_display["평가손익"] = df_display["평가손익"].apply(lambda x: f"{x:+,.0f}")
        if "평가액" in df_display.columns:
            df_display["평가액"] = df_display["평가액"].apply(lambda x: f"{x:,.0f}")
        if "평균단가" in df_display.columns:
            df_display["평균단가"] = df_display["평균단가"].apply(lambda x: f"{x:,.2f}")
        if "현재가" in df_display.columns:
            df_display["현재가"] = df_display["현재가"].apply(lambda x: f"{x:,.2f}")
        st.dataframe(df_display, use_container_width=True, hide_index=True)
    else:
        st.info("보유 포지션이 없습니다.")


# ═══════════════════════════════════════════════════════════
# 탭 2: 종목 차트
# ═══════════════════════════════════════════════════════════
with tabs[1]:
    from plotly.subplots import make_subplots

    # ── 거래 종목 목록 (DB에서 실제 거래된 종목 우선) ──────────
    _all_trades_chart = db.get_trades(_cur_mode, limit=500)
    _traded_set = set()
    _trade_rows = []  # ticker별 거래 기록
    if _all_trades_chart:
        _df_all_t = pd.DataFrame(_all_trades_chart)
        _traded_set = set(_df_all_t["ticker"].tolist())
        _trade_rows = _df_all_t.to_dict("records")

    # 거래된 종목 먼저, 나머지 뒤에
    _code_to_name = STOCK_NAMES
    _name_to_code: dict[str, str] = {}
    for code, name in _code_to_name.items():
        if code in _traded_set:
            _name_to_code[f"★  {name}"] = code   # 거래 종목 표시
        else:
            _name_to_code[name] = code
    # 거래 종목 먼저 정렬
    _sorted_options = sorted(
        _name_to_code.items(),
        key=lambda x: (0 if x[0].startswith("★") else 1, x[0])
    )
    _option_labels = [k for k, _ in _sorted_options]

    # ── 헬퍼: 이유 문자열 → 차트용 한줄 요약 ─────────────────
    def _short_reason(reason: str, action: str) -> str:
        _kw = {
            "BB하단돌파": "볼린저 하단 이탈",
            "BB하단근접": "볼린저 하단 근접",
            "RSI과매도":  "RSI 과매도",
            "MACD상승":   "MACD 상승전환",
            "MA위":       "이평선 상향돌파",
            "마법공식":   "마법공식 저평가",
            "F스코어":    "재무건전성 우수",
            "스탑로스":   "스탑로스 발동",
            "이익실현":   "목표가 도달",
        }
        parts = [p.strip() for p in reason.split("|")]
        tags = []
        for part in parts[:2]:
            for kw, label in _kw.items():
                if kw in part:
                    tags.append(label)
                    break
            else:
                tags.append(part[:12])
        prefix = "매수" if action == "BUY" else "매도"
        return f"{prefix}: " + " + ".join(tags) if tags else prefix

    # ── 컨트롤 ─────────────────────────────────────────────
    ctrl_c1, ctrl_c2 = st.columns([4, 2])
    with ctrl_c1:
        _default_idx = 0  # 거래 종목이 있으면 첫번째가 자동으로 거래 종목
        selected_label = st.selectbox(
            "종목 선택  (★ = 실제 거래된 종목)",
            options=_option_labels,
            index=_default_idx,
        )
        chart_ticker = _name_to_code[selected_label]
        selected_name = _code_to_name.get(chart_ticker, chart_ticker)
    with ctrl_c2:
        period_map = {"1개월": "1mo", "3개월": "3mo", "6개월": "6mo", "1년": "1y", "2년": "2y"}
        selected_period_label = st.selectbox("기간", list(period_map.keys()), index=2)
        selected_period = period_map[selected_period_label]

    # ── 데이터 로드 (올바른 API 사용) ──────────────────────────
    @st.cache_data(ttl=600, show_spinner="주가 데이터 로딩 중...")
    def _load_chart_data(ticker: str, period: str):
        try:
            from KoreaDataProvider import get_provider
            dp = get_provider()
            df = dp.get_price_data(ticker, period=period)
            return df if (df is not None and not df.empty) else pd.DataFrame()
        except Exception:
            return pd.DataFrame()

    df_chart = _load_chart_data(chart_ticker, selected_period)

    if df_chart.empty:
        st.warning("주가 데이터를 불러올 수 없습니다. 기간을 바꾸거나 잠시 후 다시 시도해 주세요.")
    else:
        try:
            import ta

            close = df_chart["Close"]
            open_ = df_chart["Open"]
            high  = df_chart["High"]
            low   = df_chart["Low"]
            vol   = df_chart["Volume"]

            # ── 지표 계산 ────────────────────────────────
            bb_w  = 20
            bb    = ta.volatility.BollingerBands(close, window=bb_w, window_dev=2)
            bb_up = bb.bollinger_hband()
            bb_mid= bb.bollinger_mavg()
            bb_lo = bb.bollinger_lband()

            ma5   = close.rolling(5).mean()
            ma20  = close.rolling(20).mean()
            ma60  = close.rolling(60).mean()

            rsi_val  = ta.momentum.RSIIndicator(close, window=14).rsi()
            macd_obj = ta.trend.MACD(close, window_slow=26, window_fast=12, window_sign=9)
            macd_line= macd_obj.macd()
            macd_sig = macd_obj.macd_signal()
            macd_hist= macd_obj.macd_diff()

            # ── 이 종목의 거래 기록 수집 ─────────────────
            ticker_trades = [r for r in _trade_rows if r["ticker"] == chart_ticker]
            buy_pts, sell_pts = [], []   # {dt, price, reason, agent}
            chart_dates = set(df_chart.index.normalize())
            for row in ticker_trades:
                dt = pd.to_datetime(row["executed_at"]).normalize()
                if dt in chart_dates:
                    px_s = df_chart.loc[df_chart.index.normalize() == dt, "Close"]
                    if not px_s.empty:
                        pt = {
                            "dt": dt,
                            "price": float(px_s.iloc[-1]),
                            "reason": row.get("reason", ""),
                            "agent": row.get("agent_name", ""),
                            "action": row["action"],
                            "executed_at": row["executed_at"],
                            "quantity": row.get("quantity", 0),
                            "total_amount": row.get("total_amount", 0),
                        }
                        if row["action"] == "BUY":
                            buy_pts.append(pt)
                        else:
                            sell_pts.append(pt)

            # ── Plotly 서브플롯 ──────────────────────────
            fig = make_subplots(
                rows=4, cols=1,
                shared_xaxes=True,
                row_heights=[0.52, 0.13, 0.17, 0.18],
                vertical_spacing=0.025,
                subplot_titles=(
                    f"{selected_name}  ({chart_ticker})",
                    "거래량",
                    "RSI  (14일)",
                    "MACD  (12 / 26 / 9)",
                ),
            )

            x = df_chart.index

            # 캔들스틱
            fig.add_trace(go.Candlestick(
                x=x, open=open_, high=high, low=low, close=close,
                name="주가",
                increasing_line_color="#ef4444", increasing_fillcolor="#ef4444",
                decreasing_line_color="#0ea5e9", decreasing_fillcolor="#0ea5e9",
            ), row=1, col=1)

            # 볼린저 밴드
            fig.add_trace(go.Scatter(x=x, y=bb_up,  name="BB 상단", line=dict(color="rgba(251,191,36,0.55)", width=1)), row=1, col=1)
            fig.add_trace(go.Scatter(x=x, y=bb_mid, name="BB 중앙", line=dict(color="rgba(251,191,36,0.9)",  width=1.2, dash="dot")), row=1, col=1)
            fig.add_trace(go.Scatter(x=x, y=bb_lo, name="BB 하단",
                line=dict(color="rgba(251,191,36,0.55)", width=1),
                fill="tonexty", fillcolor="rgba(251,191,36,0.04)",
            ), row=1, col=1)

            # 이동평균선
            fig.add_trace(go.Scatter(x=x, y=ma5,  name="MA 5",  line=dict(color="#a78bfa", width=1)),   row=1, col=1)
            fig.add_trace(go.Scatter(x=x, y=ma60, name="MA 60", line=dict(color="#34d399", width=1.5)), row=1, col=1)

            # 매수 마커 + 차트 위 말풍선 annotation
            if buy_pts:
                fig.add_trace(go.Scatter(
                    x=[p["dt"] for p in buy_pts],
                    y=[p["price"] * 0.985 for p in buy_pts],
                    mode="markers+text",
                    name="매수",
                    text=["B"] * len(buy_pts),
                    textposition="bottom center",
                    marker=dict(symbol="triangle-up", size=16, color="#22c55e",
                                line=dict(width=1.5, color="#f0fdf4")),
                    textfont=dict(size=9, color="#22c55e"),
                    hovertext=[_short_reason(p["reason"], "BUY") for p in buy_pts],
                    hoverinfo="text+x",
                ), row=1, col=1)
                for p in buy_pts:
                    fig.add_annotation(
                        x=p["dt"], y=p["price"] * 0.97,
                        text=_short_reason(p["reason"], "BUY"),
                        showarrow=True, arrowhead=2, arrowcolor="#22c55e", arrowwidth=1.5,
                        ax=0, ay=40,
                        bgcolor="rgba(21,128,61,0.85)", bordercolor="#22c55e", borderwidth=1,
                        font=dict(size=9, color="#f0fdf4"),
                        xref="x", yref="y",
                    )

            # 매도 마커 + annotation
            if sell_pts:
                fig.add_trace(go.Scatter(
                    x=[p["dt"] for p in sell_pts],
                    y=[p["price"] * 1.015 for p in sell_pts],
                    mode="markers+text",
                    name="매도",
                    text=["S"] * len(sell_pts),
                    textposition="top center",
                    marker=dict(symbol="triangle-down", size=16, color="#f43f5e",
                                line=dict(width=1.5, color="#fff1f2")),
                    textfont=dict(size=9, color="#f43f5e"),
                    hovertext=[_short_reason(p["reason"], "SELL") for p in sell_pts],
                    hoverinfo="text+x",
                ), row=1, col=1)
                for p in sell_pts:
                    fig.add_annotation(
                        x=p["dt"], y=p["price"] * 1.03,
                        text=_short_reason(p["reason"], "SELL"),
                        showarrow=True, arrowhead=2, arrowcolor="#f43f5e", arrowwidth=1.5,
                        ax=0, ay=-40,
                        bgcolor="rgba(190,18,60,0.85)", bordercolor="#f43f5e", borderwidth=1,
                        font=dict(size=9, color="#fff1f2"),
                        xref="x", yref="y",
                    )

            # 거래량
            vol_colors = ["#ef4444" if c >= o else "#0ea5e9" for c, o in zip(close, open_)]
            fig.add_trace(go.Bar(x=x, y=vol, name="거래량", marker_color=vol_colors, showlegend=False), row=2, col=1)

            # RSI
            fig.add_trace(go.Scatter(x=x, y=rsi_val, name="RSI", line=dict(color="#f59e0b", width=1.5)), row=3, col=1)
            fig.add_hrect(y0=70, y1=100, row=3, col=1, fillcolor="rgba(239,68,68,0.1)",   line_width=0)
            fig.add_hrect(y0=0,  y1=30,  row=3, col=1, fillcolor="rgba(59,130,246,0.1)",  line_width=0)
            fig.add_hline(y=70, row=3, col=1, line=dict(color="#ef4444", width=1, dash="dash"))
            fig.add_hline(y=30, row=3, col=1, line=dict(color="#0ea5e9", width=1, dash="dash"))

            # MACD
            hist_colors = ["#ef4444" if v >= 0 else "#0ea5e9" for v in macd_hist.fillna(0)]
            fig.add_trace(go.Bar(x=x, y=macd_hist, name="히스토그램", marker_color=hist_colors, showlegend=True), row=4, col=1)
            fig.add_trace(go.Scatter(x=x, y=macd_line, name="MACD",   line=dict(color="#60a5fa", width=1.5)), row=4, col=1)
            fig.add_trace(go.Scatter(x=x, y=macd_sig,  name="Signal", line=dict(color="#f87171", width=1.5)), row=4, col=1)
            fig.add_hline(y=0, row=4, col=1, line=dict(color="rgba(255,255,255,0.15)", width=1))

            fig.update_layout(
                height=880,
                template="plotly_dark",
                paper_bgcolor="#162640",
                plot_bgcolor="#162640",
                font=dict(color="#94a3b8", size=10.5),
                legend=dict(
                    orientation="h", yanchor="bottom", y=1.02, xanchor="left", x=0,
                    bgcolor="rgba(0,0,0,0.35)", bordercolor="rgba(255,255,255,0.08)", borderwidth=1,
                ),
                xaxis_rangeslider_visible=False,
                margin=dict(l=55, r=20, t=55, b=20),
                hoverlabel=dict(bgcolor="#1a3350", bordercolor="#1e4a78", font_size=12),
            )
            fig.update_yaxes(gridcolor="rgba(255,255,255,0.04)", zerolinecolor="rgba(255,255,255,0.06)")
            fig.update_yaxes(title_text="가격(원)", row=1, col=1)
            fig.update_yaxes(title_text="거래량",   row=2, col=1)
            fig.update_yaxes(title_text="RSI",      row=3, col=1, range=[0, 100])
            fig.update_yaxes(title_text="MACD",     row=4, col=1)
            fig.update_annotations(font_size=9)

            st.plotly_chart(fig, use_container_width=True)

            # ── 현재 지표 요약 카드 ───────────────────────
            last = close.iloc[-1]
            prev = close.iloc[-2]
            chg  = (last - prev) / prev
            rsi_now = float(rsi_val.iloc[-1])
            bb_range = float(bb_up.iloc[-1]) - float(bb_lo.iloc[-1])
            bb_pos = (last - float(bb_lo.iloc[-1])) / bb_range if bb_range > 0 else 0.5

            m1, m2, m3, m4, m5 = st.columns(5)
            m1.metric("현재가",    f"{last:,.0f}원",   f"{chg:+.2%}")
            m2.metric("RSI (14)",  f"{rsi_now:.1f}",
                      "과매수 ▲" if rsi_now >= 70 else ("과매도 ▼" if rsi_now <= 30 else "중립"))
            m3.metric("BB 위치",   f"{bb_pos*100:.0f}%",
                      "상단 근접" if bb_pos >= 0.9 else ("하단 근접" if bb_pos <= 0.1 else "중간"))
            m4.metric("MACD",      f"{float(macd_line.iloc[-1]):.2f}",
                      "상승↑" if float(macd_line.iloc[-1]) > float(macd_sig.iloc[-1]) else "하락↓")
            m5.metric("MA60 대비", f"{(last/float(ma60.iloc[-1])-1):+.2%}",
                      "상승배열" if last > float(ma60.iloc[-1]) else "하락배열")

            # ── 현재 시장 상황 자동 해석 (멘토 메시지) ────
            st.markdown("")
            msgs = []
            if rsi_now <= 30 and bb_pos <= 0.15:
                msgs.append(("info",
                    "**지금 이 종목은 과매도 구간입니다.** RSI가 {:.0f}으로 30 이하이고, "
                    "볼린저 밴드 하단까지 내려왔습니다. 스윙마스터가 반등을 노리는 구간이에요. "
                    "단, 거래량도 함께 봐야 합니다 — 거래량이 늘면서 반등하면 신뢰도가 높습니다.".format(rsi_now)))
            elif rsi_now >= 70 and bb_pos >= 0.85:
                msgs.append(("warning",
                    "**단기 과열 구간입니다.** RSI가 {:.0f}으로 70 이상이고 볼린저 밴드 상단에 닿았습니다. "
                    "이런 구간에서는 추가 매수보다 보유 중이라면 익절을 고려할 시점입니다.".format(rsi_now)))
            if float(macd_line.iloc[-1]) > float(macd_sig.iloc[-1]) and float(macd_hist.iloc[-1]) > float(macd_hist.iloc[-2]):
                msgs.append(("success",
                    "**MACD가 상승 중입니다.** MACD 라인이 시그널선 위에 있고 히스토그램이 커지고 있어요. "
                    "모멘텀(가속도)이 붙는 초기 단계로, 트렌드라이더가 매수를 검토하는 신호입니다."))
            if last > float(ma20.iloc[-1]) > float(ma60.iloc[-1]):
                msgs.append(("success",
                    "**이동평균선이 상승 배열입니다.** 현재가 > MA20 > MA60 순서로 정렬되어 있습니다. "
                    "이건 중기 상승 추세가 유지되고 있다는 뜻이에요."))

            for kind, msg in msgs:
                if kind == "info":    st.info(msg)
                elif kind == "warning": st.warning(msg)
                elif kind == "success": st.success(msg)

            # ── 이 종목의 실제 거래 해설 패널 ─────────────
            all_pts = buy_pts + sell_pts
            all_pts.sort(key=lambda p: p["dt"])

            if all_pts:
                st.markdown("---")
                st.markdown(f"### {selected_name} 거래 분석 — AI가 왜 이 시점에 거래했는지 설명합니다")
                st.caption("차트의 B(매수)·S(매도) 마커와 함께 아래 설명을 보시면 이해가 더 쉽습니다.")

                _agent_full = {
                    "value_finder": "밸류파인더 (가치투자)",
                    "trend_rider":  "트렌드라이더 (추세매매)",
                    "swing_master": "스윙마스터 (반등매매)",
                }
                _signal_explain = {
                    "BB하단돌파":   ("볼린저 밴드 하단 이탈",
                        "주가가 '통계적 하한선' 아래로 내려갔습니다. 정상 범위를 벗어난 낙폭이라 "
                        "반등 확률이 높아지는 구간입니다. 볼린저 밴드는 20일 평균가 기준 ±2 표준편차로 만든 선이에요."),
                    "BB하단근접":   ("볼린저 밴드 하단 근접",
                        "아직 하단선을 뚫지는 않았지만 근접했습니다. 본격적인 과매도 구간 진입 직전 신호입니다."),
                    "RSI과매도":    ("RSI 과매도",
                        "RSI(상대강도지수)가 30 이하입니다. 최근 14일 동안 하락이 상승보다 훨씬 강했다는 뜻이에요. "
                        "보통 30 이하면 '너무 많이 떨어졌다'고 판단하며 반등을 기대합니다."),
                    "MA위":         ("이동평균선 상향 돌파",
                        "단기 이동평균이 장기 이동평균 위로 올라갔습니다. 이걸 '골든크로스'라고 부르며, "
                        "중기 상승 추세가 시작됐다는 신호입니다."),
                    "MACD상승모멘텀":("MACD 상승 전환",
                        "MACD 라인이 시그널선을 위로 돌파했습니다. 주가의 상승 속도가 빨라지고 있다는 뜻이에요. "
                        "이동평균 두 개의 차이로 만든 지표인데, 양수로 전환되면 매수 신호입니다."),
                    "마법공식순위": ("마법공식 저평가 순위",
                        "이익수익률(싸게 사는 정도)과 ROIC(돈을 잘 버는 정도)를 합산한 순위입니다. "
                        "순위가 낮을수록 '싸면서 잘 버는 기업'이에요. 조엘 그린블라트의 마법공식 전략입니다."),
                    "F스코어":      ("피오트로스키 F스코어",
                        "기업의 재무 건전성을 9가지 항목으로 평가한 점수입니다. 5점 이상이면 "
                        "재무적으로 탄탄한 기업이라는 뜻이에요. (수익성, 레버리지, 운영효율 세 영역을 봅니다)"),
                    "스탑로스":     ("스탑로스 (손절매)",
                        "매입가에서 일정 비율 이상 손실이 나면 자동으로 파는 규칙입니다. "
                        "손실이 더 커지기 전에 빠져나오는 '리스크 관리'의 핵심 도구예요."),
                    "이익실현":     ("이익실현 (익절)",
                        "목표 수익률에 도달했을 때 자동으로 파는 규칙입니다. "
                        "'욕심 부리지 말고 계획한 만큼 벌면 나온다'는 원칙을 자동화한 것입니다."),
                    "목표가":       ("목표가 (볼린저 중앙선)",
                        "볼린저 밴드 중앙선(20일 이동평균)을 단기 목표가로 삼습니다. "
                        "하단에서 반등하면 중앙선까지는 돌아가려는 성질을 이용합니다."),
                }

                for idx, pt in enumerate(all_pts):
                    is_buy = (pt["action"] == "BUY")
                    color   = "#22c55e" if is_buy else "#f43f5e"
                    bg      = "rgba(21,128,61,0.12)" if is_buy else "rgba(190,18,60,0.12)"
                    border  = "#166534" if is_buy else "#9f1239"
                    label   = "매수" if is_buy else "매도"
                    agent   = _agent_full.get(pt["agent"], pt["agent"])
                    dt_str  = pd.to_datetime(pt["executed_at"]).strftime("%Y년 %m월 %d일 %H:%M")
                    amt_str = f"{int(pt['total_amount']):,}원" if pt["total_amount"] else ""

                    # 상단 헤더 카드
                    st.markdown(
                        f"""<div style="background:{bg};border:1px solid {border};border-radius:8px;
                                       padding:1rem 1.25rem;margin:0.75rem 0 0.25rem;">
                            <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:0.5rem;">
                                <span style="color:{color};font-weight:700;font-size:0.9rem;">
                                    {label} #{idx+1}
                                </span>
                                <span style="color:#64748b;font-size:0.78rem;">{dt_str}</span>
                            </div>
                            <div style="display:flex;gap:2rem;flex-wrap:wrap;">
                                <span style="font-size:0.8rem;color:#94a3b8;">
                                    담당 에이전트 &nbsp;<strong style="color:#e2e8f0;">{agent}</strong>
                                </span>
                                <span style="font-size:0.8rem;color:#94a3b8;">
                                    체결가 &nbsp;<strong style="color:#e2e8f0;">{pt['price']:,.0f}원</strong>
                                </span>
                                <span style="font-size:0.8rem;color:#94a3b8;">
                                    수량 &nbsp;<strong style="color:#e2e8f0;">{int(pt['quantity'])}주</strong>
                                </span>
                                {"<span style='font-size:0.8rem;color:#94a3b8;'>거래금액 &nbsp;<strong style='color:#e2e8f0;'>" + amt_str + "</strong></span>" if amt_str else ""}
                            </div>
                        </div>""",
                        unsafe_allow_html=True,
                    )

                    # 신호별 설명
                    reason_parts = [p.strip() for p in pt["reason"].split("|") if p.strip()]
                    for part in reason_parts:
                        matched = False
                        for kw, (title, explain) in _signal_explain.items():
                            if kw in part:
                                # 수치 추출
                                val_str = ""
                                if "=" in part:
                                    val_str = part.split("=", 1)[-1].replace("(", "").replace(")", "")
                                elif "(" in part:
                                    val_str = part[part.index("(")+1:part.index(")")]
                                st.markdown(
                                    f"""<div style="padding:0.5rem 1.25rem 0.5rem 2rem;margin-bottom:0.2rem;">
                                        <div style="font-size:0.8rem;font-weight:600;color:#e2e8f0;margin-bottom:0.2rem;">
                                            {title}{"  <code style='font-size:0.75rem;color:#94a3b8;background:rgba(255,255,255,0.06);padding:1px 6px;border-radius:3px;'>" + val_str + "</code>" if val_str else ""}
                                        </div>
                                        <div style="font-size:0.78rem;color:#64748b;line-height:1.55;">{explain}</div>
                                    </div>""",
                                    unsafe_allow_html=True,
                                )
                                matched = True
                                break
                        if not matched and part:
                            st.markdown(
                                f'<div style="padding:0.3rem 1.25rem 0.3rem 2rem;font-size:0.78rem;color:#475569;">{part}</div>',
                                unsafe_allow_html=True,
                            )
            else:
                st.info(f"{selected_name}의 거래 기록이 없습니다. 분석 사이클을 실행하면 거래가 쌓입니다.")

        except Exception as e:
            st.error(f"차트 생성 오류: {e}")

# ═══════════════════════════════════════════════════════════
# 탭 3: 비서실장 & 레짐
# ═══════════════════════════════════════════════════════════
with tabs[2]:
    st.markdown("## 🧠 통합 컨트롤타워 - 비서실장 엔진")

    # 실시간 레짐 분석 버튼
    col_btn, col_info = st.columns([1, 3])
    with col_btn:
        if st.button("🔍 레짐 즉시 분석", use_container_width=True):
            with st.spinner("시장 분석 중..."):
                try:
                    from ChiefOfStaff import ChiefOfStaff
                    cos = ChiefOfStaff(config)
                    sig, alloc, can_trade, reason = cos.run_analysis()
                    st.session_state["live_regime"] = {
                        "signal": sig, "alloc": alloc,
                        "can_trade": can_trade, "reason": reason
                    }
                except Exception as e:
                    st.error(f"분석 오류: {e}")

    # 최신 레짐 표시
    live = st.session_state.get("live_regime")
    if live:
        sig = live["signal"]
        alloc = live["alloc"]
        rc = regime_color(sig.regime.value)

        c1, c2, c3, c4 = st.columns(4)
        with c1:
            st.markdown(
                f"<div style='background:#1a3350;border-left:4px solid {rc};"
                f"border-radius:8px;padding:1rem'>"
                f"<div style='color:#a0aec0;font-size:0.8rem'>현재 레짐</div>"
                f"<div style='color:{rc};font-size:2rem;font-weight:bold'>{sig.regime.value}</div>"
                f"<div style='color:#718096;font-size:0.75rem'>신뢰도 {sig.confidence:.1%}</div>"
                f"</div>",
                unsafe_allow_html=True,
            )
        with c2:
            vix_col = "#fc8181" if sig.vix >= 30 else "#f6ad55" if sig.vix >= 20 else "#68d391"
            vix_hint = (
                "30 이상이면 시장 공포 — 자동으로 방어 모드 전환" if sig.vix >= 30
                else "20~30: 투자자 불안 증가. 조심해야 할 구간" if sig.vix >= 20
                else "20 이하: 비교적 안정적. 정상 투자 가능 구간"
            )
            st.markdown(
                f"<div style='background:#1a3350;border:1px solid #1e4a78;border-radius:8px;padding:1rem'>"
                f"<div style='color:#a0aec0;font-size:0.8rem'>VIX (공포지수)</div>"
                f"<div style='color:{vix_col};font-size:2rem;font-weight:bold'>{sig.vix:.2f}</div>"
                f"<div style='color:#718096;font-size:0.75rem;margin-bottom:0.35rem'>{sig.vix_signal}</div>"
                f"<div style='color:#4a5568;font-size:0.68rem;line-height:1.4'>"
                f"숫자가 높을수록 시장이 겁을 많이 먹은 상태입니다.<br>{vix_hint}."
                f"</div></div>",
                unsafe_allow_html=True,
            )
        with c3:
            ma_col = "#68d391" if sig.ma_alignment == "BULLISH" else "#fc8181" if sig.ma_alignment == "BEARISH" else "#f6ad55"
            ma_label = {"BULLISH": "골든크로스 (상승 배열)", "BEARISH": "데드크로스 (하락 배열)", "MIXED": "혼조 배열"}.get(sig.ma_alignment, sig.ma_alignment)
            ma_hint = {
                "BULLISH": "단기 평균선이 장기 평균선 위로 올라선 상태. 오르는 흐름입니다.",
                "BEARISH": "단기 평균선이 장기 평균선 아래로 내려선 상태. 하락 흐름입니다.",
                "MIXED":   "단기·장기 신호가 엇갈립니다. 방향성 확인 필요.",
            }.get(sig.ma_alignment, "이동평균선 방향 분석 중입니다.")
            st.markdown(
                f"<div style='background:#1a3350;border:1px solid #1e4a78;border-radius:8px;padding:1rem'>"
                f"<div style='color:#a0aec0;font-size:0.8rem'>MA 배열 (이동평균선)</div>"
                f"<div style='color:{ma_col};font-size:1.1rem;font-weight:bold;margin:0.25rem 0 0.15rem'>{ma_label}</div>"
                f"<div style='color:#4a5568;font-size:0.68rem;line-height:1.4'>"
                f"주가의 과거 평균값을 이은 선입니다.<br>{ma_hint}"
                f"</div></div>",
                unsafe_allow_html=True,
            )
        with c4:
            macd_col = "#68d391" if "BULL" in sig.macd_signal else "#fc8181" if "BEAR" in sig.macd_signal else "#f6ad55"
            macd_label = {
                "BULLISH_MOMENTUM": "강한 상승 모멘텀",
                "BEARISH_MOMENTUM": "강한 하락 모멘텀",
                "WEAKENING_BULL":   "상승 힘 약화 중",
                "WEAKENING_BEAR":   "하락 힘 약화 중",
            }.get(sig.macd_signal, sig.macd_signal)
            macd_hint = {
                "BULLISH_MOMENTUM": "오르는 속도가 점점 빨라지고 있습니다. 추세 추종 매수 유리.",
                "BEARISH_MOMENTUM": "내리는 속도가 점점 빨라지고 있습니다. 신규 매수 자제.",
                "WEAKENING_BULL":   "오르던 힘이 줄어들고 있습니다. 추세 전환 가능성 주시.",
                "WEAKENING_BEAR":   "내리던 힘이 줄어들고 있습니다. 반등 가능성 탐색 중.",
            }.get(sig.macd_signal, "주가 변화의 가속도를 나타내는 지표입니다.")
            st.markdown(
                f"<div style='background:#1a3350;border:1px solid #1e4a78;border-radius:8px;padding:1rem'>"
                f"<div style='color:#a0aec0;font-size:0.8rem'>MACD 모멘텀 (추세 가속도)</div>"
                f"<div style='color:{macd_col};font-size:1.1rem;font-weight:bold;margin:0.25rem 0 0.15rem'>{macd_label}</div>"
                f"<div style='color:#4a5568;font-size:0.68rem;line-height:1.4'>"
                f"주가가 오르는지 내리는지 '속도'를 봅니다.<br>{macd_hint}"
                f"</div></div>",
                unsafe_allow_html=True,
            )

        # ── 비서실장 자연어 브리핑 ────────────────────────────────
        try:
            from ChiefOfStaff import get_regime_briefing
            _briefing = get_regime_briefing(
                vix=sig.vix,
                ma_alignment=sig.ma_alignment,
                macd_signal=sig.macd_signal,
                regime=sig.regime.value,
                confidence=sig.confidence,
            )
        except Exception:
            _briefing = sig.notes

        _reg_val = sig.regime.value
        _brief_border = {"공격": "#48bb78", "방어": "#f6ad55", "전시": "#fc8181"}.get(_reg_val, "#0ea5e9")
        _brief_icon   = {"공격": "🟢", "방어": "🟡", "전시": "🚨"}.get(_reg_val, "🔵")

        st.markdown(
            f"<div style='background:linear-gradient(135deg,#1e293b,#162032);"
            f"border-left:5px solid {_brief_border};border-radius:8px;"
            f"padding:1.3rem 1.5rem;margin:0.8rem 0'>"
            f"<div style='color:{_brief_border};font-size:0.8rem;font-weight:700;"
            f"margin-bottom:0.5rem'>{_brief_icon} 비서실장 시황 브리핑</div>"
            f"<div style='color:#e2e8f0;font-size:0.9rem;line-height:1.9'>"
            f"{_briefing.replace(chr(10), '<br>')}</div>"
            f"</div>",
            unsafe_allow_html=True,
        )

        _trade_ok = live["can_trade"]
        if _trade_ok:
            st.success("✅ 거래 가능 — 에이전트 정상 운용 중")
        else:
            st.warning(f"⚠️ 거래 정지 중 — {live['reason']}")

        with st.expander("🔍 기술적 지표 원문 보기"):
            st.code(
                f"VIX        = {sig.vix:.2f}  ({sig.vix_signal})\n"
                f"MA 배열    = {sig.ma_alignment}\n"
                f"MACD       = {sig.macd_signal}\n"
                f"레짐       = {sig.regime.value}  (신뢰도 {sig.confidence:.1%})\n"
                f"분석 노트  = {sig.notes}",
                language="text",
            )

        st.markdown("---")
        st.markdown("### 에이전트 예산 배분")
        alloc_data = {
            "에이전트": ["밸류파인더", "트렌드라이더", "스윙마스터", "현금보유"],
            "배분 비중": [alloc.value_finder, alloc.trend_rider, alloc.swing_master, alloc.cash],
        }
        df_alloc = pd.DataFrame(alloc_data)
        df_alloc["배분 비중"] = df_alloc["배분 비중"].apply(lambda x: f"{x:.0%}")
        col_a, col_b = st.columns([1, 2])
        with col_a:
            st.dataframe(df_alloc, hide_index=True, use_container_width=True)
        with col_b:
            vals = [alloc.value_finder, alloc.trend_rider, alloc.swing_master, alloc.cash]
            labels = ["밸류파인더", "트렌드라이더", "스윙마스터", "현금"]
            colors = ["#00d4ff", "#68d391", "#f6ad55", "#4a5568"]
            fig_alloc = go.Figure(go.Bar(
                x=labels, y=[v * 100 for v in vals],
                marker_color=colors,
                text=[f"{v:.0%}" for v in vals],
                textposition="outside",
            ))
            fig_alloc.update_layout(
                paper_bgcolor="rgba(0,0,0,0)",
                plot_bgcolor="rgba(0,0,0,0)",
                font=dict(color="#e2e8f0"),
                yaxis=dict(ticksuffix="%", gridcolor="#2d3748", range=[0, 60]),
                margin=dict(l=0, r=0, t=10, b=0),
                height=250,
            )
            st.plotly_chart(fig_alloc, use_container_width=True)
    else:
        st.info("왼쪽 버튼을 눌러 시장 레짐을 분석하거나 사이드바에서 사이클을 실행하세요.")

    # ── 레짐 변화 이력 ────────────────────────────────────────
    st.markdown("---")
    st.markdown("### 📋 레짐 변화 이력")

    regime_hist = db.get_regime_history(20)
    if regime_hist:
        try:
            from ChiefOfStaff import get_regime_briefing as _grb
        except ImportError:
            _grb = None

        for _rh_row in regime_hist:
            _rh_regime   = _rh_row.get("regime", "방어")
            _rh_vix      = _rh_row.get("vix", 0)
            _rh_conf     = _rh_row.get("confidence", 0)
            _rh_ma       = _rh_row.get("ma_alignment", "UNKNOWN")
            _rh_macd     = _rh_row.get("macd_signal", "UNKNOWN")
            _rh_ts       = str(_rh_row.get("recorded_at", ""))[:16]
            _rh_notes    = _rh_row.get("notes", "")

            _rh_color = {"공격": "#48bb78", "방어": "#f6ad55", "전시": "#fc8181"}.get(_rh_regime, "#a0aec0")
            _rh_icon  = {"공격": "🟢", "방어": "🟡", "전시": "🚨"}.get(_rh_regime, "⚪")

            if _grb:
                try:
                    _rh_briefing = _grb(_rh_vix, _rh_ma, _rh_macd, _rh_regime, _rh_conf)
                    _brief_short = _rh_briefing.split("\n\n")[0]
                except Exception:
                    _brief_short = _rh_notes or "—"
            else:
                _brief_short = _rh_notes or "—"

            st.markdown(
                f"<div style='background:#1a3350;border-left:3px solid {_rh_color};"
                f"border-radius:6px;padding:0.7rem 1rem;margin:0.3rem 0;"
                f"display:flex;gap:1rem;align-items:flex-start'>"
                f"<div style='min-width:90px;color:#718096;font-size:0.75rem;padding-top:2px'>{_rh_ts}</div>"
                f"<div style='min-width:60px'><span style='background:{_rh_color}20;"
                f"color:{_rh_color};font-size:0.75rem;font-weight:700;"
                f"padding:2px 8px;border-radius:12px'>{_rh_icon} {_rh_regime}</span>"
                f"<div style='color:#718096;font-size:0.7rem;margin-top:3px'>"
                f"VIX {_rh_vix:.1f} · 신뢰도 {_rh_conf:.0%}</div></div>"
                f"<div style='color:#cbd5e0;font-size:0.82rem;line-height:1.6;flex:1'>{_brief_short}</div>"
                f"</div>",
                unsafe_allow_html=True,
            )

            with st.expander(f"🔍 {_rh_ts} 기술적 지표 원문"):
                st.code(
                    f"VIX     = {_rh_vix:.2f}\n"
                    f"MA배열  = {_rh_ma}\n"
                    f"MACD    = {_rh_macd}\n"
                    f"신뢰도  = {_rh_conf:.1%}\n"
                    f"원문    = {_rh_notes}",
                    language="text",
                )
    else:
        st.info("레짐 이력이 없습니다.")

    # ── DQN 강화학습 컨트롤타워 ──────────────────────────────
    st.markdown("---")
    st.markdown("## 🧠 DQN 강화학습 컨트롤타워")
    st.markdown(
        "<p style='color:#718096;font-size:0.9rem;margin-top:-0.5rem'>"
        "비서실장이 에이전트 성과와 시장 지표를 학습하여 스스로 예산 배분을 진화시킵니다.</p>",
        unsafe_allow_html=True,
    )

    if "dqn_chief" not in st.session_state:
        st.session_state.dqn_chief = DQNChief(db_path=str(Path(__file__).parent / "quant_system.db"))
    _dqn: DQNChief = st.session_state.dqn_chief

    # ── 상태 카드 행 ────────────────────────────────────────
    _buf_size  = _dqn.get_buffer_size()
    _dqn_eps   = _dqn.epsilon
    _dqn_step  = _dqn.step_count
    _train_hist = _dqn.get_training_history(limit=50)

    _c1, _c2, _c3, _c4 = st.columns(4)
    with _c1:
        st.markdown(
            f"<div style='background:#1a3350;border:1px solid #1e4a78;border-radius:8px;"
            f"padding:1rem;text-align:center'>"
            f"<div style='color:#718096;font-size:0.75rem'>경험 버퍼</div>"
            f"<div style='color:#0ea5e9;font-size:1.6rem;font-weight:700'>{_buf_size}</div>"
            f"<div style='color:#718096;font-size:0.7rem'>/ 2,000 건</div></div>",
            unsafe_allow_html=True,
        )
    with _c2:
        st.markdown(
            f"<div style='background:#1a3350;border:1px solid #1e4a78;border-radius:8px;"
            f"padding:1rem;text-align:center'>"
            f"<div style='color:#718096;font-size:0.75rem'>탐색률 (ε)</div>"
            f"<div style='color:#f6ad55;font-size:1.6rem;font-weight:700'>{_dqn_eps:.3f}</div>"
            f"<div style='color:#718096;font-size:0.7rem'>1.0 → 0.1 수렴</div></div>",
            unsafe_allow_html=True,
        )
    with _c3:
        st.markdown(
            f"<div style='background:#1a3350;border:1px solid #1e4a78;border-radius:8px;"
            f"padding:1rem;text-align:center'>"
            f"<div style='color:#718096;font-size:0.75rem'>학습 스텝</div>"
            f"<div style='color:#48bb78;font-size:1.6rem;font-weight:700'>{_dqn_step:,}</div>"
            f"<div style='color:#718096;font-size:0.7rem'>누적 배치</div></div>",
            unsafe_allow_html=True,
        )
    with _c4:
        _last_loss = _train_hist[-1]["loss"] if _train_hist else None
        _loss_str  = f"{_last_loss:.4f}" if _last_loss is not None else "—"
        st.markdown(
            f"<div style='background:#1a3350;border:1px solid #1e4a78;border-radius:8px;"
            f"padding:1rem;text-align:center'>"
            f"<div style='color:#718096;font-size:0.75rem'>최근 Loss</div>"
            f"<div style='color:#e53e3e;font-size:1.6rem;font-weight:700'>{_loss_str}</div>"
            f"<div style='color:#718096;font-size:0.7rem'>MSE (낮을수록 好)</div></div>",
            unsafe_allow_html=True,
        )

    st.markdown("<br>", unsafe_allow_html=True)

    # ── 현재 상태 벡터 + Q값 시각화 ────────────────────────
    _col_state, _col_q = st.columns([1, 1])

    with _col_state:
        st.markdown("#### 📊 현재 상태 벡터 (12차원)")

        _pf         = db.get_portfolio(mode=_cur_mode)
        _perf_hist  = db.get_performance_history(mode=_cur_mode, days=30)
        _trades_all = db.get_trades(mode=_cur_mode, limit=200)

        _vf_m = DQNChief.compute_agent_metrics(_trades_all, "value_finder")
        _tr_m = DQNChief.compute_agent_metrics(_trades_all, "trend_rider")
        _sm_m = DQNChief.compute_agent_metrics(_trades_all, "swing_master")

        _pf_ret  = _pf.get("daily_pnl_pct", 0.0) or 0.0
        _pf_mdd  = _perf_hist[-1]["drawdown"] if _perf_hist else 0.0
        _cash_r  = (_pf.get("cash", 0) / max(_pf.get("total_capital", 1), 1))

        _rh_latest = (regime_hist[0] if regime_hist else {}) if "regime_hist" in dir() else db.get_regime_history(1)
        _rh_latest = _rh_latest[0] if isinstance(_rh_latest, list) else (_rh_latest or {})
        _s_vix  = float(_rh_latest.get("vix", 20.0) or 20.0)
        _s_ma   = str(_rh_latest.get("ma_alignment", "UNKNOWN") or "UNKNOWN")
        _s_macd = str(_rh_latest.get("macd_signal", "UNKNOWN") or "UNKNOWN")

        _cur_state = build_state(
            vix=_s_vix, ma_alignment=_s_ma, macd_signal=_s_macd,
            vf_winrate=_vf_m["win_rate"],  vf_sharpe=_vf_m["sharpe"],
            tr_winrate=_tr_m["win_rate"],  tr_sharpe=_tr_m["sharpe"],
            sm_winrate=_sm_m["win_rate"],  sm_sharpe=_sm_m["sharpe"],
            portfolio_daily_return=_pf_ret,
            portfolio_mdd=_pf_mdd,
            cash_ratio=_cash_r,
        )

        _STATE_LABELS = [
            "VIX 정규화", "MA 배열", "MACD 모멘텀",
            "밸류파인더 승률", "밸류파인더 샤프",
            "트렌드라이더 승률", "트렌드라이더 샤프",
            "스윙마스터 승률", "스윙마스터 샤프",
            "일일 수익률", "포트폴리오 MDD", "현금 비율",
        ]
        _state_colors = [
            "#e53e3e" if v < -0.3 else "#48bb78" if v > 0.3 else "#f6ad55"
            for v in _cur_state
        ]

        _fig_state = go.Figure(go.Bar(
            x=_cur_state.tolist(),
            y=_STATE_LABELS,
            orientation="h",
            marker_color=_state_colors,
            text=[f"{v:+.2f}" for v in _cur_state],
            textposition="outside",
        ))
        _fig_state.update_layout(
            plot_bgcolor="#162640", paper_bgcolor="#162640",
            font_color="#cbd5e0", height=340,
            xaxis=dict(range=[-1.1, 1.1], gridcolor="#1e4a78", zeroline=True,
                       zerolinecolor="#4a5568"),
            yaxis=dict(gridcolor="#1e4a78"),
            margin=dict(l=10, r=40, t=10, b=10),
        )
        st.plotly_chart(_fig_state, use_container_width=True, key="dqn_state_chart")

    with _col_q:
        st.markdown("#### 🎯 행동별 Q값 (현재 추천)")
        _q_vals   = _dqn.get_q_values(_cur_state)
        _best_act = int(_q_vals.argmax())
        _act_labels = [a["label"] for a in ACTIONS]
        _q_colors   = [
            "#0ea5e9" if i == _best_act else "#2d4a6a"
            for i in range(N_ACTIONS)
        ]

        _fig_q = go.Figure(go.Bar(
            x=_q_vals.tolist(),
            y=_act_labels,
            orientation="h",
            marker_color=_q_colors,
            text=[f"{v:.3f}" for v in _q_vals],
            textposition="outside",
        ))
        _fig_q.update_layout(
            plot_bgcolor="#162640", paper_bgcolor="#162640",
            font_color="#cbd5e0", height=340,
            xaxis=dict(gridcolor="#1e4a78"),
            yaxis=dict(gridcolor="#1e4a78"),
            margin=dict(l=10, r=50, t=10, b=10),
        )
        st.plotly_chart(_fig_q, use_container_width=True, key="dqn_q_chart")

    # ── DQN 추천 배분 카드 ──────────────────────────────────
    _best_action = ACTIONS[_best_act]
    _q_conf = float((
        (_q_vals[_best_act] - _q_vals.mean()) /
        max(float(_q_vals.std()), 1e-6)
    ))
    _q_conf_label = "매우 확실" if abs(_q_conf) > 1.5 else "보통" if abs(_q_conf) > 0.5 else "탐색 중"

    st.markdown(
        f"<div style='background:linear-gradient(135deg,#0d2137,#1a3a5c);"
        f"border:1px solid #0ea5e9;border-radius:10px;padding:1.2rem 1.5rem;margin:0.5rem 0'>"
        f"<div style='display:flex;justify-content:space-between;align-items:center'>"
        f"<div>"
        f"<div style='color:#718096;font-size:0.8rem;margin-bottom:4px'>🧠 DQN 추천 배분 전략</div>"
        f"<div style='color:#0ea5e9;font-size:1.3rem;font-weight:700'>{_best_action['label']}</div>"
        f"<div style='color:#a0aec0;font-size:0.85rem;margin-top:4px'>{_best_action['desc']}</div>"
        f"</div>"
        f"<div style='text-align:right'>"
        f"<div style='color:#718096;font-size:0.75rem'>Q값 신뢰도</div>"
        f"<div style='color:#48bb78;font-size:1.1rem;font-weight:700'>{_q_conf_label}</div>"
        f"<div style='color:#718096;font-size:0.75rem'>탐색률 ε={_dqn_eps:.3f}</div>"
        f"</div></div>"
        f"<div style='display:flex;gap:1.5rem;margin-top:0.8rem'>"
        f"<div style='text-align:center'><div style='color:#718096;font-size:0.7rem'>밸류파인더</div>"
        f"<div style='color:#00d4ff;font-size:1rem;font-weight:700'>{_best_action['value_finder']:.0%}</div></div>"
        f"<div style='text-align:center'><div style='color:#718096;font-size:0.7rem'>트렌드라이더</div>"
        f"<div style='color:#f6ad55;font-size:1rem;font-weight:700'>{_best_action['trend_rider']:.0%}</div></div>"
        f"<div style='text-align:center'><div style='color:#718096;font-size:0.7rem'>스윙마스터</div>"
        f"<div style='color:#48bb78;font-size:1rem;font-weight:700'>{_best_action['swing_master']:.0%}</div></div>"
        f"<div style='text-align:center'><div style='color:#718096;font-size:0.7rem'>현금</div>"
        f"<div style='color:#a0aec0;font-size:1rem;font-weight:700'>{_best_action['cash']:.0%}</div></div>"
        f"</div></div>",
        unsafe_allow_html=True,
    )

    # ── DQN 학습 실행 버튼 ──────────────────────────────────
    st.markdown("<br>", unsafe_allow_html=True)
    _btn_col1, _btn_col2, _btn_col3 = st.columns([1, 1, 2])

    with _btn_col1:
        if st.button("🔬 DQN 학습 실행", key="dqn_train_btn",
                     help="경험 버퍼에서 무작위 샘플링하여 신경망을 10배치 학습합니다."):
            with st.spinner("신경망 학습 중..."):
                _result = _dqn.train_episode(n_batches=10)
            if _result.get("avg_loss") is not None:
                st.success(f"✅ {_result['msg']}")
            else:
                st.warning(f"⚠️ {_result['msg']}")
            st.rerun()

    with _btn_col2:
        if st.button("💾 DQN 추천 배분 적용", key="dqn_apply_btn",
                     help="DQN이 추천하는 예산 배분을 config.yaml에 즉시 반영합니다."):
            try:
                import yaml
                _cfg_path = Path(__file__).parent / "config.yaml"
                with open(_cfg_path, "r", encoding="utf-8") as _f:
                    _cfg_data = yaml.safe_load(_f)
                _cur_regime = (regime_hist[0].get("regime", "방어") if regime_hist else "방어")
                _regime_key_map = {"공격": "OFFENSIVE", "방어": "DEFENSIVE", "전시": "WARTIME"}
                _rk = _regime_key_map.get(_cur_regime, "DEFENSIVE")
                _cfg_data.setdefault("chief_of_staff", {}).setdefault("regime_allocation", {})
                _cfg_data["chief_of_staff"]["regime_allocation"][_rk] = {
                    "value_finder": _best_action["value_finder"],
                    "trend_rider":  _best_action["trend_rider"],
                    "swing_master": _best_action["swing_master"],
                    "cash":         _best_action["cash"],
                }
                with open(_cfg_path, "w", encoding="utf-8") as _f:
                    yaml.dump(_cfg_data, _f, allow_unicode=True, default_flow_style=False)
                st.success(
                    f"✅ {_cur_regime} 레짐 배분 → {_best_action['label']} 적용 완료!"
                )
            except Exception as _e:
                st.error(f"적용 실패: {_e}")

    # ── 학습 이력 차트 ──────────────────────────────────────
    if _train_hist:
        with st.expander("📈 DQN 학습 이력 보기", expanded=False):
            _df_hist = pd.DataFrame(_train_hist)
            _fig_hist = go.Figure()
            _fig_hist.add_trace(go.Scatter(
                x=_df_hist["episode"], y=_df_hist["loss"],
                mode="lines+markers", name="Loss (MSE)",
                line=dict(color="#e53e3e", width=2),
                marker=dict(size=4),
            ))
            _fig_hist.add_trace(go.Scatter(
                x=_df_hist["episode"], y=_df_hist["avg_reward"],
                mode="lines+markers", name="평균 보상",
                line=dict(color="#48bb78", width=2),
                marker=dict(size=4),
                yaxis="y2",
            ))
            _fig_hist.add_trace(go.Scatter(
                x=_df_hist["episode"], y=_df_hist["epsilon"],
                mode="lines", name="탐색률 ε",
                line=dict(color="#f6ad55", width=1.5, dash="dash"),
                yaxis="y3",
            ))
            _fig_hist.update_layout(
                plot_bgcolor="#162640", paper_bgcolor="#162640",
                font_color="#cbd5e0", height=320,
                xaxis=dict(title="학습 스텝", gridcolor="#1e4a78"),
                yaxis=dict(title="Loss", gridcolor="#1e4a78", side="left"),
                yaxis2=dict(title="보상", overlaying="y", side="right",
                            showgrid=False),
                yaxis3=dict(title="ε", overlaying="y", side="right",
                            anchor="free", position=1.0, showgrid=False),
                legend=dict(bgcolor="#162640", bordercolor="#1e4a78"),
                margin=dict(l=10, r=60, t=20, b=30),
            )
            st.plotly_chart(_fig_hist, use_container_width=True, key="dqn_hist_chart")

            _df_hist_disp = _df_hist[["episode", "loss", "avg_reward", "epsilon", "buffer_size", "trained_at"]].copy()
            _df_hist_disp.columns = ["스텝", "Loss", "평균보상", "탐색률ε", "버퍼크기", "학습시각"]
            st.dataframe(
                _df_hist_disp.sort_values("스텝", ascending=False).head(20),
                use_container_width=True,
                hide_index=True,
            )

    with st.expander("🔬 DQN 작동 원리", expanded=False):
        st.markdown("""
**상태 공간 (12차원 벡터)**
| 지표 | 설명 |
|---|---|
| VIX 정규화 | 시장 공포지수 / 50 (0~1) |
| MA 배열 | BULLISH=1.0, MIXED=0, BEARISH=-1.0 |
| MACD 모멘텀 | 강한상승=1.0 → 강한하락=-1.0 |
| 에이전트 승률×3 | 최근 거래 승률 (0~1) |
| 에이전트 샤프×3 | 수익/변동성 비율 (정규화) |
| 일일 수익률 | 포트폴리오 당일 수익 (정규화) |
| MDD | 최대손실낙폭 (0~1) |
| 현금 비율 | 현금/총자산 |

**보상 함수 (Reward)**
```
reward = daily_return / max(VIX/30, 0.05)  # 변동성 조정 수익
       - 2.0  (손실 한도 초과 시 페널티)
```

**학습 방정식 (Bellman)**
```
Q(s,a) ← r + γ·max Q(s',a')    γ = 0.75 (할인율)
```

**탐색률 감소**: ε × 0.98 (매 학습마다) → 0.1 수렴
        """)


# ═══════════════════════════════════════════════════════════
# 탭 3: 에이전트 현황
# ═══════════════════════════════════════════════════════════
with tabs[3]:
    # ── 에이전트 탭 헤더 ─────────────────────────────────────
    st.markdown("""
    <div style="margin-bottom:2rem;">
      <div style="font-size:0.7rem;font-weight:700;letter-spacing:0.15em;
                  text-transform:uppercase;color:#888888;margin-bottom:0.4rem;">
        Quantitative Strategy Engine
      </div>
      <div style="font-size:1.625rem;font-weight:800;color:#111111;
                  letter-spacing:-0.03em;margin-bottom:0.4rem;">
        3 Tactical Agents
      </div>
      <div style="font-size:0.9375rem;color:#555555;max-width:540px;">
        각 에이전트는 독립적인 알파 팩터를 보유하며 비서실장 레짐 판단에 따라
        병렬 실행됩니다.
      </div>
    </div>
    """, unsafe_allow_html=True)

    # ── 에이전트 파라미터 동적 로딩 ──────────────────────────
    _vf = config["agents"]["value_finder"]
    _tr = config["agents"]["trend_rider"]
    _sm = config["agents"]["swing_master"]

    # ── Card 1: ValueFinder ──────────────────────────────────
    st.markdown(f"""
    <div style="background:#ffffff;border-radius:18px;padding:0;margin-bottom:1.25rem;
                box-shadow:0 2px 12px rgba(0,0,0,0.07);overflow:hidden;">
      <div style="background:#111111;padding:1.25rem 1.75rem;
                  display:flex;align-items:center;gap:1rem;">
        <div style="background:rgba(255,255,255,0.12);border-radius:10px;
                    width:40px;height:40px;display:flex;align-items:center;
                    justify-content:center;font-size:1.25rem;font-weight:800;
                    color:#ffffff;flex-shrink:0;">01</div>
        <div>
          <div style="font-size:1.125rem;font-weight:700;color:#ffffff;
                      letter-spacing:-0.02em;">ValueFinder</div>
          <div style="font-size:0.75rem;color:#aaaaaa;margin-top:1px;">
            밸류파인더 · 장기 · 월 1회 리밸런싱
          </div>
        </div>
        <div style="margin-left:auto;background:rgba(255,255,255,0.1);
                    border-radius:20px;padding:0.3rem 0.875rem;
                    font-size:0.75rem;font-weight:600;color:#dddddd;">
          Magic Formula
        </div>
      </div>
      <div style="padding:1.5rem 1.75rem;">
        <div style="font-size:0.6875rem;font-weight:700;letter-spacing:0.12em;
                    text-transform:uppercase;color:#888888;margin-bottom:0.875rem;">
          Strategy Flow
        </div>
        <div style="display:flex;align-items:center;gap:0.5rem;margin-bottom:1.5rem;
                    flex-wrap:wrap;">
          <div style="background:#f4f4f5;border-radius:8px;padding:0.5rem 0.875rem;
                      font-size:0.8125rem;font-weight:600;color:#111111;">
            EBIT/EV<br><span style="font-size:0.7rem;font-weight:400;color:#666666;">이익수익률</span>
          </div>
          <div style="color:#cccccc;font-size:1.1rem;">→</div>
          <div style="background:#f4f4f5;border-radius:8px;padding:0.5rem 0.875rem;
                      font-size:0.8125rem;font-weight:600;color:#111111;">
            ROIC 상위<br><span style="font-size:0.7rem;font-weight:400;color:#666666;">자본효율</span>
          </div>
          <div style="color:#cccccc;font-size:1.1rem;">→</div>
          <div style="background:#f4f4f5;border-radius:8px;padding:0.5rem 0.875rem;
                      font-size:0.8125rem;font-weight:600;color:#111111;">
            Sortino ≥ {_vf['sortino_min_threshold']}<br><span style="font-size:0.7rem;font-weight:400;color:#666666;">하방변동성 필터</span>
          </div>
          <div style="color:#cccccc;font-size:1.1rem;">→</div>
          <div style="background:#f4f4f5;border-radius:8px;padding:0.5rem 0.875rem;
                      font-size:0.8125rem;font-weight:600;color:#111111;">
            F-Score ≥ {_vf['piotroski_min_score']}<br><span style="font-size:0.7rem;font-weight:400;color:#666666;">재무건전성</span>
          </div>
          <div style="color:#cccccc;font-size:1.1rem;">→</div>
          <div style="background:#111111;border-radius:8px;padding:0.5rem 0.875rem;
                      font-size:0.8125rem;font-weight:700;color:#ffffff;">
            TOP {_vf['top_n_stocks']} 편입<br><span style="font-size:0.7rem;font-weight:400;color:#aaaaaa;">포트폴리오</span>
          </div>
        </div>
        <div style="display:grid;grid-template-columns:repeat(4,1fr);gap:0.75rem;">
          <div style="background:#f9f9fa;border-radius:10px;padding:0.875rem;text-align:center;">
            <div style="font-size:1.25rem;font-weight:800;color:#111111;">{_vf['sortino_min_threshold']}</div>
            <div style="font-size:0.7rem;color:#888888;margin-top:2px;">소르티노 최소</div>
          </div>
          <div style="background:#f9f9fa;border-radius:10px;padding:0.875rem;text-align:center;">
            <div style="font-size:1.25rem;font-weight:800;color:#111111;">{_vf['piotroski_min_score']}/{_vf['piotroski_items']}</div>
            <div style="font-size:0.7rem;color:#888888;margin-top:2px;">F-스코어 기준</div>
          </div>
          <div style="background:#f9f9fa;border-radius:10px;padding:0.875rem;text-align:center;">
            <div style="font-size:1.25rem;font-weight:800;color:#111111;">TOP {_vf['top_n_stocks']}</div>
            <div style="font-size:0.7rem;color:#888888;margin-top:2px;">선정 종목</div>
          </div>
          <div style="background:#f9f9fa;border-radius:10px;padding:0.875rem;text-align:center;">
            <div style="font-size:1.25rem;font-weight:800;color:#111111;">{_vf['rebalance_days']}일</div>
            <div style="font-size:0.7rem;color:#888888;margin-top:2px;">리밸런싱 주기</div>
          </div>
        </div>
        <div style="margin-top:1rem;background:#fffbeb;border:1px solid #fde68a;
                    border-radius:8px;padding:0.625rem 1rem;
                    font-size:0.8125rem;color:#92400e;">
          핵심 규칙 — 소르티노 &lt; {_vf['sortino_min_threshold']} 종목 영구 배제 · Value Trap 사전 차단
        </div>
      </div>
    </div>
    """, unsafe_allow_html=True)

    # ── Card 2: TrendRider ───────────────────────────────────
    _tr_macd = _tr['macd']
    _tr_ma   = _tr['ma_periods']
    st.markdown(f"""
    <div style="background:#ffffff;border-radius:18px;padding:0;margin-bottom:1.25rem;
                box-shadow:0 2px 12px rgba(0,0,0,0.07);overflow:hidden;">
      <div style="background:#2d2d2d;padding:1.25rem 1.75rem;
                  display:flex;align-items:center;gap:1rem;">
        <div style="background:rgba(255,255,255,0.12);border-radius:10px;
                    width:40px;height:40px;display:flex;align-items:center;
                    justify-content:center;font-size:1.25rem;font-weight:800;
                    color:#ffffff;flex-shrink:0;">02</div>
        <div>
          <div style="font-size:1.125rem;font-weight:700;color:#ffffff;
                      letter-spacing:-0.02em;">TrendRider</div>
          <div style="font-size:0.75rem;color:#aaaaaa;margin-top:1px;">
            트렌드라이더 · 중기 · 주 1회 리밸런싱
          </div>
        </div>
        <div style="margin-left:auto;background:rgba(255,255,255,0.1);
                    border-radius:20px;padding:0.3rem 0.875rem;
                    font-size:0.75rem;font-weight:600;color:#dddddd;">
          Golden Cross + MACD
        </div>
      </div>
      <div style="padding:1.5rem 1.75rem;">
        <div style="font-size:0.6875rem;font-weight:700;letter-spacing:0.12em;
                    text-transform:uppercase;color:#888888;margin-bottom:0.875rem;">
          Strategy Flow
        </div>
        <div style="display:flex;align-items:center;gap:0.5rem;margin-bottom:1.5rem;flex-wrap:wrap;">
          <div style="background:#f4f4f5;border-radius:8px;padding:0.5rem 0.875rem;
                      font-size:0.8125rem;font-weight:600;color:#111111;">
            MA{_tr_ma['fast']} / MA{_tr_ma['slow']}<br><span style="font-size:0.7rem;font-weight:400;color:#666666;">이동평균 계산</span>
          </div>
          <div style="color:#cccccc;font-size:1.1rem;">→</div>
          <div style="background:#f4f4f5;border-radius:8px;padding:0.5rem 0.875rem;
                      font-size:0.8125rem;font-weight:600;color:#111111;">
            Golden Cross<br><span style="font-size:0.7rem;font-weight:400;color:#666666;">단기&gt;장기 돌파</span>
          </div>
          <div style="color:#cccccc;font-size:1.1rem;">+</div>
          <div style="background:#f4f4f5;border-radius:8px;padding:0.5rem 0.875rem;
                      font-size:0.8125rem;font-weight:600;color:#111111;">
            MACD {_tr_macd['fast']}/{_tr_macd['slow']}/{_tr_macd['signal']}<br><span style="font-size:0.7rem;font-weight:400;color:#666666;">모멘텀 확인</span>
          </div>
          <div style="color:#cccccc;font-size:1.1rem;">→</div>
          <div style="background:#f4f4f5;border-radius:8px;padding:0.5rem 0.875rem;
                      font-size:0.8125rem;font-weight:600;color:#111111;">
            강도 ≥ {_tr['min_trend_strength']}<br><span style="font-size:0.7rem;font-weight:400;color:#666666;">추세 강도 필터</span>
          </div>
          <div style="color:#cccccc;font-size:1.1rem;">→</div>
          <div style="background:#2d2d2d;border-radius:8px;padding:0.5rem 0.875rem;
                      font-size:0.8125rem;font-weight:700;color:#ffffff;">
            추세 진입<br><span style="font-size:0.7rem;font-weight:400;color:#aaaaaa;">롱 포지션</span>
          </div>
        </div>
        <div style="display:grid;grid-template-columns:repeat(4,1fr);gap:0.75rem;">
          <div style="background:#f9f9fa;border-radius:10px;padding:0.875rem;text-align:center;">
            <div style="font-size:1.25rem;font-weight:800;color:#111111;">MA{_tr_ma['fast']}</div>
            <div style="font-size:0.7rem;color:#888888;margin-top:2px;">단기 이동평균</div>
          </div>
          <div style="background:#f9f9fa;border-radius:10px;padding:0.875rem;text-align:center;">
            <div style="font-size:1.25rem;font-weight:800;color:#111111;">MA{_tr_ma['slow']}</div>
            <div style="font-size:0.7rem;color:#888888;margin-top:2px;">장기 이동평균</div>
          </div>
          <div style="background:#f9f9fa;border-radius:10px;padding:0.875rem;text-align:center;">
            <div style="font-size:1.25rem;font-weight:800;color:#111111;">{_tr_macd['fast']}/{_tr_macd['slow']}/{_tr_macd['signal']}</div>
            <div style="font-size:0.7rem;color:#888888;margin-top:2px;">MACD 파라미터</div>
          </div>
          <div style="background:#f9f9fa;border-radius:10px;padding:0.875rem;text-align:center;">
            <div style="font-size:1.25rem;font-weight:800;color:#111111;">{_tr['min_trend_strength']}</div>
            <div style="font-size:0.7rem;color:#888888;margin-top:2px;">최소 추세 강도</div>
          </div>
        </div>
        <div style="margin-top:1rem;background:#f0fdf4;border:1px solid #bbf7d0;
                    border-radius:8px;padding:0.625rem 1rem;
                    font-size:0.8125rem;color:#166534;">
          핵심 규칙 — 골든크로스 + MACD 상승모멘텀 동시 확인 · 상승 추세 조기 포착
        </div>
      </div>
    </div>
    """, unsafe_allow_html=True)

    # ── Card 3: SwingMaster ──────────────────────────────────
    _bb = _sm['bollinger']
    _rsi = _sm['rsi']
    st.markdown(f"""
    <div style="background:#ffffff;border-radius:18px;padding:0;margin-bottom:1.25rem;
                box-shadow:0 2px 12px rgba(0,0,0,0.07);overflow:hidden;">
      <div style="background:#555555;padding:1.25rem 1.75rem;
                  display:flex;align-items:center;gap:1rem;">
        <div style="background:rgba(255,255,255,0.12);border-radius:10px;
                    width:40px;height:40px;display:flex;align-items:center;
                    justify-content:center;font-size:1.25rem;font-weight:800;
                    color:#ffffff;flex-shrink:0;">03</div>
        <div>
          <div style="font-size:1.125rem;font-weight:700;color:#ffffff;
                      letter-spacing:-0.02em;">SwingMaster</div>
          <div style="font-size:0.75rem;color:#cccccc;margin-top:1px;">
            스윙마스터 · 단기 · 3일 주기
          </div>
        </div>
        <div style="margin-left:auto;background:rgba(255,255,255,0.1);
                    border-radius:20px;padding:0.3rem 0.875rem;
                    font-size:0.75rem;font-weight:600;color:#dddddd;">
          Bollinger + RSI
        </div>
      </div>
      <div style="padding:1.5rem 1.75rem;">
        <div style="font-size:0.6875rem;font-weight:700;letter-spacing:0.12em;
                    text-transform:uppercase;color:#888888;margin-bottom:0.875rem;">
          Strategy Flow
        </div>
        <div style="display:flex;align-items:center;gap:0.5rem;margin-bottom:1.5rem;flex-wrap:wrap;">
          <div style="background:#f4f4f5;border-radius:8px;padding:0.5rem 0.875rem;
                      font-size:0.8125rem;font-weight:600;color:#111111;">
            BB({_bb['period']}, {_bb['std_dev']}σ)<br><span style="font-size:0.7rem;font-weight:400;color:#666666;">볼린저 밴드</span>
          </div>
          <div style="color:#cccccc;font-size:1.1rem;">+</div>
          <div style="background:#f4f4f5;border-radius:8px;padding:0.5rem 0.875rem;
                      font-size:0.8125rem;font-weight:600;color:#111111;">
            RSI ≤ {_rsi['oversold']}<br><span style="font-size:0.7rem;font-weight:400;color:#666666;">과매도 구간</span>
          </div>
          <div style="color:#cccccc;font-size:1.1rem;">→</div>
          <div style="background:#f4f4f5;border-radius:8px;padding:0.5rem 0.875rem;
                      font-size:0.8125rem;font-weight:600;color:#111111;">
            하단 돌파<br><span style="font-size:0.7rem;font-weight:400;color:#666666;">동시 발생 확인</span>
          </div>
          <div style="color:#cccccc;font-size:1.1rem;">→</div>
          <div style="background:#f4f4f5;border-radius:8px;padding:0.5rem 0.875rem;
                      font-size:0.8125rem;font-weight:600;color:#111111;">
            RSI ≥ {_rsi['overbought']}<br><span style="font-size:0.7rem;font-weight:400;color:#666666;">과매수 청산</span>
          </div>
          <div style="color:#cccccc;font-size:1.1rem;">→</div>
          <div style="background:#555555;border-radius:8px;padding:0.5rem 0.875rem;
                      font-size:0.8125rem;font-weight:700;color:#ffffff;">
            역추세 매매<br><span style="font-size:0.7rem;font-weight:400;color:#cccccc;">Mean Reversion</span>
          </div>
        </div>
        <div style="display:grid;grid-template-columns:repeat(5,1fr);gap:0.75rem;">
          <div style="background:#f9f9fa;border-radius:10px;padding:0.875rem;text-align:center;">
            <div style="font-size:1.25rem;font-weight:800;color:#111111;">{_bb['period']}</div>
            <div style="font-size:0.7rem;color:#888888;margin-top:2px;">BB 기간</div>
          </div>
          <div style="background:#f9f9fa;border-radius:10px;padding:0.875rem;text-align:center;">
            <div style="font-size:1.25rem;font-weight:800;color:#111111;">{_bb['std_dev']}σ</div>
            <div style="font-size:0.7rem;color:#888888;margin-top:2px;">표준편차</div>
          </div>
          <div style="background:#f9f9fa;border-radius:10px;padding:0.875rem;text-align:center;">
            <div style="font-size:1.25rem;font-weight:800;color:#111111;">≤{_rsi['oversold']}</div>
            <div style="font-size:0.7rem;color:#888888;margin-top:2px;">RSI 매수</div>
          </div>
          <div style="background:#f9f9fa;border-radius:10px;padding:0.875rem;text-align:center;">
            <div style="font-size:1.25rem;font-weight:800;color:#111111;">≥{_rsi['overbought']}</div>
            <div style="font-size:0.7rem;color:#888888;margin-top:2px;">RSI 청산</div>
          </div>
          <div style="background:#111111;border-radius:10px;padding:0.875rem;text-align:center;">
            <div style="font-size:1.25rem;font-weight:800;color:#ffffff;">{_sm['target_win_rate']:.0%}</div>
            <div style="font-size:0.7rem;color:#aaaaaa;margin-top:2px;">목표 승률</div>
          </div>
        </div>
        <div style="margin-top:1rem;background:#faf5ff;border:1px solid #e9d5ff;
                    border-radius:8px;padding:0.625rem 1rem;
                    font-size:0.8125rem;color:#6b21a8;">
          핵심 규칙 — BB 하단 돌파 + RSI ≤ {_rsi['oversold']} 동시 발생 시만 진입 · 박스권 역추세 매매
        </div>
      </div>
    </div>
    """, unsafe_allow_html=True)

    # ── Card 4: MicroSniper ─────────────────────────────────
    _ms_cfg = config["agents"]["micro_sniper"]
    _ms_adx  = _ms_cfg["adx"]
    _ms_bb   = _ms_cfg["bollinger"]
    _ms_rsi  = _ms_cfg["rsi"]
    _ms_stoch = _ms_cfg["stochastic"]

    # 런타임 스나이퍼 상태 조회
    try:
        from MicroSniper import MicroSniperAgent
        _sniper_agent = st.session_state.get("_sniper_agent_ref")
        if _sniper_agent is None:
            _sniper_agent = MicroSniperAgent(config)
            st.session_state["_sniper_agent_ref"] = _sniper_agent
        _sniper_status = _sniper_agent.get_agent_status()
    except Exception:
        _sniper_status = {
            "halted": False, "total_trades": 0, "wins": 0, "losses": 0,
            "consecutive_losses": 0, "realized_pnl": 0.0, "win_rate": 0.0,
            "halt_reason": "",
        }

    _s_halted = _sniper_status["halted"]
    _s_status_bg  = "#fee2e2" if _s_halted else "#f0fdf4"
    _s_status_clr = "#991b1b" if _s_halted else "#166534"
    _s_status_txt = f"당일 중단 — {_sniper_status['halt_reason']}" if _s_halted else "가동 중"

    st.markdown(f"""
    <div style="background:#ffffff;border-radius:18px;padding:0;margin-bottom:1.25rem;
                box-shadow:0 2px 12px rgba(0,0,0,0.07);overflow:hidden;">
      <div style="background:linear-gradient(135deg,#1a1a2e 0%,#16213e 100%);
                  padding:1.25rem 1.75rem;display:flex;align-items:center;gap:1rem;">
        <div style="background:rgba(255,255,255,0.1);border-radius:10px;
                    width:40px;height:40px;display:flex;align-items:center;
                    justify-content:center;font-size:1.25rem;font-weight:800;
                    color:#ffffff;flex-shrink:0;">04</div>
        <div style="flex:1;">
          <div style="font-size:1.125rem;font-weight:700;color:#ffffff;
                      letter-spacing:-0.02em;">MicroSniper</div>
          <div style="font-size:0.75rem;color:#9999cc;margin-top:1px;">
            마이크로 스나이퍼 · 초단타 스캘핑 · 1분봉 기반
          </div>
        </div>
        <div style="display:flex;gap:0.5rem;align-items:center;">
          <div style="background:rgba(255,255,255,0.1);border-radius:20px;
                      padding:0.3rem 0.875rem;font-size:0.75rem;font-weight:600;color:#ccccee;">
            ADX + BB%B + RSI + Stoch
          </div>
          <div style="background:{_s_status_bg};border-radius:20px;padding:0.3rem 0.875rem;
                      font-size:0.75rem;font-weight:700;color:{_s_status_clr};">
            {_s_status_txt}
          </div>
        </div>
      </div>

      <div style="padding:1.5rem 1.75rem;">
        <div style="font-size:0.6875rem;font-weight:700;letter-spacing:0.12em;
                    text-transform:uppercase;color:#888888;margin-bottom:0.875rem;">
          4-Layer Signal Flow (동시 충족 필수)
        </div>
        <div style="display:flex;align-items:stretch;gap:0.5rem;margin-bottom:1.5rem;flex-wrap:wrap;">
          <div style="background:#f4f4f5;border-radius:8px;padding:0.75rem 0.875rem;
                      font-size:0.8125rem;font-weight:600;color:#111111;min-width:110px;">
            ADX({_ms_adx['period']}) &gt; {_ms_adx['threshold']}<br>
            <span style="font-size:0.7rem;font-weight:400;color:#666666;">추세 강도 필터<br>횡보장 차단</span>
          </div>
          <div style="color:#cccccc;font-size:1.5rem;display:flex;align-items:center;">+</div>
          <div style="background:#f4f4f5;border-radius:8px;padding:0.75rem 0.875rem;
                      font-size:0.8125rem;font-weight:600;color:#111111;min-width:120px;">
            BB%B({_ms_bb['period']}, {_ms_bb['std_dev']}σ) &lt; 0.1<br>
            <span style="font-size:0.7rem;font-weight:400;color:#666666;">볼린저 하단 터치<br>극단 과매도 위치</span>
          </div>
          <div style="color:#cccccc;font-size:1.5rem;display:flex;align-items:center;">+</div>
          <div style="background:#f4f4f5;border-radius:8px;padding:0.75rem 0.875rem;
                      font-size:0.8125rem;font-weight:600;color:#111111;min-width:110px;">
            RSI({_ms_rsi['period']}) &lt; {_ms_rsi['oversold']}<br>
            <span style="font-size:0.7rem;font-weight:400;color:#666666;">타이트 과매도<br>(일반 기준 30보다 강화)</span>
          </div>
          <div style="color:#cccccc;font-size:1.5rem;display:flex;align-items:center;">+</div>
          <div style="background:#f4f4f5;border-radius:8px;padding:0.75rem 0.875rem;
                      font-size:0.8125rem;font-weight:600;color:#111111;min-width:130px;">
            Stoch %K({_ms_stoch['k_period']}) GC %D({_ms_stoch['d_period']})<br>
            <span style="font-size:0.7rem;font-weight:400;color:#666666;">마이크로 골든크로스<br>최종 방아쇠</span>
          </div>
          <div style="color:#cccccc;font-size:1.5rem;display:flex;align-items:center;">→</div>
          <div style="background:linear-gradient(135deg,#1a1a2e,#16213e);border-radius:8px;
                      padding:0.75rem 0.875rem;font-size:0.8125rem;font-weight:700;
                      color:#ffffff;min-width:110px;">
            시장가 즉시 진입<br>
            <span style="font-size:0.7rem;font-weight:400;color:#aaaacc;">Mean Reversion<br>당일 스캘핑</span>
          </div>
        </div>
        <div style="display:grid;grid-template-columns:1fr 1fr;gap:1rem;margin-bottom:1rem;">
          <div>
            <div style="font-size:0.6875rem;font-weight:700;letter-spacing:0.1em;
                        text-transform:uppercase;color:#888888;margin-bottom:0.6rem;">
              Parameters
            </div>
            <div style="display:grid;grid-template-columns:repeat(3,1fr);gap:0.5rem;">
              <div style="background:#f9f9fa;border-radius:10px;padding:0.75rem;text-align:center;">
                <div style="font-size:1.1rem;font-weight:800;color:#111111;">{_ms_adx['period']}/{_ms_adx['threshold']}</div>
                <div style="font-size:0.65rem;color:#888888;margin-top:2px;">ADX 기간/임계값</div>
              </div>
              <div style="background:#f9f9fa;border-radius:10px;padding:0.75rem;text-align:center;">
                <div style="font-size:1.1rem;font-weight:800;color:#111111;">{_ms_bb['period']}</div>
                <div style="font-size:0.65rem;color:#888888;margin-top:2px;">BB 기간</div>
              </div>
              <div style="background:#f9f9fa;border-radius:10px;padding:0.75rem;text-align:center;">
                <div style="font-size:1.1rem;font-weight:800;color:#111111;">{_ms_rsi['period']}</div>
                <div style="font-size:0.65rem;color:#888888;margin-top:2px;">RSI 기간</div>
              </div>
              <div style="background:#f9f9fa;border-radius:10px;padding:0.75rem;text-align:center;">
                <div style="font-size:1.1rem;font-weight:800;color:#111111;">{_ms_rsi['oversold']}/{_ms_rsi['overbought']}</div>
                <div style="font-size:0.65rem;color:#888888;margin-top:2px;">RSI 매수/청산</div>
              </div>
              <div style="background:#f9f9fa;border-radius:10px;padding:0.75rem;text-align:center;">
                <div style="font-size:1.1rem;font-weight:800;color:#111111;">{_ms_stoch['k_period']}/{_ms_stoch['d_period']}</div>
                <div style="font-size:0.65rem;color:#888888;margin-top:2px;">Stoch K/D</div>
              </div>
              <div style="background:#1a1a2e;border-radius:10px;padding:0.75rem;text-align:center;">
                <div style="font-size:1.1rem;font-weight:800;color:#ffffff;">{_ms_cfg['budget_pct']:.0%}</div>
                <div style="font-size:0.65rem;color:#9999cc;margin-top:2px;">특수 예산</div>
              </div>
            </div>
          </div>
          <div>
            <div style="font-size:0.6875rem;font-weight:700;letter-spacing:0.1em;
                        text-transform:uppercase;color:#888888;margin-bottom:0.6rem;">
              Today's Performance
            </div>
            <div style="display:grid;grid-template-columns:repeat(3,1fr);gap:0.5rem;">
              <div style="background:#f9f9fa;border-radius:10px;padding:0.75rem;text-align:center;">
                <div style="font-size:1.1rem;font-weight:800;color:#111111;">{_sniper_status['total_trades']}</div>
                <div style="font-size:0.65rem;color:#888888;margin-top:2px;">총 매매</div>
              </div>
              <div style="background:#f9f9fa;border-radius:10px;padding:0.75rem;text-align:center;">
                <div style="font-size:1.1rem;font-weight:800;color:#166534;">{_sniper_status['wins']}</div>
                <div style="font-size:0.65rem;color:#888888;margin-top:2px;">수익</div>
              </div>
              <div style="background:#f9f9fa;border-radius:10px;padding:0.75rem;text-align:center;">
                <div style="font-size:1.1rem;font-weight:800;color:#991b1b;">{_sniper_status['losses']}</div>
                <div style="font-size:0.65rem;color:#888888;margin-top:2px;">손실</div>
              </div>
              <div style="background:#f9f9fa;border-radius:10px;padding:0.75rem;text-align:center;">
                <div style="font-size:1.1rem;font-weight:800;color:#111111;">{_sniper_status['win_rate']:.0%}</div>
                <div style="font-size:0.65rem;color:#888888;margin-top:2px;">당일 승률</div>
              </div>
              <div style="background:#f9f9fa;border-radius:10px;padding:0.75rem;text-align:center;">
                <div style="font-size:1.1rem;font-weight:800;color:{'#991b1b' if _sniper_status['realized_pnl']<0 else '#166534'};">
                  {_sniper_status['realized_pnl']:+,.0f}</div>
                <div style="font-size:0.65rem;color:#888888;margin-top:2px;">실현 P&L</div>
              </div>
              <div style="background:{'#fee2e2' if _sniper_status['consecutive_losses']>=2 else '#f9f9fa'};
                          border-radius:10px;padding:0.75rem;text-align:center;">
                <div style="font-size:1.1rem;font-weight:800;
                            color:{'#991b1b' if _sniper_status['consecutive_losses']>=2 else '#111111'};">
                  {_sniper_status['consecutive_losses']}/{_ms_cfg['consecutive_loss_limit']}
                </div>
                <div style="font-size:0.65rem;color:#888888;margin-top:2px;">연속손실/한도</div>
              </div>
            </div>
          </div>
        </div>
        <div style="display:grid;grid-template-columns:1fr 1fr;gap:0.75rem;">
          <div style="background:#fff7ed;border:1px solid #fed7aa;border-radius:8px;
                      padding:0.625rem 1rem;font-size:0.8125rem;color:#9a3412;">
            리스크 격리 — 전체 자본의 {_ms_cfg['budget_pct']:.0%}만 운용 ·
            SL {_ms_cfg['stop_loss_pct']:.0%} / TP {_ms_cfg['take_profit_pct']:.0%}
          </div>
          <div style="background:#faf5ff;border:1px solid #e9d5ff;border-radius:8px;
                      padding:0.625rem 1rem;font-size:0.8125rem;color:#6b21a8;">
            워치독 — 연속 {_ms_cfg['consecutive_loss_limit']}회 손실 시 당일 자동 가동 중단 ·
            일 최대 {_ms_cfg['max_daily_trades']}회
          </div>
        </div>
      </div>
    </div>
    """, unsafe_allow_html=True)

    # ══════════════════════════════════════════════════════════
    # 🏆 당일 조기 퇴근 에이전트 알림 + Ground Truth 검증 UI
    # ══════════════════════════════════════════════════════════
    try:
        import json as _ag_json
        from datetime import date as _ag_date
        _ag_today = _ag_date.today().isoformat()
        _ag_logs = db.get_system_logs(limit=300)

        _retire_events: list[dict] = []
        _retire_msgs:   dict[str, str] = {}

        for _agl in _ag_logs:
            _agl_msg = _agl.get("message", "")
            _agl_at  = str(_agl.get("logged_at", ""))[:10]
            if _agl_at != _ag_today:
                continue
            if _agl_msg.startswith("RETIRE_EVENT:"):
                try:
                    _gt = _ag_json.loads(_agl_msg[len("RETIRE_EVENT:"):])
                    _retire_events.append({**_gt, "_logged_at": _agl.get("logged_at", "")})
                except Exception:
                    pass
            elif "🏆" in _agl_msg and "조기 퇴근" in _agl_msg:
                _agt_name = _agl.get("module", "")
                if _agt_name:
                    _retire_msgs[_agt_name] = _agl_msg

        if _retire_events:
            _ag_name_map = {
                "value_finder":  "💎 밸류파인더",
                "trend_rider":   "📈 트렌드라이더",
                "swing_master":  "🎢 스윙마스터",
                "micro_sniper":  "🎯 마이크로스나이퍼",
            }
            st.markdown("---")
            st.markdown("### 🏆 당일 조기 퇴근 에이전트")
            for _ev in _retire_events:
                _ev_agent = _ev.get("에이전트", "")
                _ev_pnl   = float(_ev.get("수익률_pct", 0))
                _ev_tgt   = float(_ev.get("목표_수익률_pct", 0))
                _ev_time  = _ev.get("판정_시각", "")
                _ev_label = _ag_name_map.get(_ev_agent, _ev_agent)
                _ev_msg   = _retire_msgs.get(_ev_agent, f"🏆 {_ev_label} 목표 수익 달성 후 조기 퇴근")

                st.success(
                    f"**{_ev_label}** · {_ev_time} 퇴근 — "
                    f"목표 {_ev_tgt:.1f}% → 실제 달성 **{_ev_pnl:.1f}%** 🎉"
                )
                with st.expander(f"🔍 퇴근 정산 원본 (Ground Truth) 보기 — {_ev_label}"):
                    st.caption(
                        "아래 데이터는 인공지능(LLM) 개입 없이 파이썬 사칙연산으로만 산출된 "
                        "원본 수치입니다. 퇴근 판정의 정확성을 직접 교차 검증할 수 있습니다."
                    )
                    _disp_ev = {k: v for k, v in _ev.items() if not k.startswith("_")}
                    st.json(_disp_ev)
                    _buy  = int(_ev.get("당일_매수_총액", 0))
                    _sell = int(_ev.get("당일_매도_총액", 0))
                    _bgt  = int(_ev.get("배정_예산", 1))
                    _pnl  = _sell - _buy
                    st.code(
                        f"계산 검증:\n"
                        f"  매도 총액   = {_sell:>15,}원\n"
                        f"  매수 총액   = {_buy:>15,}원\n"
                        f"  실현 손익   = {_pnl:>+15,}원\n"
                        f"  배정 예산   = {_bgt:>15,}원\n"
                        f"  수익률      = {_pnl}/{_bgt} = {_pnl/_bgt*100:.4f}%\n"
                        f"  목표 기준   = {_ev_tgt:.4f}%\n"
                        f"  판정 결과   = {'✅ 목표 초과 달성' if _pnl/_bgt*100 >= _ev_tgt else '❌ 미달성'}\n"
                        f"  LLM 개입    = {_ev.get('LLM_개입', False)}",
                        language="text",
                    )
        elif _retire_events == []:
            pass  # 퇴근 에이전트 없으면 조용히 통과
    except Exception:
        pass

    # ── 에이전트별 보유 포지션 현황 ──────────────────────────
    positions = db.get_positions(_cur_mode)
    if positions:
        st.markdown("---")
        st.markdown("### 에이전트별 포지션 현황")
        df_pos = pd.DataFrame(positions)
        agent_summary = df_pos.groupby("agent_name").agg(
            종목수=("ticker", "count"),
            평가액=("market_value", "sum"),
            평가손익=("unrealized_pnl", "sum"),
        ).reset_index()
        agent_summary.rename(columns={"agent_name": "에이전트"}, inplace=True)
        agent_summary["평가액"] = agent_summary["평가액"].apply(lambda x: f"{x:,.0f}")
        agent_summary["평가손익"] = agent_summary["평가손익"].apply(lambda x: f"{x:+,.0f}")
        st.dataframe(agent_summary, hide_index=True, use_container_width=True)


# ═══════════════════════════════════════════════════════════
# 탭 4: 리스크 관리
# ═══════════════════════════════════════════════════════════
with tabs[4]:
    st.markdown("## ⚠️ 4중 리스크 관리 시스템")

    risk_cfg = config["risk_management"]
    cos_cfg = config["chief_of_staff"]

    # 킬스위치 상태
    ks = st.session_state.kill_switch_active
    ks_color = "#fc8181" if ks else "#68d391"
    ks_label = "🔴 발동 중" if ks else "🟢 대기 중"

    st.markdown("### 시스템 방어 상태")
    c1, c2, c3, c4 = st.columns(4)
    with c1:
        st.markdown(
            f"<div style='background:#1a3350;border:1px solid #1e4a78;border-radius:8px;padding:1.2rem;text-align:center'>"
            f"<div style='font-size:1.8rem'>🔴</div>"
            f"<div style='font-size:0.85rem;color:#a0aec0'>킬스위치</div>"
            f"<div style='color:{ks_color};font-weight:bold'>{ks_label}</div>"
            f"</div>",
            unsafe_allow_html=True,
        )
    with c2:
        cb = st.session_state.circuit_breaker
        cb_color = "#fc8181" if cb else "#68d391"
        cb_label = "발동 중" if cb else "정상"
        st.markdown(
            f"<div style='background:#1a3350;border:1px solid #1e4a78;border-radius:8px;padding:1.2rem;text-align:center'>"
            f"<div style='font-size:1.8rem'>⚡</div>"
            f"<div style='font-size:0.85rem;color:#a0aec0'>서킷브레이커</div>"
            f"<div style='color:{cb_color};font-weight:bold'>{cb_label}</div>"
            f"</div>",
            unsafe_allow_html=True,
        )
    with c3:
        st.markdown(
            f"<div style='background:#1a3350;border:1px solid #1e4a78;border-radius:8px;padding:1.2rem;text-align:center'>"
            f"<div style='font-size:1.8rem'>📉</div>"
            f"<div style='font-size:0.85rem;color:#a0aec0'>VIX 트리거</div>"
            f"<div style='color:#f6ad55;font-weight:bold'>≥ {cos_cfg['circuit_breaker']['vix_trigger']}</div>"
            f"</div>",
            unsafe_allow_html=True,
        )
    with c4:
        st.markdown(
            f"<div style='background:#1a3350;border:1px solid #1e4a78;border-radius:8px;padding:1.2rem;text-align:center'>"
            f"<div style='font-size:1.8rem'>🛡️</div>"
            f"<div style='font-size:0.85rem;color:#a0aec0'>일일 최대 손실</div>"
            f"<div style='color:#f6ad55;font-weight:bold'>{cos_cfg['circuit_breaker']['daily_loss_trigger']:.0%}</div>"
            f"</div>",
            unsafe_allow_html=True,
        )

    st.markdown("---")
    st.markdown("### 포지션 리스크 파라미터")

    risk_params = {
        "최대 단일 포지션 비중": f"{risk_cfg['position_max_pct']:.0%}",
        "스탑로스": f"-{risk_cfg['stop_loss_pct']:.0%}",
        "이익실현 목표": f"+{risk_cfg['take_profit_pct']:.0%}",
        "최대 보유 종목 수": risk_cfg["max_positions"],
        "서킷브레이커 쿨다운": f"{risk_cfg['circuit_breaker_cooldown_hours']}시간",
        "수수료율": f"{config['paper_trading']['commission_rate']:.4%}",
        "슬리피지": f"{config['paper_trading']['slippage_pct']:.3%}",
    }

    c_l, c_r = st.columns(2)
    items = list(risk_params.items())
    for i, (k, v) in enumerate(items):
        col = c_l if i % 2 == 0 else c_r
        with col:
            st.markdown(
                f"<div style='background:#1a3350;border:1px solid #1e4a78;border-radius:8px;padding:0.7rem 1rem;"
                f"margin:0.3rem 0;display:flex;justify-content:space-between'>"
                f"<span style='color:#a0aec0'>{k}</span>"
                f"<span style='color:#00d4ff;font-weight:bold'>{v}</span>"
                f"</div>",
                unsafe_allow_html=True,
            )

    st.markdown("---")
    st.markdown("### 레짐별 에이전트 배분 테이블")
    alloc_regimes = config["chief_of_staff"]["regime_allocation"]
    rows = []
    for regime_name, alloc in alloc_regimes.items():
        rows.append({
            "레짐": regime_name,
            "💎 밸류파인더": f"{alloc.get('value_finder', 0):.0%}",
            "📈 트렌드라이더": f"{alloc.get('trend_rider', 0):.0%}",
            "🎢 스윙마스터": f"{alloc.get('swing_master', 0):.0%}",
            "🎯 마이크로스나이퍼": f"{alloc.get('micro_sniper', 0):.0%}",
            "💵 현금보유": f"{alloc.get('cash', 0):.0%}",
        })
    st.dataframe(pd.DataFrame(rows), hide_index=True, use_container_width=True)

    st.markdown("---")
    st.markdown("### VIX 임계값 기준")
    vix_cfg = config["chief_of_staff"]["market_regime"]["vix_thresholds"]
    vix_data = {
        "구간": ["공격 레짐", "방어 레짐", "전시 레짐"],
        "VIX 범위": [
            f"< {vix_cfg['offensive']}",
            f"{vix_cfg['offensive']} ~ {vix_cfg['wartime']}",
            f"≥ {vix_cfg['wartime']} (서킷브레이커 자동 발동)",
        ],
        "거래 상태": ["전면 거래 가능", "보수적 거래", "거래 제한"],
    }
    st.dataframe(pd.DataFrame(vix_data), hide_index=True, use_container_width=True)


# ── 거래 이유 파싱 → 교육용 설명 변환 ─────────────────────────
_SIGNAL_GUIDE = {
    "MA위":           ("📈 이동평균 상향", "단기 이동평균이 장기 이동평균 위에 있습니다. 상승 추세가 유지되고 있다는 신호입니다."),
    "MA아래":         ("📉 이동평균 하향", "단기 이동평균이 장기 이동평균 아래로 내려갔습니다. 하락 추세 신호입니다."),
    "MACD상승모멘텀":  ("🚀 MACD 상승 모멘텀", "MACD 라인이 신호선을 위로 돌파했습니다. 매수 모멘텀이 강화되고 있는 신호입니다."),
    "MACD하락모멘텀":  ("⬇️ MACD 하락 모멘텀", "MACD 라인이 신호선 아래로 떨어졌습니다. 매도 압력이 높아지고 있습니다."),
    "BB하단돌파":      ("🔵 볼린저 밴드 하단 이탈", "주가가 볼린저 밴드 하단선 아래로 내려갔습니다. 통계적으로 과매도 구간으로 반등 가능성이 높습니다."),
    "BB하단근접":      ("🔵 볼린저 밴드 하단 근접", "주가가 볼린저 밴드 하단선에 가까워지고 있습니다. 반등 신호가 형성 중입니다."),
    "BB상단돌파":      ("🔴 볼린저 밴드 상단 이탈", "주가가 볼린저 밴드 상단선 위로 올라갔습니다. 과매수 구간으로 조정 가능성이 있습니다."),
    "RSI과매도":       ("💚 RSI 과매도", "RSI가 30 이하입니다. 단기 낙폭이 과대하여 기술적 반등이 기대되는 구간입니다."),
    "RSI근접과매도":   ("💛 RSI 과매도 근접", "RSI가 30~35 구간입니다. 과매도 진입 직전으로 반등 준비 단계입니다."),
    "RSI과매수":       ("🔴 RSI 과매수(매도 신호)", "RSI가 70 이상입니다. 단기 급등으로 조정 가능성이 높습니다."),
    "마법공식순위":    ("🏆 마법공식 순위", "이익수익률(EY)과 투자자본수익률(ROIC)을 결합한 마법공식 순위입니다. 낮을수록 우량 종목입니다."),
    "F스코어":         ("📊 피오트로스키 F스코어", "9가지 재무 기준으로 기업 건전성을 평가한 점수입니다. 5점 만점 기준이며, 높을수록 재무 상태가 우수합니다."),
    "이익수익률":      ("💰 이익수익률(EY)", "기업의 EBIT을 기업가치(EV)로 나눈 값입니다. 높을수록 저평가된 종목입니다."),
    "ROIC":           ("⚙️ ROIC (투자자본수익률)", "투자한 자본으로 얼마나 이익을 냈는지를 보여주는 지표입니다. 높을수록 자본 효율이 좋은 기업입니다."),
    "목표가":          ("🎯 목표가", "볼린저 밴드 중앙선(20일 이동평균)을 기준으로 계산한 단기 목표 주가입니다."),
    "통과":            ("✅ 통과 기준", "이 종목이 통과한 재무 필터 목록입니다."),
    "스탑로스":        ("🛑 스탑로스 발동", "매입가 대비 손실이 한도(기본 7%)를 초과하여 자동으로 손절매가 실행되었습니다."),
    "이익실현":        ("🏁 이익실현 발동", "매입가 대비 수익이 목표(기본 15%)에 도달하여 자동으로 차익 실현이 실행되었습니다."),
    "비상청산":        ("⚠️ 비상청산", "킬스위치 또는 서킷브레이커가 발동되어 전량 강제 청산되었습니다."),
}

_AGENT_DESC = {
    "value_finder":  ("💎 밸류파인더", "마법공식 + 소르티노 비율 + 피오트로스키 F스코어를 결합하여 재무적으로 저평가된 우량 기업을 발굴합니다."),
    "trend_rider":   ("🏄 트렌드라이더", "이동평균 골든크로스와 MACD 모멘텀을 동시에 확인하여 상승 추세가 형성된 종목을 매수합니다."),
    "swing_master":  ("🎯 스윙마스터", "볼린저 밴드 하단 이탈과 RSI 과매도 구간이 겹칠 때 반등을 노리는 역추세 매매를 실행합니다."),
}

def _parse_reason_to_cards(reason: str, agent: str) -> None:
    """reason 문자열을 파싱해 교육용 설명 카드로 렌더링"""
    parts = [p.strip() for p in reason.split("|") if p.strip()]

    agent_ko, agent_desc = _AGENT_DESC.get(agent, (agent, ""))
    st.markdown(f"**{agent_ko}** — {agent_desc}")
    st.markdown("---")
    st.markdown("**📋 매매 신호 상세 분석**")

    found_any = False
    for part in parts:
        matched = False
        for key, (title, explanation) in _SIGNAL_GUIDE.items():
            if key in part:
                # 괄호 안 수치 추출
                value_str = ""
                if "(" in part and ")" in part:
                    value_str = part[part.index("(")+1:part.index(")")]
                elif "=" in part:
                    value_str = part.split("=", 1)[-1]

                with st.container():
                    col_icon, col_body = st.columns([1, 9])
                    with col_body:
                        if value_str and value_str not in part.replace(key, ""):
                            st.markdown(f"**{title}** `{value_str}`")
                        else:
                            st.markdown(f"**{title}**")
                        st.caption(explanation)
                matched = True
                found_any = True
                break

        if not matched:
            # 매핑 없는 항목은 그대로 표시
            st.markdown(f"- {part}")
            found_any = True

    if not found_any:
        st.info("상세 신호 정보가 없습니다.")


# ═══════════════════════════════════════════════════════════
# 탭 5: 거래 내역
# ═══════════════════════════════════════════════════════════
with tabs[5]:
    st.markdown("## 📜 거래 내역")
    trades = db.get_trades(_cur_mode, limit=100)
    if trades:
        df_trades = pd.DataFrame(trades)
        df_trades["executed_at"] = pd.to_datetime(df_trades["executed_at"]).dt.strftime("%m-%d %H:%M")
        df_trades["price"] = df_trades["price"].apply(lambda x: f"{x:,.2f}")
        df_trades["total_amount"] = df_trades["total_amount"].apply(lambda x: f"{x:,.0f}")
        df_trades["commission"] = df_trades["commission"].apply(lambda x: f"{x:,.0f}")

        df_trades["종목명"] = df_trades["ticker"].apply(ticker_label)
        display = df_trades[["executed_at", "종목명", "agent_name", "action",
                              "quantity", "price", "total_amount", "commission", "regime", "reason"]].rename(columns={
            "executed_at": "시각", "종목명": "종목", "agent_name": "에이전트",
            "action": "매매", "quantity": "수량", "price": "체결가",
            "total_amount": "총액", "commission": "수수료",
            "regime": "레짐", "reason": "사유",
        })
        st.dataframe(display, use_container_width=True, hide_index=True)

        # ── 거래 상세 분석 카드 ──────────────────────────────────
        st.markdown("---")
        st.markdown("### 🔍 거래 상세 분석")
        st.caption("아래에서 거래를 선택하면 AI 에이전트가 왜 이 종목을 선택했는지 자세히 설명합니다.")

        # 선택 레이블: "06-06 16:11 | 삼성전자 매수"
        df_raw = pd.DataFrame(trades)
        df_raw["label"] = (
            pd.to_datetime(df_raw["executed_at"]).dt.strftime("%m-%d %H:%M") + " | "
            + df_raw["ticker"].apply(ticker_label) + " "
            + df_raw["action"].map({"BUY": "매수", "SELL": "매도"}).fillna(df_raw["action"])
        )
        selected_label = st.selectbox(
            "분석할 거래 선택",
            options=df_raw["label"].tolist(),
            index=0,
        )
        selected_idx = df_raw["label"].tolist().index(selected_label)
        sel = df_raw.iloc[selected_idx]

        action_ko = "📗 매수" if sel["action"] == "BUY" else "📕 매도"
        regime_emoji = {"OFFENSIVE": "⚔️", "DEFENSIVE": "🛡️", "WARTIME": "🚨"}.get(sel.get("regime", ""), "")

        col1, col2, col3, col4 = st.columns(4)
        col1.metric("종목", ticker_label(sel["ticker"]))
        col2.metric("매매 유형", action_ko)
        col3.metric("레짐", f"{regime_emoji} {sel.get('regime', '—')}")
        col4.metric("체결가", f"{float(sel['price'].replace(',','')) if isinstance(sel['price'], str) else float(sel['price']):,.0f}원")

        st.markdown("")

        # ── 일반인 맞춤형 매매 설명 (TradeTranslator) ─────────────
        try:
            from TradeTranslator import translate_buy, translate_sell
            _agent  = str(sel.get("agent_name", ""))
            _action = str(sel.get("action", "BUY"))
            _reason = str(sel.get("reason", ""))
            _stock  = ticker_label(str(sel.get("ticker", "")))
            _pnl    = sel.get("realized_pnl", None)
            _pnl_pct = None
            if _pnl and sel.get("total_amount", 0) and float(sel.get("total_amount", 1) or 1) > 0:
                try:
                    _pnl_pct = float(_pnl) / float(sel.get("total_amount", 1)) * 100
                except Exception:
                    pass

            _agent_label = {
                "value_finder": "💎 밸류파인더",
                "trend_rider": "🏄 트렌드라이더",
                "swing_master": "🏓 스윙마스터",
            }.get(_agent, _agent)

            st.markdown(
                f"<div style='background:linear-gradient(135deg,#162640,#1a3350);"
                f"border-left:4px solid #0ea5e9;border-radius:8px;"
                f"padding:1.2rem 1.5rem;margin:0.5rem 0'>"
                f"<div style='color:#0ea5e9;font-size:0.8rem;font-weight:600;margin-bottom:0.6rem'>"
                f"🗣️ {_agent_label} — 일반인 맞춤 설명</div>",
                unsafe_allow_html=True,
            )
            if _action == "BUY":
                buy_reason, sell_cond = translate_buy(_agent, _stock, _reason)
                st.markdown(
                    f"<div style='color:#e2e8f0;line-height:1.8;margin-bottom:0.8rem'>{buy_reason}</div>"
                    f"<div style='background:#0d1e33;border-radius:6px;padding:0.7rem 1rem;"
                    f"color:#a0aec0;font-size:0.85rem'>"
                    f"📌 <b>향후 매도 조건:</b> {sell_cond}</div>"
                    f"</div>",
                    unsafe_allow_html=True,
                )
            else:
                sell_msg = translate_sell(_agent, _stock, _reason, _pnl_pct)
                st.markdown(
                    f"<div style='color:#e2e8f0;line-height:1.8'>{sell_msg}</div>"
                    f"</div>",
                    unsafe_allow_html=True,
                )
        except Exception as _tt_err:
            st.caption(f"번역 로드 실패: {_tt_err}")

        # ── 기술적 신호 상세 (전문가용 접기) ──────────────────────
        with st.expander("전문가 기술적 분석 보기"):
            _parse_reason_to_cards(str(sel.get("reason", "")), str(sel.get("agent_name", "")))

        # ── 에이전트별 거래 통계 ────────────────────────────────
        st.markdown("---")
        st.markdown("### 에이전트별 거래 통계")
        if "agent_name" in df_raw.columns:
            summary = df_raw.groupby(["agent_name", "action"]).size().unstack(fill_value=0).reset_index()
            st.dataframe(summary, hide_index=True, use_container_width=True)
    else:
        st.info("거래 내역이 없습니다. 사이클을 실행하면 거래가 기록됩니다.")


# ═══════════════════════════════════════════════════════════
# 탭 6: 백테스트 결과
# ═══════════════════════════════════════════════════════════
with tabs[6]:
    st.markdown("## 🔬 백테스트 & Out-of-Sample 검증")
    st.markdown("**검증 기간:** IS 2019-2023 (코로나 폭락 포함) | OOS 2024년")

    # 사이드바에서 실행 후 DB에 저장된 결과를 자동으로 불러옴
    bt_db_results = db.get_latest_backtest_results()

    # 세션 상태의 실시간 결과도 병행 확인
    bt_session = st.session_state.get("backtest_results")

    if bt_db_results:
        ran_at = bt_db_results[0].get("ran_at", "")[:16] if bt_db_results else ""
        st.success(f"✅ 최근 백테스트 결과 로드 완료 (실행 시각: {ran_at})")

        # ── 전략 비교 요약 테이블 ────────────────────────────
        summary_rows = []
        for rd in bt_db_results:
            summary_rows.append({
                "전략": rd["strategy_name"],
                "총 수익률": f"{rd['total_return']:.2%}",
                "연환산 수익률": f"{rd['annual_return']:.2%}",
                "샤프": f"{rd['sharpe_ratio']:.3f}",
                "소르티노": f"{rd['sortino_ratio']:.3f}",
                "MDD": f"{rd['max_drawdown']:.2%}",
                "승률": f"{rd['win_rate']:.2%}",
                "알파": f"{rd['alpha']:.2%}",
                "거래수": rd["total_trades"],
            })
        st.markdown("### 전략별 성과 비교")
        st.dataframe(pd.DataFrame(summary_rows), hide_index=True, use_container_width=True)

        st.markdown("---")

        # ── 자본 곡선 통합 차트 ──────────────────────────────
        fig_all = go.Figure()
        colors = {
            "트렌드라이더 IS": "#00d4ff",
            "스윙마스터 IS":   "#68d391",
            "Buy & Hold":      "#f6ad55",
            "트렌드라이더 OOS": "#90cdf4",
            "스윙마스터 OOS":   "#9ae6b4",
        }
        for rd in bt_db_results:
            if rd["equity_dates"] and rd["equity_values"]:
                name = rd["strategy_name"]
                color = next(
                    (v for k, v in colors.items() if k in name),
                    "#a0aec0"
                )
                dash = "dot" if "OOS" in name else "solid"
                fig_all.add_trace(go.Scatter(
                    x=pd.to_datetime(rd["equity_dates"]),
                    y=rd["equity_values"],
                    name=name,
                    line=dict(color=color, width=1.8, dash=dash),
                ))
        fig_all.update_layout(
            title="전략별 자본 곡선 (실선=IS, 점선=OOS)",
            paper_bgcolor="rgba(0,0,0,0)",
            plot_bgcolor="rgba(0,0,0,0)",
            font=dict(color="#e2e8f0"),
            legend=dict(orientation="h", y=1.05),
            xaxis=dict(gridcolor="#2d3748"),
            yaxis=dict(gridcolor="#2d3748", tickformat=","),
            height=380,
            margin=dict(l=0, r=0, t=50, b=0),
        )
        st.plotly_chart(fig_all, use_container_width=True)

        st.markdown("---")

        # ── 전략별 상세 카드 ─────────────────────────────────
        st.markdown("### 전략별 상세 지표")
        for rd in bt_db_results:
            label = rd["strategy_name"]
            is_oos = "OOS" in label
            icon = "🔵" if "트렌드" in label else "🟢" if "스윙" in label else "🟡"
            with st.expander(f"{icon} {label}", expanded=not is_oos):
                c1, c2, c3, c4 = st.columns(4)
                tr_delta = None
                if rd["total_return"] > 0:
                    tr_delta = f"벤치마크 대비 +{rd['alpha']:.2%}"
                with c1:
                    st.metric("총 수익률", f"{rd['total_return']:.2%}", tr_delta)
                    st.metric("연환산 수익률", f"{rd['annual_return']:.2%}")
                with c2:
                    sharpe_delta = "양호" if rd["sharpe_ratio"] > 1.0 else "개선 필요"
                    st.metric("샤프 비율", f"{rd['sharpe_ratio']:.3f}", sharpe_delta)
                    st.metric("소르티노 비율", f"{rd['sortino_ratio']:.3f}")
                with c3:
                    mdd_delta = "안전" if rd["max_drawdown"] > -0.20 else "위험"
                    st.metric("최대 낙폭(MDD)", f"{rd['max_drawdown']:.2%}", mdd_delta,
                              delta_color="inverse")
                    st.metric("승률", f"{rd['win_rate']:.2%}")
                with c4:
                    st.metric("알파(α)", f"{rd['alpha']:.2%}")
                    st.metric("수익 팩터", f"{rd['profit_factor']:.2f}"
                              if rd['profit_factor'] != float('inf') else "∞")

                sc1, sc2, sc3 = st.columns(3)
                with sc1:
                    st.markdown(f"- 총 거래: **{rd['total_trades']}** 건")
                with sc2:
                    st.markdown(f"- 수익/손실: **{rd['winning_trades']}**/**{rd['losing_trades']}**")
                with sc3:
                    st.markdown(f"- 평균수익/손실: **{rd['avg_win']:.2%}** / **{rd['avg_loss']:.2%}**")

    elif bt_session:
        # 세션에만 있는 경우 (이전 방식 호환)
        st.info("세션 결과 표시 중 (페이지 새로고침 시 사라집니다)")
        for name, report in bt_session.items():
            rd = report.to_dict()
            with st.expander(rd['strategy_name'], expanded=True):
                c1, c2, c3, c4 = st.columns(4)
                with c1:
                    st.metric("총 수익률", f"{rd['total_return']:.2%}")
                    st.metric("연환산 수익률", f"{rd['annual_return']:.2%}")
                with c2:
                    st.metric("샤프 비율", f"{rd['sharpe_ratio']:.3f}")
                    st.metric("소르티노 비율", f"{rd['sortino_ratio']:.3f}")
                with c3:
                    st.metric("최대 낙폭 (MDD)", f"{rd['max_drawdown']:.2%}")
                    st.metric("승률", f"{rd['win_rate']:.2%}")
                with c4:
                    st.metric("알파 (vs 벤치마크)", f"{rd['alpha']:.2%}")
                    st.metric("수익 팩터", f"{rd['profit_factor']:.2f}")
    else:
        st.info("백테스트 결과가 없습니다. 사이드바의 '📊 백테스트 실행' 버튼을 누르거나 터미널에서 실행하세요.")
        st.code("cd quant-system && python SimulationEngine.py", language="bash")

        # 전략 기대치 요약
        st.markdown("### 전략 기대 성과 (설정값 기준)")
        sample_data = {
            "전략": ["밸류파인더", "트렌드라이더", "스윙마스터", "통합 포트폴리오"],
            "예상 연수익률": ["12~18%", "10~15%", "15~25%", "13~20%"],
            "최대 낙폭": ["< 20%", "< 15%", "< 10%", "< 12%"],
            "목표 승률": ["-", "55~65%", "87.5%", "60~70%"],
            "리밸런싱": ["월 1회", "주 1회", "3일", "레짐 변화 시"],
        }
        st.dataframe(pd.DataFrame(sample_data), hide_index=True, use_container_width=True)


# ═══════════════════════════════════════════════════════════
# 탭 7: 시스템 로그
# ═══════════════════════════════════════════════════════════
with tabs[7]:
    st.markdown("## 📝 시스템 로그")

    logs = db.get_system_logs(200)
    if logs:
        df_logs = pd.DataFrame(logs)
        df_logs["logged_at"] = pd.to_datetime(df_logs["logged_at"]).dt.strftime("%m-%d %H:%M:%S")

        level_filter = st.multiselect(
            "로그 레벨 필터",
            options=["CRITICAL", "ERROR", "WARNING", "INFO"],
            default=["CRITICAL", "ERROR", "WARNING", "INFO"],
        )
        df_filtered = df_logs[df_logs["level"].isin(level_filter)]

        def color_level(val):
            colors = {
                "CRITICAL": "background-color: #742a2a; color: #fed7d7",
                "ERROR": "background-color: #63171b; color: #feb2b2",
                "WARNING": "background-color: #744210; color: #fefcbf",
                "INFO": "",
            }
            return colors.get(val, "")

        display = df_filtered[["logged_at", "level", "module", "message"]].rename(columns={
            "logged_at": "시각", "level": "레벨", "module": "모듈", "message": "메시지"
        })
        st.dataframe(display, use_container_width=True, hide_index=True)
    else:
        st.info("시스템 로그가 없습니다.")

    # 로그 초기화
    if st.button("🗑️ 로그 초기화"):
        import sqlite3
        with sqlite3.connect(config["system"]["db_path"]) as conn:
            conn.execute("DELETE FROM system_log")
        st.success("로그 초기화 완료")
        st.rerun()

# ═══════════════════════════════════════════════════════════
# 탭 8: 관리자 제어판
# ═══════════════════════════════════════════════════════════
with tabs[8]:
    from config_loader import save_config

    # ── 헬퍼: 비서실장 브리핑 텍스트 생성 ───────────────────
    def _make_briefing(r: dict) -> str:
        vix   = r.get("vix", 0)
        ma    = r.get("ma_alignment", "UNKNOWN")
        macd  = r.get("macd_signal", "UNKNOWN")
        regime = r.get("regime", "방어")
        conf   = r.get("confidence", 0)

        ma_kor  = {"BULLISH": "골든크로스(상승 배열)", "BEARISH": "데드크로스(하락 배열)",
                   "MIXED": "혼조세", "UNKNOWN": "데이터 부족", "INSUFFICIENT_DATA": "데이터 부족"}.get(ma, ma)
        macd_kor = {"BULLISH_MOMENTUM": "상승 모멘텀 강화", "BEARISH_MOMENTUM": "하락 모멘텀 강화",
                    "WEAKENING_BULL": "상승 모멘텀 약화", "WEAKENING_BEAR": "하락 모멘텀 약화",
                    "UNKNOWN": "분석 중"}.get(macd, macd)

        if regime == "전시":
            action = f"VIX가 {vix:.1f}로 공포 구간에 진입했습니다. 현금 80% 확보를 최우선으로 하고, 스윙마스터 10% 이하 최소 운용을 권고합니다. 신규 매수를 즉시 중단하세요."
        elif regime == "방어":
            action = f"VIX {vix:.1f}로 경계 구간입니다. 현금 30%를 유지하며 가치주 위주의 소극적 운용을 권장합니다. 트렌드라이더 비중을 축소하세요."
        else:
            action = f"VIX {vix:.1f}로 안정적 구간입니다. 공격적 운용이 가능합니다. 트렌드라이더·밸류파인더 비중을 높여 수익을 극대화하세요."

        return (
            f"현재 VIX는 **{vix:.1f}**이며, S&P500 지수는 **{ma_kor}** 상태입니다. "
            f"MACD는 **{macd_kor}** 신호를 보내고 있습니다.\n\n"
            f"종합 판단: **{regime} 레짐** (신뢰도 {conf:.0%})\n\n"
            f"💡 {action}"
        )

    # ── 헬퍼: 레짐별 권장 배분 ───────────────────────────────
    def _recommended_alloc(regime: str) -> dict:
        return config["chief_of_staff"]["regime_allocation"].get(
            {"공격": "OFFENSIVE", "방어": "DEFENSIVE", "전시": "WARTIME"}.get(regime, "DEFENSIVE"),
            {"value_finder": 0.3, "trend_rider": 0.2, "swing_master": 0.2, "cash": 0.3},
        )

    # ══════════════════════════════════════════════════════
    # 0. 🎯 목표 기대수익률 설정 & 자동 예산 재분배
    # ══════════════════════════════════════════════════════
    st.markdown("## 🎯 목표 기대수익률 설정")
    st.caption("원하는 연간 수익률을 선택하면 비서실장이 현재 시장 상황에 맞춰 에이전트 예산을 자동으로 재분배합니다.")

    try:
        from TradeTranslator import recommend_allocation_for_target

        _rh = db.get_regime_history(limit=1)
        _cur_regime = _rh[0].get("regime", "방어") if _rh else "방어"
        _cur_vix    = _rh[0].get("vix", 20.0) if _rh else 20.0

        target_return = st.slider(
            "연간 목표 기대수익률 (%)",
            min_value=5, max_value=50, value=15, step=1,
            format="%d%%",
            help="낮을수록 안전, 높을수록 리스크 증가",
        )

        alloc_prop, chief_advice, tier = recommend_allocation_for_target(
            target_return, _cur_regime, _cur_vix
        )

        tier_colors = {
            "안정": "#48bb78", "균형": "#0ea5e9",
            "공격": "#f6ad55", "초공격": "#fc8181", "전시": "#fc8181",
        }
        tier_color = tier_colors.get(tier, "#a0aec0")

        col_t1, col_t2 = st.columns([2, 3])
        with col_t1:
            st.markdown(
                f"<div style='background:#1a3350;border-radius:8px;padding:1rem 1.2rem;"
                f"border-left:4px solid {tier_color}'>"
                f"<div style='color:{tier_color};font-size:0.75rem;font-weight:700;margin-bottom:0.4rem'>"
                f"목표 수익률 유형</div>"
                f"<div style='font-size:1.6rem;font-weight:800;color:#e2e8f0'>"
                f"연 {target_return}%</div>"
                f"<div style='color:{tier_color};font-size:0.85rem;font-weight:600;margin-top:0.2rem'>"
                f"{tier}형 투자</div>"
                f"<div style='color:#718096;font-size:0.75rem;margin-top:0.6rem'>"
                f"현재 레짐: {_cur_regime} | VIX {_cur_vix:.1f}</div>"
                f"</div>",
                unsafe_allow_html=True,
            )

        with col_t2:
            st.markdown(
                f"<div style='background:linear-gradient(135deg,#1e293b,#162032);"
                f"border-radius:8px;padding:1rem 1.2rem;"
                f"border-left:4px solid {tier_color};height:100%'>"
                f"<div style='color:{tier_color};font-size:0.75rem;font-weight:700;margin-bottom:0.4rem'>"
                f"👨‍💼 비서실장 조언</div>"
                f"<div style='color:#e2e8f0;font-size:0.85rem;line-height:1.7'>"
                f"{chief_advice.replace(chr(10), '<br>')}</div>"
                f"</div>",
                unsafe_allow_html=True,
            )

        st.markdown("#### 📊 제안 예산 배분")
        _labels = {
            "value_finder":  "💎 밸류파인더",
            "trend_rider":   "📈 트렌드라이더",
            "swing_master":  "🎢 스윙마스터",
            "micro_sniper":  "🎯 마이크로스나이퍼",
            "cash":          "💵 현금 보유",
        }
        _bar_colors = {
            "value_finder": "#48bb78", "trend_rider": "#0ea5e9",
            "swing_master": "#f6ad55", "micro_sniper": "#b794f4",
            "cash": "#718096",
        }
        _alloc_keys = [k for k in ["value_finder","trend_rider","swing_master","micro_sniper","cash"] if k in alloc_prop]
        alloc_cols = st.columns(len(_alloc_keys))
        for i, key in enumerate(_alloc_keys):
            val = alloc_prop.get(key, 0)
            with alloc_cols[i]:
                pct = int(round(val * 100))
                bc  = _bar_colors.get(key, "#a0aec0")
                st.markdown(
                    f"<div style='background:#1a3350;border-radius:8px;padding:0.8rem;text-align:center'>"
                    f"<div style='color:#a0aec0;font-size:0.72rem;margin-bottom:0.3rem'>{_labels.get(key, key)}</div>"
                    f"<div style='font-size:1.5rem;font-weight:800;color:{bc}'>{pct}%</div>"
                    f"<div style='background:#0d1e33;border-radius:4px;margin-top:0.4rem;height:6px'>"
                    f"<div style='background:{bc};width:{pct}%;height:6px;border-radius:4px'></div>"
                    f"</div></div>",
                    unsafe_allow_html=True,
                )

        st.markdown("")
        col_btn1, col_btn2 = st.columns([1, 4])
        with col_btn1:
            do_apply = st.button("✅ 이 전략으로 재분배 실행", type="primary", use_container_width=True)
        with col_btn2:
            st.caption("적용 시 config.yaml의 에이전트 예산 비중이 즉시 변경됩니다.")

        if do_apply:
            try:
                config["chief_of_staff"]["regime_allocation"]["OFFENSIVE"] = {
                    "value_finder": round(alloc_prop["value_finder"], 3),
                    "trend_rider":  round(alloc_prop["trend_rider"], 3),
                    "swing_master": round(alloc_prop["swing_master"], 3),
                    "cash":         round(alloc_prop["cash"], 3),
                }
                config["chief_of_staff"]["regime_allocation"]["DEFENSIVE"] = {
                    "value_finder": round(min(alloc_prop["value_finder"] + 0.10, 0.60), 3),
                    "trend_rider":  round(max(alloc_prop["trend_rider"] - 0.10, 0.05), 3),
                    "swing_master": round(alloc_prop["swing_master"], 3),
                    "cash":         round(min(alloc_prop["cash"] + 0.05, 0.40), 3),
                }
                if tier in ("공격", "초공격"):
                    config["chief_of_staff"]["vix_thresholds"]["wartime"] = 35
                    config["chief_of_staff"]["vix_thresholds"]["defensive"] = 25
                else:
                    config["chief_of_staff"]["vix_thresholds"]["wartime"] = 30
                    config["chief_of_staff"]["vix_thresholds"]["defensive"] = 20
                save_config(config)
                st.success(
                    f"✅ 재분배 완료! {tier}형({target_return}%) 전략이 적용되었습니다. "
                    f"다음 분석 사이클부터 새 배분이 반영됩니다."
                )
            except Exception as _e:
                st.error(f"재분배 저장 실패: {_e}")

    except ImportError:
        st.warning("TradeTranslator 모듈을 불러올 수 없습니다.")

    st.markdown("---")

    st.markdown("## 🛠️ 관리자 제어판")
    st.caption("파라미터를 조정하고 저장하면 config.yaml에 즉시 반영되어 전체 시스템에 적용됩니다.")

    # ══════════════════════════════════════════════════════
    # 1. 비서실장 브리핑 창
    # ══════════════════════════════════════════════════════
    st.markdown("### 👨‍💼 비서실장 브리핑 창")
    regime_history = db.get_regime_history(limit=1)
    if regime_history:
        latest = regime_history[0]
        r_name = latest.get("regime", "방어")
        r_color = {"공격": "#00d4ff", "방어": "#f6ad55", "전시": "#fc8181"}.get(r_name, "#a0aec0")
        r_ts = latest.get("recorded_at", "")[:16]

        col_r1, col_r2, col_r3, col_r4 = st.columns(4)
        with col_r1:
            st.metric("현재 레짐", r_name)
        with col_r2:
            st.metric("VIX", f"{latest.get('vix', 0):.1f}")
        with col_r3:
            ma_short = {"BULLISH": "골든크로스↑", "BEARISH": "데드크로스↓", "MIXED": "혼조", "UNKNOWN": "—"}.get(
                latest.get("ma_alignment", "UNKNOWN"), "—")
            st.metric("이동평균 배열", ma_short)
        with col_r4:
            macd_short = {"BULLISH_MOMENTUM": "강한 상승↑", "BEARISH_MOMENTUM": "강한 하락↓",
                          "WEAKENING_BULL": "모멘텀 약화", "WEAKENING_BEAR": "반등 시도"}.get(
                latest.get("macd_signal", ""), "분석 중")
            st.metric("MACD", macd_short)

        briefing_text = _make_briefing(latest)
        st.markdown(
            f"<div style='background:linear-gradient(135deg,#1e293b,#162032);"
            f"border-left:4px solid {r_color};border-radius:8px;"
            f"padding:1.2rem 1.5rem;margin:0.5rem 0'>"
            f"<div style='color:#a0aec0;font-size:0.75rem;margin-bottom:0.5rem'>"
            f"마지막 분석: {r_ts}</div>"
            f"<div style='color:#e2e8f0;line-height:1.8'>{briefing_text.replace(chr(10), '<br>')}</div>"
            f"</div>",
            unsafe_allow_html=True,
        )
    else:
        st.info("아직 레짐 분석 데이터가 없습니다. 사이드바에서 '분석 사이클 1회 실행'을 먼저 실행하세요.")
        latest = {}

    st.markdown("---")

    # ══════════════════════════════════════════════════════
    # 2. 제어 권한 선택
    # ══════════════════════════════════════════════════════
    st.markdown("### 🎛️ 제어 권한 선택")
    ctrl_mode = st.radio(
        "운용 모드를 선택하세요",
        ["🤖 비서실장 권고안 자동 적용", "🛠️ 대표님 수동 조정 (Manual)"],
        horizontal=True,
        key="admin_ctrl_mode",
    )
    manual = ctrl_mode == "🛠️ 대표님 수동 조정 (Manual)"

    if manual:
        st.success("✅ 수동 조정 모드 — 슬라이더를 자유롭게 조작할 수 있습니다.")
    else:
        st.info("🔒 자동 모드 — 비서실장 권고값으로 잠겨 있습니다. 수정하려면 수동 조정으로 전환하세요.")

    st.markdown("---")

    # 현재 config 로컬 사본 (이 페이지 렌더링 중에만 사용)
    cfg = config  # 저장 시 직접 수정 후 save_config 호출

    # ══════════════════════════════════════════════════════
    # 3. 파라미터 섹션 4개
    # ══════════════════════════════════════════════════════

    # ── Section A: 비서실장 매크로 ────────────────────────
    with st.expander("비서실장 매크로 설정 (VIX 임계값·추세 필터)", expanded=True):

        st.info(
            "**📖 이 섹션이 하는 일**\n\n"
            "비서실장이 '지금 시장이 위험한가 안전한가'를 판단하는 기준선을 설정합니다.\n\n"
            "**VIX**는 '시장 공포 온도계'입니다. 숫자가 높을수록 투자자들이 겁을 많이 먹고 있다는 뜻입니다. "
            "평상시는 15–20, 조정장은 25–30, 대폭락장(코로나·금융위기)은 40–80까지 올라갑니다.\n\n"
            "VIX 수치에 따라 시스템이 세 가지 모드로 바뀝니다:\n"
            "- 🟦 **공격 모드**: VIX가 낮음 → 주식 비중 최대, 적극 매수\n"
            "- 🟨 **방어 모드**: VIX가 경계값 이상 → 현금 30% 확보, 보수적 운용\n"
            "- 🟥 **전시 모드**: VIX가 패닉값 이상 → 현금 80% 확보, 매수 중단"
        )

        vix_cfg = cfg["chief_of_staff"]["market_regime"]["vix_thresholds"]
        cur_def  = vix_cfg.get("defensive", 20)
        cur_war  = vix_cfg.get("wartime",  30)
        cur_filter = cfg["chief_of_staff"]["market_regime"].get("use_ma_trend_filter", True)

        col_a1, col_a2, col_a3 = st.columns(3)
        with col_a1:
            new_def = st.slider(
                "⚠️ VIX 경계 임계값",
                min_value=10, max_value=45, value=int(cur_def), step=1,
                disabled=not manual, key="sl_vix_def",
                help=(
                    "VIX가 이 숫자 이상이 되면 '방어 모드'로 전환됩니다.\n\n"
                    "기본값 20 의미: VIX가 20을 넘으면 시장이 불안하다고 판단, 현금을 30% 확보합니다.\n\n"
                    "▶ 높이면: 더 많이 불안해야 방어 모드가 켜짐 → 공격적 운용 시간이 길어짐\n"
                    "▶ 낮추면: 조금만 불안해도 방어 모드로 전환 → 더 보수적으로 운용"
                )
            )
        with col_a2:
            new_war = st.slider(
                "🚨 VIX 패닉 임계값",
                min_value=20, max_value=60, value=int(cur_war), step=1,
                disabled=not manual, key="sl_vix_war",
                help=(
                    "VIX가 이 숫자 이상이면 '전시 모드(공포 구간)'로 강제 전환됩니다.\n\n"
                    "기본값 30 의미: VIX 30 이상이면 코로나·금융위기 수준의 공포 상태로 판단, "
                    "현금 80%로 대피하고 신규 매수를 중단합니다.\n\n"
                    "▶ 높이면: 극단적 상황에만 전시 모드 → 하락장에서도 더 오래 버팀\n"
                    "▶ 낮추면: 조금만 흔들려도 전시 모드 → 손실 방어는 강하지만 수익 기회도 줄어듦"
                )
            )
        with col_a3:
            new_filter = st.toggle(
                "📈 주가 추세 필터 사용",
                value=cur_filter,
                disabled=not manual,
                key="tgl_ma_filter",
                help=(
                    "S&P500(미국 대표 지수) 주가 흐름을 VIX와 함께 참고할지 여부입니다.\n\n"
                    "ON(권장): VIX + 주가 추세 두 가지를 모두 보고 레짐을 결정 → 더 정확\n"
                    "OFF: VIX 수치만 보고 결정 → 단순하지만 오판 가능성 있음"
                )
            )

        st.markdown("---")
        st.markdown(
            "**💰 상황별 투자 예산 배분**\n\n"
            "시장 상황(레짐)에 따라 세 가지 투자 전략에 자금을 얼마씩 나눌지 설정합니다. "
            "네 항목의 합이 100%가 되도록 맞추세요."
        )
        alloc_cfg = cfg["chief_of_staff"]["regime_allocation"]
        regime_help = {
            "OFFENSIVE": "시장이 안정적일 때의 배분 — 수익을 최대한 추구합니다",
            "DEFENSIVE": "시장이 불안할 때의 배분 — 손실을 줄이며 보수적으로 운용합니다",
            "WARTIME":   "시장이 공포 상태일 때의 배분 — 거의 현금으로 대피합니다",
        }
        for regime_key, label in [("OFFENSIVE", "🟦 공격 레짐 (VIX 안정)"), ("DEFENSIVE", "🟨 방어 레짐 (VIX 경계)"), ("WARTIME", "🟥 전시 레짐 (VIX 패닉)")]:
            st.caption(f"{label} — {regime_help[regime_key]}")
            a = alloc_cfg[regime_key]
            c1, c2, c3, c4, c5 = st.columns(5)
            with c1:
                alloc_cfg[regime_key]["value_finder"] = st.slider(
                    "💎 가치주 발굴", 0, 100,
                    int(a.get("value_finder", 0) * 100), 5,
                    disabled=not manual, key=f"sl_{regime_key}_vf",
                    format="%d%%",
                    help="저평가된 우량 기업 주식에 투자하는 비중"
                ) / 100
            with c2:
                alloc_cfg[regime_key]["trend_rider"] = st.slider(
                    "📈 추세 추종", 0, 100,
                    int(a.get("trend_rider", 0) * 100), 5,
                    disabled=not manual, key=f"sl_{regime_key}_tr",
                    format="%d%%",
                    help="오르는 주식을 따라 사는 추세 전략 비중"
                ) / 100
            with c3:
                alloc_cfg[regime_key]["swing_master"] = st.slider(
                    "🎢 단기 반등", 0, 100,
                    int(a.get("swing_master", 0) * 100), 5,
                    disabled=not manual, key=f"sl_{regime_key}_sm",
                    format="%d%%",
                    help="많이 떨어진 주식의 단기 반등을 노리는 전략 비중"
                ) / 100
            with c4:
                alloc_cfg[regime_key]["micro_sniper"] = st.slider(
                    "🎯 초단타 스나이퍼", 0, 100,
                    int(a.get("micro_sniper", 0) * 100), 5,
                    disabled=not manual, key=f"sl_{regime_key}_ms",
                    format="%d%%",
                    help="1분봉 기반 초단타 스캘핑 전략 비중. 공격 레짐에서만 활성화 권장"
                ) / 100
            with c5:
                alloc_cfg[regime_key]["cash"] = st.slider(
                    "💵 현금 보유", 0, 100,
                    int(a.get("cash", 0) * 100), 5,
                    disabled=not manual, key=f"sl_{regime_key}_cash",
                    format="%d%%",
                    help="투자하지 않고 현금으로 보유하는 비중. 높을수록 안전하지만 수익도 줄어듦"
                ) / 100

    # ── Section B: 밸류파인더 ─────────────────────────────
    with st.expander("밸류파인더 (가치투자) 설정", expanded=False):

        st.info(
            "**📖 이 섹션이 하는 일**\n\n"
            "밸류파인더는 '저평가된 우량 기업'을 골라내는 가치투자 전략입니다. "
            "워런 버핏이 하는 방식처럼, 실적이 좋은데 주가가 싼 기업을 찾아 장기 보유합니다.\n\n"
            "아래 필터 기준을 통과한 기업만 매수 대상이 됩니다. "
            "기준을 **엄격하게** 설정할수록 선발되는 종목 수가 줄고, "
            "**느슨하게** 설정할수록 더 많은 종목이 포함되어 분산 투자됩니다."
        )

        vf_cfg = cfg["agents"]["value_finder"]
        col_b1, col_b2 = st.columns(2)
        with col_b1:
            new_roa = st.slider(
                "📈 ROA 최솟값 (자산 대비 이익률)",
                0, 40,
                int(vf_cfg.get("roa_min_threshold", 0.15) * 100), 1,
                disabled=not manual, key="sl_roa",
                help=(
                    "ROA = 회사가 가진 자산 대비 얼마나 이익을 냈는지 (Return on Assets)\n\n"
                    "예: ROA 15% = 100억 자산으로 15억 순이익을 냈다는 뜻\n\n"
                    "▶ 높이면: 더 알짜배기 기업만 선발 → 종목 수 감소, 질적 향상\n"
                    "▶ 낮추면: 더 많은 기업 포함 → 종목 수 증가, 분산 투자 강화"
                )
            )
            new_sortino = st.slider(
                "📊 소르티노 지수 최솟값 (손실 위험 대비 수익)",
                0.0, 2.0,
                float(vf_cfg.get("sortino_min_threshold", 0.2)), 0.05,
                disabled=not manual, key="sl_sortino",
                help=(
                    "소르티노 지수 = 손실 위험 대비 얼마나 수익을 냈는지를 나타내는 지표\n\n"
                    "0.2 미만이면 '손실 위험에 비해 수익이 너무 낮다'고 판단해 영구 제외합니다.\n\n"
                    "▶ 높이면: 더 좋은 위험-수익 비율의 종목만 허용 → 더 까다로운 필터\n"
                    "▶ 낮추면: 웬만한 종목은 통과 → 더 많은 종목 허용"
                )
            )
        with col_b2:
            new_per = st.slider(
                "💰 PER 최솟값 (주가 대비 이익 배율)",
                1, 50,
                int(vf_cfg.get("per_min_threshold", 5)), 1,
                disabled=not manual, key="sl_per",
                help=(
                    "PER = 주가가 연간 순이익의 몇 배인지 (Price Earnings Ratio)\n\n"
                    "예: PER 5 = 지금 주가가 연이익의 5배 → 5년 치 이익이면 주식을 살 수 있다\n"
                    "PER이 낮을수록 '저평가(싸다)'는 의미입니다.\n\n"
                    "▶ 높이면: 조금 비싼 주식도 포함 → 고성장 기업 포함 가능\n"
                    "▶ 낮추면: 정말 싼 주식만 포함 → 더 엄격한 저평가 기준"
                )
            )
            new_fscore = st.slider(
                "🏆 재무 건전성 점수 최솟값 (F-Score)",
                1, 9,
                int(vf_cfg.get("piotroski_min_score", 3)), 1,
                disabled=not manual, key="sl_fscore",
                help=(
                    "피오트로스키 F-Score = 기업 재무 건강도를 9개 항목(수익성·안전성·성장성)으로 점수화\n\n"
                    "9점: 최고 우량 기업 / 0점: 재무 위험 기업\n"
                    "기본값 3: 9개 중 최소 3개는 통과해야 매수 대상\n\n"
                    "▶ 높이면: 5~7점 이상 우량 기업만 편입 → 안전하지만 종목 수 감소\n"
                    "▶ 낮추면: 재무가 조금 불안한 기업도 포함 → 위험 증가"
                )
            )
        new_top_n_vf = st.slider(
            "🎯 한 번에 보유할 최대 종목 수",
            3, 20,
            int(vf_cfg.get("top_n_stocks", 10)), 1,
            disabled=not manual, key="sl_vf_topn",
            help=(
                "필터를 통과한 종목 중 상위 N개만 실제로 매수합니다.\n\n"
                "▶ 늘리면: 더 많은 종목에 분산 투자 → 한 종목 리스크 감소\n"
                "▶ 줄이면: 가장 좋은 소수 종목에 집중 → 수익도 크지만 리스크도 큼"
            )
        )

    # ── Section C: 트렌드라이더 ───────────────────────────
    with st.expander("트렌드라이더 (추세매매) 설정", expanded=False):

        st.info(
            "**📖 이 섹션이 하는 일**\n\n"
            "트렌드라이더는 '오르는 주식을 따라 사고, 내리는 주식을 따라 파는' 추세 추종 전략입니다. "
            "파도를 올라탄다고 생각하면 됩니다 — 파도(추세)가 오르면 타고, 내리면 내린다.\n\n"
            "**이동평균선**: 최근 N일간 평균 주가입니다. 단기 평균이 장기 평균을 뚫고 올라가면 "
            "'골든크로스(매수 신호)', 반대면 '데드크로스(매도 신호)'라고 합니다.\n\n"
            "**MACD**: 단기·장기 이동평균의 차이를 보여주는 지표로, '모멘텀(속도)'을 측정합니다. "
            "오르는 속도가 빨라지면 매수, 느려지면 매도 준비를 합니다."
        )

        tr_cfg  = cfg["agents"]["trend_rider"]
        ma_cfg  = tr_cfg["ma_periods"]
        macd_cfg = tr_cfg["macd"]
        col_c1, col_c2 = st.columns(2)
        with col_c1:
            st.markdown("**📊 이동평균선 설정** (추세 판단 기준)")
            new_ma_fast = st.slider(
                "단기선 기간 (일)",
                3, 30,
                int(ma_cfg.get("fast", 20)), 1,
                disabled=not manual, key="sl_ma_fast",
                help=(
                    "최근 며칠간 평균 주가를 '단기 추세'로 볼지 설정합니다.\n\n"
                    "기본값 20일 = 최근 한 달 평균\n\n"
                    "▶ 줄이면: 최근 변화에 더 민감하게 반응 → 신호가 많아지고 잦은 거래 발생\n"
                    "▶ 늘리면: 큰 추세만 따라감 → 안정적이지만 반응이 느림"
                )
            )
            new_ma_slow = st.slider(
                "중기선 기간 (일)",
                20, 100,
                int(ma_cfg.get("slow", 60)), 5,
                disabled=not manual, key="sl_ma_slow",
                help=(
                    "중기 추세를 판단하는 기간입니다.\n\n"
                    "기본값 60일 = 최근 3개월 평균\n"
                    "단기선이 이 선을 뚫고 올라가면 매수(골든크로스), 내려가면 매도(데드크로스)"
                )
            )
            new_ma_long = st.slider(
                "장기선 기간 (일)",
                60, 250,
                int(ma_cfg.get("long", 120)), 10,
                disabled=not manual, key="sl_ma_long",
                help=(
                    "장기 추세를 판단하는 기간입니다.\n\n"
                    "기본값 120일 = 최근 6개월 평균\n"
                    "단기>중기>장기 순서면 강한 상승 추세(공격 신호)"
                )
            )
        with col_c2:
            st.markdown("**⚡ MACD 설정** (모멘텀·속도 측정)")
            new_macd_fast = st.slider(
                "MACD 단기 기간 (일)",
                5, 30,
                int(macd_cfg.get("fast", 12)), 1,
                disabled=not manual, key="sl_macd_fast",
                help=(
                    "MACD 계산에 쓰이는 단기 기간입니다.\n\n"
                    "기본값 12일 — 업계 표준값입니다. 특별한 이유 없이는 변경하지 않는 것을 권장합니다.\n\n"
                    "▶ 줄이면: 단기 모멘텀에 더 민감 → 빠른 신호\n"
                    "▶ 늘리면: 더 큰 흐름만 포착 → 느린 신호"
                )
            )
            new_macd_slow = st.slider(
                "MACD 장기 기간 (일)",
                15, 60,
                int(macd_cfg.get("slow", 26)), 1,
                disabled=not manual, key="sl_macd_slow",
                help=(
                    "MACD 계산에 쓰이는 장기 기간입니다.\n\n"
                    "기본값 26일 — 업계 표준값입니다.\n\n"
                    "단기와 장기의 차이가 커질수록 모멘텀이 강하다는 신호"
                )
            )
            new_macd_sig = st.slider(
                "MACD 시그널 기간 (일)",
                5, 20,
                int(macd_cfg.get("signal", 9)), 1,
                disabled=not manual, key="sl_macd_sig",
                help=(
                    "MACD의 '방아쇠' 역할을 하는 기간입니다.\n\n"
                    "기본값 9일 — 업계 표준값입니다.\n\n"
                    "MACD 선이 이 시그널 선을 위로 뚫으면 매수, 아래로 내려가면 매도"
                )
            )
        new_top_n_tr = st.slider(
            "🎯 한 번에 보유할 최대 종목 수",
            3, 20,
            int(tr_cfg.get("top_n_stocks", 8)), 1,
            disabled=not manual, key="sl_tr_topn",
            help="추세 신호가 강한 상위 N개 종목만 매수합니다."
        )

    # ── Section D: 스윙마스터 ─────────────────────────────
    with st.expander("스윙마스터 (변동성매매) 설정", expanded=False):

        st.info(
            "**📖 이 섹션이 하는 일**\n\n"
            "스윙마스터는 '많이 떨어진 주식이 다시 튀어오를 때' 수익을 내는 역추세 전략입니다. "
            "고무공이 바닥에 닿으면 튀어오르듯, 주가가 과도하게 하락하면 반등을 노립니다.\n\n"
            "**볼린저 밴드**: 주가 주변에 그린 '정상 범위 띠'입니다. "
            "주가가 이 띠의 아래쪽을 뚫고 내려가면 '비정상적으로 많이 떨어진 것'으로 판단해 매수 준비합니다.\n\n"
            "**RSI**: 주가가 과열 혹은 침체 상태인지를 0~100 숫자로 표현합니다. "
            "30 이하면 '너무 많이 팔렸다(매수 신호)', 70 이상이면 '너무 많이 샀다(매도 신호)'입니다."
        )

        sm_cfg = cfg["agents"]["swing_master"]
        bb_cfg = sm_cfg["bollinger"]
        rsi_cfg = sm_cfg["rsi"]
        col_d1, col_d2 = st.columns(2)
        with col_d1:
            st.markdown("**📊 볼린저 밴드 설정** (정상 범위 띠)")
            new_bb_period = st.slider(
                "기준 기간 (일)",
                10, 50,
                int(bb_cfg.get("period", 20)), 1,
                disabled=not manual, key="sl_bb_period",
                help=(
                    "볼린저 밴드의 '정상 범위'를 계산할 기간입니다.\n\n"
                    "기본값 20일 — 최근 한 달 기준\n\n"
                    "▶ 줄이면: 최근 변동폭 기준으로 좁은 띠 → 더 자주 신호 발생\n"
                    "▶ 늘리면: 긴 기간 기준의 넓은 띠 → 신호 발생 빈도 감소"
                )
            )
            new_bb_std = st.slider(
                "밴드 너비 (표준편차 배수)",
                1.0, 3.5,
                float(bb_cfg.get("std_dev", 2.0)), 0.1,
                disabled=not manual, key="sl_bb_std",
                help=(
                    "밴드를 얼마나 넓게 펼칠지 결정합니다.\n\n"
                    "기본값 2.0 — 통계적으로 주가의 95%가 이 띠 안에 들어옴\n\n"
                    "▶ 늘리면: 띠가 넓어짐 → 더 극단적으로 떨어져야만 매수 신호 (더 보수적)\n"
                    "▶ 줄이면: 띠가 좁아짐 → 조금만 떨어져도 매수 신호 (더 공격적)"
                )
            )
        with col_d2:
            st.markdown("**⚡ RSI 설정** (과열·침체 판단)")
            new_rsi_oversold = st.slider(
                "🟢 과매도 기준선 (이하면 매수 신호)",
                10, 45,
                int(rsi_cfg.get("oversold", 30)), 1,
                disabled=not manual, key="sl_rsi_os",
                help=(
                    "RSI가 이 숫자 이하면 '너무 많이 팔렸다'고 판단해 매수 신호를 냅니다.\n\n"
                    "기본값 30 — RSI 30 이하 = 극단적 침체 상태\n\n"
                    "▶ 높이면(예: 40): 더 많은 상황에서 매수 신호 → 거래 빈도 증가\n"
                    "▶ 낮추면(예: 20): 정말 극단적인 하락에만 반응 → 신중한 진입"
                )
            )
            new_rsi_overbought = st.slider(
                "🔴 과매수 기준선 (이상이면 매도 신호)",
                55, 90,
                int(rsi_cfg.get("overbought", 70)), 1,
                disabled=not manual, key="sl_rsi_ob",
                help=(
                    "RSI가 이 숫자 이상이면 '너무 많이 올랐다'고 판단해 매도 신호를 냅니다.\n\n"
                    "기본값 70 — RSI 70 이상 = 과열 상태\n\n"
                    "▶ 낮추면(예: 60): 더 일찍 팔아서 이익 실현 → 안전하지만 수익 상한이 낮아짐\n"
                    "▶ 높이면(예: 80): 더 오를 때까지 기다림 → 수익 극대화 시도, 되돌림 위험 있음"
                )
            )
        new_top_n_sm = st.slider(
            "🎯 한 번에 보유할 최대 종목 수",
            2, 15,
            int(sm_cfg.get("top_n_stocks", 6)), 1,
            disabled=not manual, key="sl_sm_topn",
            help="반등 신호가 가장 강한 상위 N개 종목만 매수합니다."
        )

    # ── Section E: 마이크로스나이퍼 ────────────────────────
    with st.expander("🎯 마이크로스나이퍼 (초단타 스캘핑) 설정", expanded=False):

        st.info(
            "**📖 이 섹션이 하는 일**\n\n"
            "마이크로스나이퍼는 **1분봉 기반 초단타 스캘핑** 전략입니다. "
            "ADX(추세 강도)·볼린저 밴드·RSI·스토캐스틱 4가지 지표를 동시에 확인해 "
            "아주 짧은 시간 안에 진입·익절하는 방식입니다.\n\n"
            "**ADX**: 추세가 얼마나 강한지를 0~100으로 표현합니다. 20 이상이면 '방향이 명확한 추세'로 판단합니다.\n\n"
            "**스토캐스틱**: 최근 가격 범위 안에서 현재 가격이 어디에 있는지를 보여줍니다. "
            "20 이하면 침체(매수 신호), 80 이상이면 과열(매도 신호)입니다.\n\n"
            "손절/익절 기준이 짧기 때문에 하루 거래 횟수 상한선을 꼭 설정하세요."
        )

        ms_cfg = cfg["agents"]["micro_sniper"]
        ms_adx  = ms_cfg.get("adx", {})
        ms_rsi  = ms_cfg.get("rsi", {})
        ms_bb   = ms_cfg.get("bollinger", {})
        ms_stch = ms_cfg.get("stochastic", {})

        col_e1, col_e2 = st.columns(2)

        with col_e1:
            st.markdown("**📡 ADX 설정** (추세 강도 필터)")
            new_ms_adx_period = st.slider(
                "ADX 계산 기간 (분봉 캔들 수)", 7, 30,
                int(ms_adx.get("period", 15)), 1,
                disabled=not manual, key="sl_ms_adx_p",
                help="ADX를 계산할 기간입니다. 기본 15분봉 — 짧을수록 민감, 길수록 안정적."
            )
            new_ms_adx_thr = st.slider(
                "ADX 최소 임계값 (이상이어야 매매)", 10, 40,
                int(ms_adx.get("threshold", 20)), 1,
                disabled=not manual, key="sl_ms_adx_thr",
                help="ADX가 이 값 이상일 때만 진입합니다. 높이면 강한 추세에서만 매매."
            )

            st.markdown("**🎲 스토캐스틱 설정** (과열·침체 판단)")
            col_es1, col_es2 = st.columns(2)
            with col_es1:
                new_ms_stoch_k = st.slider(
                    "K 기간", 5, 30,
                    int(ms_stch.get("k_period", 14)), 1,
                    disabled=not manual, key="sl_ms_stk",
                    help="스토캐스틱 %K 계산 기간."
                )
                new_ms_stoch_os = st.slider(
                    "🟢 과매도 기준 (이하면 매수)", 10, 35,
                    int(ms_stch.get("oversold", 20)), 1,
                    disabled=not manual, key="sl_ms_stk_os",
                )
            with col_es2:
                new_ms_stoch_d = st.slider(
                    "D 기간 (신호선)", 2, 10,
                    int(ms_stch.get("d_period", 3)), 1,
                    disabled=not manual, key="sl_ms_std",
                    help="스토캐스틱 %D 이동평균 기간."
                )
                new_ms_stoch_ob = st.slider(
                    "🔴 과매수 기준 (이상이면 매도)", 65, 95,
                    int(ms_stch.get("overbought", 80)), 1,
                    disabled=not manual, key="sl_ms_stk_ob",
                )

        with col_e2:
            st.markdown("**⚡ RSI 설정**")
            new_ms_rsi_period = st.slider(
                "RSI 계산 기간", 7, 30,
                int(ms_rsi.get("period", 33)), 1,
                disabled=not manual, key="sl_ms_rsi_p",
            )
            col_er1, col_er2 = st.columns(2)
            with col_er1:
                new_ms_rsi_os = st.slider(
                    "🟢 과매도 기준", 10, 40,
                    int(ms_rsi.get("oversold", 21)), 1,
                    disabled=not manual, key="sl_ms_rsi_os",
                )
            with col_er2:
                new_ms_rsi_ob = st.slider(
                    "🔴 과매수 기준", 55, 75,
                    int(ms_rsi.get("overbought", 33)), 1,
                    disabled=not manual, key="sl_ms_rsi_ob",
                )

            st.markdown("**📊 볼린저 밴드 설정**")
            new_ms_bb_period = st.slider(
                "볼린저 기간 (분봉)", 10, 60,
                int(ms_bb.get("period", 47)), 1,
                disabled=not manual, key="sl_ms_bb_p",
            )
            new_ms_bb_std = st.slider(
                "밴드 너비 (표준편차 배수)", 1.0, 3.5,
                float(ms_bb.get("std_dev", 2.0)), 0.1,
                disabled=not manual, key="sl_ms_bb_std",
            )

            st.markdown("**🛡️ 리스크 설정**")
            col_ek1, col_ek2 = st.columns(2)
            with col_ek1:
                new_ms_sl = st.slider(
                    "🔴 손절 기준 (%)", 0.5, 5.0,
                    float(ms_cfg.get("stop_loss_pct", 0.02)) * 100, 0.1,
                    disabled=not manual, key="sl_ms_sl",
                    format="%.1f%%",
                    help="이 비율 손실 시 즉시 매도합니다."
                )
                new_ms_max_trades = st.slider(
                    "하루 최대 거래 횟수", 5, 50,
                    int(ms_cfg.get("max_daily_trades", 20)), 1,
                    disabled=not manual, key="sl_ms_max_tr",
                )
            with col_ek2:
                new_ms_tp = st.slider(
                    "🟢 익절 기준 (%)", 0.5, 5.0,
                    float(ms_cfg.get("take_profit_pct", 0.015)) * 100, 0.1,
                    disabled=not manual, key="sl_ms_tp",
                    format="%.1f%%",
                    help="이 비율 수익 시 즉시 매도해 이익을 확정합니다."
                )
                new_ms_top_n = st.slider(
                    "최대 보유 종목 수", 1, 15,
                    int(ms_cfg.get("top_n_stocks", 5)), 1,
                    disabled=not manual, key="sl_ms_topn",
                )

    st.markdown("---")

    # ══════════════════════════════════════════════════════
    # 4. 저장 버튼
    # ══════════════════════════════════════════════════════
    save_col, _ = st.columns([1, 2])
    with save_col:
        save_btn = st.button(
            "💾 설정 저장 (config.yaml 즉시 반영)",
            use_container_width=True,
            type="primary",
            disabled=not manual,
        )

    if save_btn and manual:
        # 수집된 슬라이더 값 → config dict 갱신
        cfg["chief_of_staff"]["market_regime"]["vix_thresholds"]["defensive"] = new_def
        cfg["chief_of_staff"]["market_regime"]["vix_thresholds"]["wartime"]   = new_war
        cfg["chief_of_staff"]["market_regime"]["use_ma_trend_filter"] = new_filter

        cfg["agents"]["value_finder"]["roa_min_threshold"]     = round(new_roa / 100, 4)
        cfg["agents"]["value_finder"]["per_min_threshold"]     = new_per
        cfg["agents"]["value_finder"]["sortino_min_threshold"] = round(new_sortino, 3)
        cfg["agents"]["value_finder"]["piotroski_min_score"]   = new_fscore
        cfg["agents"]["value_finder"]["top_n_stocks"]         = new_top_n_vf

        cfg["agents"]["trend_rider"]["ma_periods"]["fast"]  = new_ma_fast
        cfg["agents"]["trend_rider"]["ma_periods"]["slow"]  = new_ma_slow
        cfg["agents"]["trend_rider"]["ma_periods"]["long"]  = new_ma_long
        cfg["agents"]["trend_rider"]["macd"]["fast"]        = new_macd_fast
        cfg["agents"]["trend_rider"]["macd"]["slow"]        = new_macd_slow
        cfg["agents"]["trend_rider"]["macd"]["signal"]      = new_macd_sig
        cfg["agents"]["trend_rider"]["top_n_stocks"]        = new_top_n_tr

        cfg["agents"]["swing_master"]["bollinger"]["period"]  = new_bb_period
        cfg["agents"]["swing_master"]["bollinger"]["std_dev"] = round(new_bb_std, 2)
        cfg["agents"]["swing_master"]["rsi"]["oversold"]     = new_rsi_oversold
        cfg["agents"]["swing_master"]["rsi"]["overbought"]   = new_rsi_overbought
        cfg["agents"]["swing_master"]["top_n_stocks"]        = new_top_n_sm

        cfg["agents"]["micro_sniper"]["adx"]["period"]           = new_ms_adx_period
        cfg["agents"]["micro_sniper"]["adx"]["threshold"]        = new_ms_adx_thr
        cfg["agents"]["micro_sniper"]["rsi"]["period"]           = new_ms_rsi_period
        cfg["agents"]["micro_sniper"]["rsi"]["oversold"]         = new_ms_rsi_os
        cfg["agents"]["micro_sniper"]["rsi"]["overbought"]       = new_ms_rsi_ob
        cfg["agents"]["micro_sniper"]["bollinger"]["period"]     = new_ms_bb_period
        cfg["agents"]["micro_sniper"]["bollinger"]["std_dev"]    = round(new_ms_bb_std, 2)
        cfg["agents"]["micro_sniper"]["stochastic"]["k_period"]  = new_ms_stoch_k
        cfg["agents"]["micro_sniper"]["stochastic"]["d_period"]  = new_ms_stoch_d
        cfg["agents"]["micro_sniper"]["stochastic"]["oversold"]  = new_ms_stoch_os
        cfg["agents"]["micro_sniper"]["stochastic"]["overbought"]= new_ms_stoch_ob
        cfg["agents"]["micro_sniper"]["stop_loss_pct"]           = round(new_ms_sl / 100, 4)
        cfg["agents"]["micro_sniper"]["take_profit_pct"]         = round(new_ms_tp / 100, 4)
        cfg["agents"]["micro_sniper"]["max_daily_trades"]        = new_ms_max_trades
        cfg["agents"]["micro_sniper"]["top_n_stocks"]            = new_ms_top_n

        if save_config(cfg):
            # session_state config 도 갱신
            st.session_state.config = cfg
            db.log_system_event("INFO", "AdminPanel", "설정 저장 완료 — config.yaml 업데이트")
            st.success("✅ 설정이 config.yaml에 저장되었습니다! 다음 사이클부터 즉시 적용됩니다.")
        else:
            st.error("❌ 설정 저장 실패 — 파일 쓰기 권한을 확인하세요.")

    if not manual:
        st.caption("🔒 자동 모드에서는 저장이 비활성화됩니다. '수동 조정'으로 전환 후 저장하세요.")

    st.markdown("---")

    # ══════════════════════════════════════════════════════
    # 4-F. 🏦 한국투자증권 KIS API 설정
    # ══════════════════════════════════════════════════════
    with st.expander("🏦 한국투자증권 KIS API 연동 설정", expanded=False):
        st.info(
            "**📖 이 섹션이 하는 일**\n\n"
            "실전 투자 전환 시 한국투자증권 KIS API 인증 정보를 등록합니다.\n\n"
            "**발급 방법**: [KIS Developers 포털](https://apiportal.koreainvestment.com) 접속 → 앱 등록 → "
            "App Key / App Secret 발급 (무료, 계좌 보유자라면 즉시 가능)\n\n"
            "⚠️ **주의**: App Key·App Secret은 비밀번호와 같습니다. 타인과 공유하지 마세요.\n"
            "입력 후 저장하면 `config.yaml`에 기록됩니다."
        )

        _kis_cfg = cfg.get("broker", {}).get("live", {})
        _sys_cfg = cfg.get("system", {})

        _kis_col1, _kis_col2 = st.columns(2)

        with _kis_col1:
            st.markdown("##### 🔑 API 인증 정보")
            _new_app_key = st.text_input(
                "App Key",
                value=_kis_cfg.get("app_key", ""),
                type="password",
                placeholder="PSxxxxxxxxxxxxxxxxxxxxxxxx",
                key="kis_app_key",
                help="KIS Developers에서 발급한 App Key (실전/모의 구분 주의)",
            )
            _new_app_secret = st.text_input(
                "App Secret",
                value=_kis_cfg.get("app_secret", ""),
                type="password",
                placeholder="App Secret을 입력하세요",
                key="kis_app_secret",
                help="KIS Developers에서 발급한 App Secret",
            )
            _new_account = st.text_input(
                "계좌번호 (앞 8자리)",
                value=_kis_cfg.get("account_number", ""),
                placeholder="12345678",
                max_chars=8,
                key="kis_account",
                help="한국투자증권 계좌번호 앞 8자리만 입력 (뒤 2자리 제외)",
            )

        with _kis_col2:
            st.markdown("##### ⚙️ 계좌 및 운용 모드")
            _new_acct_type = st.selectbox(
                "계좌 구분",
                options=["01", "02"],
                index=0 if _kis_cfg.get("account_type", "01") == "01" else 1,
                format_func=lambda x: "01 — 실전 투자" if x == "01" else "02 — 모의 투자",
                key="kis_acct_type",
                help="01=실전, 02=모의투자. KIS Developers에서 앱 등록 시 선택한 구분과 일치해야 합니다.",
            )
            _new_base_url = (
                "https://openapi.koreainvestment.com:9443"
                if _new_acct_type == "01"
                else "https://openapivts.koreainvestment.com:29443"
            )
            st.text_input(
                "API 엔드포인트 (자동 설정)",
                value=_new_base_url,
                disabled=True,
                key="kis_base_url_display",
                help="계좌 구분에 따라 자동으로 결정됩니다.",
            )

            _cur_mode = _sys_cfg.get("mode", "paper")
            _new_mode = st.selectbox(
                "거래 모드",
                options=["paper", "live"],
                index=0 if _cur_mode == "paper" else 1,
                format_func=lambda x: "📄 paper — 모의투자 (안전)" if x == "paper" else "🔴 live — 실전 투자 (실제 주문)",
                key="kis_trade_mode",
                help="live로 변경하면 다음 사이클부터 실제 주문이 나갑니다.",
            )

            if _new_mode == "live":
                st.warning("⚠️ **live 모드**: 실제 계좌에서 주문이 체결됩니다. App Key·계좌번호가 정확한지 반드시 확인하세요.")

        # 연결 상태 표시
        _has_key = bool(_kis_cfg.get("app_key") and _kis_cfg.get("app_secret") and _kis_cfg.get("account_number"))
        if _has_key:
            _connected_mode = "🔴 실전" if _kis_cfg.get("account_type") == "01" else "📄 모의"
            st.success(
                f"✅ **API 정보 등록됨** — 계좌 {_kis_cfg.get('account_number', '')}  |  "
                f"계좌 구분: {_connected_mode}  |  "
                f"운용 모드: **{_cur_mode.upper()}**"
            )
        else:
            st.warning("🔌 API 정보 미등록 — 현재 모의투자(Paper) 모드로 운용 중입니다.")

        _kis_save_col, _kis_test_col = st.columns([2, 1])
        with _kis_save_col:
            if st.button("💾 KIS API 설정 저장", key="btn_save_kis", use_container_width=True, type="primary"):
                try:
                    if "broker" not in cfg:
                        cfg["broker"] = {}
                    if "live" not in cfg["broker"]:
                        cfg["broker"]["live"] = {}
                    cfg["broker"]["provider"]               = "kis"
                    cfg["broker"]["live"]["app_key"]        = _new_app_key.strip()
                    cfg["broker"]["live"]["app_secret"]     = _new_app_secret.strip()
                    cfg["broker"]["live"]["account_number"] = _new_account.strip()
                    cfg["broker"]["live"]["account_type"]   = _new_acct_type
                    cfg["broker"]["live"]["base_url"]       = _new_base_url
                    cfg["system"]["mode"]                   = _new_mode
                    if save_config(cfg):
                        st.session_state.config = cfg
                        db.log_system_event(
                            "INFO", "AdminPanel",
                            f"KIS API 설정 저장 — 계좌:{_new_account[:4]}**** 구분:{_new_acct_type} 모드:{_new_mode}"
                        )
                        st.success("✅ KIS API 설정이 저장되었습니다! 다음 사이클부터 적용됩니다.")
                        st.rerun()
                    else:
                        st.error("❌ 설정 저장 실패")
                except Exception as _kis_ex:
                    st.error(f"저장 오류: {_kis_ex}")
        with _kis_test_col:
            if st.button("🔍 연결 테스트", key="btn_test_kis", use_container_width=True):
                _test_key = _new_app_key.strip() or _kis_cfg.get("app_key", "")
                _test_sec = _new_app_secret.strip() or _kis_cfg.get("app_secret", "")
                if not (_test_key and _test_sec):
                    st.warning("App Key와 App Secret을 먼저 입력하세요.")
                else:
                    with st.spinner("KIS API 서버에 연결 중..."):
                        try:
                            import requests as _req
                            _token_url = f"{_new_base_url}/oauth2/tokenP"
                            _resp = _req.post(
                                _token_url,
                                json={"grant_type": "client_credentials",
                                      "appkey": _test_key, "appsecret": _test_sec},
                                timeout=10,
                            )
                            if _resp.status_code == 200 and _resp.json().get("access_token"):
                                st.success("✅ KIS API 연결 성공 — 액세스 토큰 정상 발급")
                            else:
                                _msg = _resp.json().get("msg1") or _resp.text[:120]
                                st.error(f"❌ 연결 실패: {_msg}")
                        except Exception as _te:
                            st.error(f"❌ 연결 오류: {_te}")

        st.caption(
            "🔗 **발급 안내**: [KIS Developers 포털](https://apiportal.koreainvestment.com) → 로그인 → "
            "'앱 등록' → App Key / App Secret 복사  |  "
            "실전·모의 앱은 별도 등록 필요 (각각 다른 키 발급)"
        )

    st.markdown("---")

    # ══════════════════════════════════════════════════════
    # 5. 🎯 일일 단타 목표 수익 (Daily Take Profit)
    # ══════════════════════════════════════════════════════
    st.markdown("## 🎯 일일 단타 목표 수익 설정")
    st.caption(
        "스윙마스터·마이크로스나이퍼가 하루 목표를 달성하면 수익을 확정하고 당일 매매를 자동 종료합니다."
    )

    _cur_user_for_tp = st.session_state.get("user", {})
    _cur_tp_val = float(_cur_user_for_tp.get("daily_target_profit", 0.03) or 0.03)
    _cur_tp_pct = max(1, min(10, int(round(_cur_tp_val * 100))))

    _tp_col1, _tp_col2 = st.columns([2, 1])
    with _tp_col1:
        _new_tp_pct = st.slider(
            "📈 일일 단타 목표 수익률",
            min_value=1, max_value=10, value=_cur_tp_pct, step=1,
            format="%d%%",
            help="이 수익률 도달 시 스윙마스터·마이크로스나이퍼가 당일 매매를 멈춥니다.",
            key="sl_daily_tp",
        )
        st.caption(
            "목표 수익 도달 시, 단기 매매 에이전트들은 수익을 확정하고 당일 매매를 종료(퇴근)합니다."
        )
    with _tp_col2:
        st.metric("현재 설정", f"+{_cur_tp_pct}%")
        if st.button("💾 저장", key="btn_save_tp", use_container_width=True):
            _tp_user_id = _cur_user_for_tp.get("id")
            if _tp_user_id:
                try:
                    db.migrate_trading_features()
                    db.update_user_trading_settings(
                        user_id=_tp_user_id,
                        daily_target_profit=_new_tp_pct / 100,
                    )
                    st.session_state["user"]["daily_target_profit"] = _new_tp_pct / 100
                    st.success(f"✅ 일일 단타 목표 +{_new_tp_pct}% 저장 완료")
                    db.log_system_event("INFO", "Dashboard", f"일일 단타 목표수익 설정: {_new_tp_pct}%")
                except Exception as _tp_ex:
                    st.error(f"저장 실패: {_tp_ex}")
            else:
                st.warning("로그인 후 저장하세요.")

    st.markdown("---")

    # ══════════════════════════════════════════════════════
    # 5-B. 🏆 에이전트별 개별 자동 퇴근 설정
    # ══════════════════════════════════════════════════════
    st.markdown("## 🏆 에이전트별 개별 자동 퇴근 설정")
    st.caption(
        "각 에이전트가 담당 몫의 수익을 달성하면 다른 에이전트와 무관하게 독립적으로 Sleep합니다.\n"
        "0%로 설정하면 해당 에이전트는 당일 목표 없이 계속 매매합니다."
    )

    _itp_user = st.session_state.get("user", {})
    _itp_c1, _itp_c2, _itp_c3, _itp_c4 = st.columns(4)

    def _itp_val(key, default):
        return max(0, min(30, int(round(float(_itp_user.get(key, default) or default) * 100))))

    with _itp_c1:
        st.markdown("**💎 밸류파인더**")
        _itp_vf = st.slider("", 0, 30, _itp_val("target_profit_value", 0.15), 1,
                             format="%d%%", key="sl_itp_vf",
                             help="달성 시 밸류파인더만 당일 Sleep. 0% = 무제한.")
        st.caption(f"현재: {'없음' if _itp_vf == 0 else f'+{_itp_vf}%'}")
    with _itp_c2:
        st.markdown("**📈 트렌드라이더**")
        _itp_tr = st.slider("", 0, 30, _itp_val("target_profit_trend", 0.10), 1,
                             format="%d%%", key="sl_itp_tr",
                             help="달성 시 트렌드라이더만 당일 Sleep.")
        st.caption(f"현재: {'없음' if _itp_tr == 0 else f'+{_itp_tr}%'}")
    with _itp_c3:
        st.markdown("**🎢 스윙마스터**")
        _itp_sw = st.slider("", 0, 20, _itp_val("target_profit_swing", 0.05), 1,
                             format="%d%%", key="sl_itp_sw",
                             help="달성 시 스윙마스터만 당일 Sleep.")
        st.caption(f"현재: {'없음' if _itp_sw == 0 else f'+{_itp_sw}%'}")
    with _itp_c4:
        st.markdown("**🎯 마이크로스나이퍼**")
        _itp_sn = st.slider("", 0, 10, _itp_val("target_profit_sniper", 0.03), 1,
                             format="%d%%", key="sl_itp_sn",
                             help="달성 시 마이크로스나이퍼만 당일 Sleep.")
        st.caption(f"현재: {'없음' if _itp_sn == 0 else f'+{_itp_sn}%'}")

    if st.button("💾 에이전트별 퇴근 목표 저장", key="btn_save_itp", type="primary"):
        _itp_uid = _itp_user.get("id")
        if _itp_uid:
            try:
                db.migrate_trading_features()
                db.update_user_trading_settings(
                    user_id=_itp_uid,
                    target_profit_value=_itp_vf / 100,
                    target_profit_trend=_itp_tr / 100,
                    target_profit_swing=_itp_sw / 100,
                    target_profit_sniper=_itp_sn / 100,
                )
                st.session_state["user"]["target_profit_value"]  = _itp_vf / 100
                st.session_state["user"]["target_profit_trend"]  = _itp_tr / 100
                st.session_state["user"]["target_profit_swing"]  = _itp_sw / 100
                st.session_state["user"]["target_profit_sniper"] = _itp_sn / 100
                st.success(
                    f"✅ 저장 완료 — 밸류 +{_itp_vf}% / 트렌드 +{_itp_tr}% / "
                    f"스윙 +{_itp_sw}% / 스나이퍼 +{_itp_sn}%\n\n"
                    "각 에이전트는 목표 달성 즉시 독립적으로 당일 매매를 종료합니다."
                )
                db.log_system_event(
                    "INFO", "Dashboard",
                    f"에이전트별 개별 TP 설정: 밸류{_itp_vf}% 트렌드{_itp_tr}% 스윙{_itp_sw}% 스나이퍼{_itp_sn}%"
                )
            except Exception as _itp_ex:
                st.error(f"저장 실패: {_itp_ex}")
        else:
            st.warning("로그인 후 저장하세요.")

    st.markdown("---")

    # ══════════════════════════════════════════════════════
    # 6. ✋ 수동 자산 배분 (Manual Override)
    # ══════════════════════════════════════════════════════
    st.markdown("## ✋ 자산 배분 모드 설정")
    st.caption(
        "비서실장 자동 판단을 끄고 4대 에이전트에 직접 예산 비율을 지정할 수 있습니다."
    )

    _mo_user = st.session_state.get("user", {})
    _mo_mode  = _mo_user.get("allocation_mode", "auto") or "auto"

    _mo_choice = st.radio(
        "운용 모드",
        options=["🤖 비서실장 자동 위임 (Auto)", "✋ 수동 예산 할당 (Manual)"],
        index=1 if _mo_mode == "manual" else 0,
        horizontal=True,
        key="radio_alloc_mode",
    )
    _mo_is_manual = "Manual" in _mo_choice

    # ── 스나이퍼 고정 예산 (모드 공통) ──────────────────────
    _mo_ic      = float(config.get("paper_trading", {}).get("initial_capital", 100_000_000))
    _mo_sn_fixed_def = int(float(_mo_user.get("sniper_fixed_budget", 5_000_000) or 5_000_000))

    if _mo_is_manual:
        st.info(
            "📌 비서실장의 VIX·이동평균 판단을 무시하고, 직접 입력한 비율로 매매합니다.\n\n"
            "**마이크로스나이퍼는 슬리피지 방지를 위해 비율이 아닌 정액(원화)으로 독립 운용됩니다.** "
            "3대 에이전트는 '총자본 − 스나이퍼 정액'을 100%로 나눕니다."
        )

        # ── 스나이퍼 정액 입력 (맨 위 별도 블록) ──────────
        _sn_col1, _sn_col2 = st.columns([3, 2])
        with _sn_col1:
            _mo_sn_fixed = st.number_input(
                "🎯 마이크로스나이퍼 고정 예산 (원화)",
                min_value=0,
                max_value=int(_mo_ic),
                value=_mo_sn_fixed_def,
                step=500_000,
                key="ni_mo_sn_fixed",
                help="슬리피지 방지용 정액 운용 — 시장 상황과 무관하게 항상 이 금액만 사용합니다. "
                     "전시 레짐(VIX ≥ 30)일 때는 자동으로 0원으로 강제 회수됩니다.",
            )
        with _sn_col2:
            _core_for_3 = max(0, _mo_ic - _mo_sn_fixed)
            st.metric("핵심 운용 자본 (3대 에이전트 몫)", f"{_core_for_3:,.0f}원")
            st.caption(f"총자본 {_mo_ic:,.0f}원 − 스나이퍼 {_mo_sn_fixed:,.0f}원")

        st.markdown("---")
        st.markdown("**3대 에이전트 예산 배분** *(핵심 운용 자본의 % 비율)*")

        _mo_c1, _mo_c2, _mo_c3 = st.columns(3)
        _mo_vf_def = int(round(float(_mo_user.get("budget_value_pct",  0.35) or 0.35) * 100))
        _mo_tr_def = int(round(float(_mo_user.get("budget_trend_pct",  0.35) or 0.35) * 100))
        _mo_sw_def = int(round(float(_mo_user.get("budget_swing_pct",  0.20) or 0.20) * 100))

        with _mo_c1:
            _mo_vf = st.number_input(
                "💎 밸류파인더 (%)", 0, 100, _mo_vf_def, 5, key="ni_mo_vf",
                help="핵심 운용 자본 내 밸류파인더 배분 비율"
            )
            st.caption(f"≈ {_core_for_3 * _mo_vf / 100:,.0f}원")
        with _mo_c2:
            _mo_tr = st.number_input(
                "📈 트렌드라이더 (%)", 0, 100, _mo_tr_def, 5, key="ni_mo_tr",
                help="핵심 운용 자본 내 트렌드라이더 배분 비율"
            )
            st.caption(f"≈ {_core_for_3 * _mo_tr / 100:,.0f}원")
        with _mo_c3:
            _mo_sw = st.number_input(
                "🎢 스윙마스터 (%)", 0, 100, _mo_sw_def, 5, key="ni_mo_sw",
                help="핵심 운용 자본 내 스윙마스터 배분 비율"
            )
            st.caption(f"≈ {_core_for_3 * _mo_sw / 100:,.0f}원")

        _mo_total = _mo_vf + _mo_tr + _mo_sw
        _mo_cash  = max(0, 100 - _mo_total)
        if _mo_total > 100:
            st.warning(f"⚠️ 합계 {_mo_total}% > 100% — 저장 시 자동 정규화됩니다.")
        else:
            st.success(
                f"✅ 3대 에이전트 합계 {_mo_total}% | 현금 유보 {_mo_cash}% "
                f"| 스나이퍼 정액 {_mo_sn_fixed:,.0f}원 별도"
            )

        if st.button("✅ 수동 배분 적용", key="btn_apply_manual", type="primary"):
            _mo_uid = _mo_user.get("id")
            if _mo_uid:
                try:
                    db.migrate_trading_features()
                    db.update_user_trading_settings(
                        user_id=_mo_uid,
                        allocation_mode="manual",
                        budget_value_pct=_mo_vf / 100,
                        budget_trend_pct=_mo_tr / 100,
                        budget_swing_pct=_mo_sw / 100,
                        sniper_fixed_budget=float(_mo_sn_fixed),
                    )
                    st.session_state["user"]["allocation_mode"]      = "manual"
                    st.session_state["user"]["budget_value_pct"]     = _mo_vf / 100
                    st.session_state["user"]["budget_trend_pct"]     = _mo_tr / 100
                    st.session_state["user"]["budget_swing_pct"]     = _mo_sw / 100
                    st.session_state["user"]["sniper_fixed_budget"]  = float(_mo_sn_fixed)
                    db.log_system_event(
                        "INFO", "Dashboard",
                        f"수동 배분 설정: 밸류{_mo_vf}% 트렌드{_mo_tr}% 스윙{_mo_sw}% "
                        f"스나이퍼 정액{_mo_sn_fixed:,.0f}원"
                    )
                    st.success(
                        f"✅ 수동 배분 적용 완료 — 다음 사이클부터 비서실장 자동 판단을 우회합니다.\n\n"
                        f"밸류 {_mo_vf}% / 트렌드 {_mo_tr}% / 스윙 {_mo_sw}% "
                        f"| 스나이퍼 정액 {_mo_sn_fixed:,.0f}원 독립 운용"
                    )
                except Exception as _mo_ex:
                    st.error(f"저장 실패: {_mo_ex}")
            else:
                st.warning("로그인 후 적용하세요.")
    else:
        # ── 자동 모드: 스나이퍼 정액 안내 ───────────────────
        st.info(
            "🤖 **비서실장이 VIX·이동평균선을 분석하여 3대 에이전트 예산을 자동 조정합니다.**\n\n"
            f"🎯 마이크로스나이퍼는 슬리피지 방지를 위해 시장 상황과 무관하게 "
            f"독립된 **정액 {_mo_sn_fixed_def:,.0f}원**으로 운용됩니다.\n"
            "*(단, 전시 레짐 VIX ≥ 30 시 스나이퍼 예산도 0원으로 자동 회수됩니다.)*"
        )

        _sn_auto_col1, _sn_auto_col2 = st.columns([3, 2])
        with _sn_auto_col1:
            _mo_sn_fixed_new = st.number_input(
                "🎯 마이크로스나이퍼 고정 예산 설정 (원화)",
                min_value=0,
                max_value=int(_mo_ic),
                value=_mo_sn_fixed_def,
                step=500_000,
                key="ni_mo_sn_auto",
                help="자동 모드에서도 스나이퍼 정액 금액은 직접 설정합니다."
            )
        with _sn_auto_col2:
            if st.button("💾 스나이퍼 정액 저장", key="btn_save_sniper_auto"):
                _mo_uid_a = _mo_user.get("id")
                if _mo_uid_a:
                    try:
                        db.migrate_trading_features()
                        db.update_user_trading_settings(
                            user_id=_mo_uid_a,
                            sniper_fixed_budget=float(_mo_sn_fixed_new),
                        )
                        st.session_state["user"]["sniper_fixed_budget"] = float(_mo_sn_fixed_new)
                        st.success(f"✅ 스나이퍼 정액 {_mo_sn_fixed_new:,.0f}원 저장 완료")
                        db.log_system_event("INFO", "Dashboard",
                            f"스나이퍼 고정예산 설정: {_mo_sn_fixed_new:,.0f}원")
                    except Exception as _sae:
                        st.error(f"저장 실패: {_sae}")
                else:
                    st.warning("로그인 후 저장하세요.")

        if st.button("🤖 자동 모드로 전환", key="btn_switch_auto"):
            _mo_uid = _mo_user.get("id")
            if _mo_uid:
                try:
                    db.migrate_trading_features()
                    db.update_user_trading_settings(user_id=_mo_uid, allocation_mode="auto")
                    st.session_state["user"]["allocation_mode"] = "auto"
                    st.success("✅ 자동 모드로 전환되었습니다.")
                    db.log_system_event("INFO", "Dashboard", "자산 배분 모드: 자동으로 전환")
                except Exception as _mo_ex:
                    st.error(f"전환 실패: {_mo_ex}")

    st.markdown("---")

    # ══════════════════════════════════════════════════════
    # 6-B. 💰 가상 입출금 (MDD 오작동 방지 보정)
    # ══════════════════════════════════════════════════════
    st.markdown("## 💰 가상 입출금 (MDD 보정)")
    st.caption(
        "모의투자 중 가상으로 자금을 입출금할 수 있습니다. "
        "입출금액은 당일 MDD 계산 기준선에 반영되어 오인 킬스위치를 방지합니다."
    )

    _cf_col1, _cf_col2 = st.columns(2)

    with _cf_col1:
        st.markdown("##### 💵 가상 입금")
        _dep_amount = st.number_input(
            "입금액 (원)", min_value=0, max_value=500_000_000,
            value=10_000_000, step=1_000_000, key="ni_deposit",
            help="포트폴리오 현금 잔고 증가 + 오늘 MDD 기준선 상향 보정"
        )
        _dep_note = st.text_input("입금 메모", value="추가 자금 투입", key="ti_dep_note")
        if st.button("💵 입금하기", key="btn_deposit", use_container_width=True, type="primary"):
            if _dep_amount <= 0:
                st.warning("입금액을 입력하세요.")
            else:
                try:
                    from SimulationEngine import PaperTradingEngine as _PTE
                    from config_loader import load_config as _lc2
                    _pt = _PTE(_lc2(), db)
                    _pt.register_cash_flow(_dep_amount, _dep_note or "가상입금")
                    db.log_system_event("INFO", "Dashboard", f"가상입금: {_dep_amount:,.0f}원 ({_dep_note})")
                    st.success(f"✅ {_dep_amount:,.0f}원 입금 완료. 현금 잔고에 반영됐습니다.")
                    st.rerun()
                except Exception as _ce:
                    st.error(f"입금 실패: {_ce}")

    with _cf_col2:
        st.markdown("##### 🏧 가상 출금")
        _portfolio_now = db.get_portfolio("paper")
        _cash_now = _portfolio_now.get("cash", 0)
        st.caption(f"현재 현금 잔고: **{_cash_now:,.0f}원**")
        _wth_amount = st.number_input(
            "출금액 (원)", min_value=0, max_value=int(max(_cash_now, 1)),
            value=min(5_000_000, int(_cash_now)) if _cash_now > 0 else 0,
            step=1_000_000, key="ni_withdraw",
            help="포트폴리오 현금 잔고 감소 + 오늘 MDD 기준선 하향 보정"
        )
        _wth_note = st.text_input("출금 메모", value="자금 인출", key="ti_wth_note")
        if st.button("🏧 출금하기", key="btn_withdraw", use_container_width=True):
            if _wth_amount <= 0:
                st.warning("출금액을 입력하세요.")
            elif _wth_amount > _cash_now:
                st.error(f"현금 잔고({_cash_now:,.0f}원) 초과 출금은 불가합니다.")
            else:
                try:
                    from SimulationEngine import PaperTradingEngine as _PTE2
                    from config_loader import load_config as _lc3
                    _pt2 = _PTE2(_lc3(), db)
                    _pt2.register_cash_flow(-_wth_amount, _wth_note or "가상출금")
                    db.log_system_event("INFO", "Dashboard", f"가상출금: {_wth_amount:,.0f}원 ({_wth_note})")
                    st.success(f"✅ {_wth_amount:,.0f}원 출금 완료.")
                    st.rerun()
                except Exception as _we:
                    st.error(f"출금 실패: {_we}")

    # ── 오늘 입출금 내역 ─────────────────────────────────────────
    _today_cf = db.get_daily_cash_flow(datetime.now().strftime("%Y-%m-%d"))
    if _today_cf != 0:
        _cf_color = "#34d399" if _today_cf > 0 else "#f87171"
        _cf_label = "순입금" if _today_cf > 0 else "순출금"
        st.info(f"📊 오늘 {_cf_label}: **{_today_cf:+,.0f}원** — 이 금액은 MDD 손익 계산에서 제외됩니다.")

    with st.expander("📋 최근 입출금 내역"):
        _cf_history = db.get_cash_flow_history(limit=20)
        if _cf_history:
            import pandas as pd
            _cf_df = pd.DataFrame(_cf_history)
            _cf_df["구분"] = _cf_df["amount"].apply(lambda x: "💵 입금" if x >= 0 else "🏧 출금")
            _cf_df["금액"] = _cf_df["amount"].apply(lambda x: f"{x:+,.0f}원")
            _cf_df = _cf_df.rename(columns={"date": "날짜", "note": "메모", "recorded_at": "기록시각"})
            st.dataframe(_cf_df[["날짜", "구분", "금액", "메모", "기록시각"]], use_container_width=True)
        else:
            st.caption("입출금 내역이 없습니다.")

    st.markdown("---")

    # ══════════════════════════════════════════════════════
    # 7. 백테스트 재실행
    # ══════════════════════════════════════════════════════
    st.markdown("### 🔄 수정된 전략으로 백테스트 재실행")
    st.caption(
        "현재 저장된 config.yaml 파라미터로 과거 데이터(2020-2023 In-Sample + 2024 Out-of-Sample)를 즉시 재검증합니다."
    )

    if st.button("🚀 백테스트 재실행", type="primary", use_container_width=False, key="admin_bt_run"):
        with st.spinner("⏳ 백테스트 실행 중... (약 30~60초 소요)"):
            try:
                from SimulationEngine import BacktestEngine
                # 저장된 최신 config를 새로 로드
                from config_loader import load_config as _lc
                fresh_cfg = _lc()
                bt = BacktestEngine(fresh_cfg, db=db)
                bt_results = bt.run_all_strategies(save_to_db=True)
                st.session_state["admin_bt_results"] = bt_results
                st.success(f"✅ 백테스트 완료! {len(bt_results)}개 전략 결과")
            except Exception as e:
                st.error(f"❌ 백테스트 오류: {e}")
                st.session_state["admin_bt_results"] = []

    # 결과 표시
    bt_res = st.session_state.get("admin_bt_results", [])
    if bt_res:
        st.markdown("#### 📊 백테스트 결과 요약")

        rows = []
        for r in bt_res:
            # PerformanceReport 객체 또는 dict만 처리, 그 외(str 등) 무시
            if hasattr(r, "to_dict"):
                d = r.to_dict()
            elif isinstance(r, dict):
                d = r
            else:
                continue  # 문자열이나 기타 타입은 건너뜀
            rows.append({
                "전략":        d.get("strategy_name", "—"),
                "기간":        f"{str(d.get('start_date',''))[:10]} ~ {str(d.get('end_date',''))[:10]}",
                "총수익률":    f"{d.get('total_return', 0):.2%}",
                "연환산":      f"{d.get('annual_return', 0):.2%}",
                "샤프지수":    f"{d.get('sharpe_ratio', 0):.3f}",
                "소르티노":    f"{d.get('sortino_ratio', 0):.3f}",
                "최대낙폭MDD": f"{d.get('max_drawdown', 0):.2%}",
                "승률":        f"{d.get('win_rate', 0):.1%}",
                "총거래":      d.get("total_trades", 0),
                "벤치마크대비":f"{d.get('alpha', 0):.2%}",
            })

        df_bt = pd.DataFrame(rows)

        # 컬러 하이라이트: IS(In-Sample) vs OOS(Out-of-Sample) 구분
        is_rows  = [r for r in rows if "In-Sample"  in r["전략"] or "IS"  in r["전략"]]
        oos_rows = [r for r in rows if "Out-of-Sample" in r["전략"] or "OOS" in r["전략"]]
        other    = [r for r in rows if r not in is_rows and r not in oos_rows]

        if is_rows or oos_rows:
            if is_rows:
                st.markdown("**🔵 In-Sample (학습 구간: 2020-2023)**")
                st.dataframe(pd.DataFrame(is_rows), use_container_width=True, hide_index=True)
            if oos_rows:
                st.markdown("**🟠 Out-of-Sample (검증 구간: 2024)**")
                st.dataframe(pd.DataFrame(oos_rows), use_container_width=True, hide_index=True)
            if other:
                st.dataframe(pd.DataFrame(other), use_container_width=True, hide_index=True)
        else:
            st.dataframe(df_bt, use_container_width=True, hide_index=True)

        # 유효한 결과만 필터링 (PerformanceReport 또는 dict 형태만)
        def _to_dict_safe(r):
            if hasattr(r, "to_dict"):
                return r.to_dict()
            if isinstance(r, dict):
                return r
            return None

        valid_results = [_to_dict_safe(r) for r in bt_res if _to_dict_safe(r) is not None]

        # KPI 강조 카드
        if valid_results:
            st.markdown("#### 🏆 핵심 성과 지표")
            kpi_cols = st.columns(max(len(valid_results), 1))
            for i, d in enumerate(valid_results):
                with kpi_cols[i]:
                    name   = d.get("strategy_name", f"전략{i+1}")
                    ret    = d.get("total_return", 0)
                    sharpe = d.get("sharpe_ratio", 0)
                    mdd    = d.get("max_drawdown", 0)
                    color  = "#68d391" if ret > 0 else "#fc8181"
                    st.markdown(
                        f"<div style='background:linear-gradient(135deg,#1e293b,#162032);"
                        f"border:1px solid #2d3748;border-radius:10px;padding:1rem;text-align:center'>"
                        f"<div style='font-size:0.75rem;color:#a0aec0'>{name[:30]}</div>"
                        f"<div style='font-size:1.6rem;font-weight:bold;color:{color}'>{ret:+.1%}</div>"
                        f"<div style='color:#a0aec0;font-size:0.8rem'>총수익률</div>"
                        f"<hr style='border-color:#2d3748;margin:0.5rem 0'>"
                        f"<div style='font-size:0.85rem'>샤프 <b>{sharpe:.3f}</b> | MDD <b style='color:#fc8181'>{mdd:.1%}</b></div>"
                        f"</div>",
                        unsafe_allow_html=True,
                    )

            # 오버피팅 체크
            if len(valid_results) >= 2:
                st.markdown("#### 🔍 과최적화(Overfitting) 체크")
                is_d  = next((d for d in valid_results if "In"  in d.get("strategy_name", "")), None)
                oos_d = next((d for d in valid_results if "Out" in d.get("strategy_name", "")), None)
                if is_d and oos_d:
                    is_ret  = is_d.get("total_return", 0)
                    oos_ret = oos_d.get("total_return", 0)
                    degradation = is_ret - oos_ret
                    if abs(is_ret) > 0:
                        deg_pct = degradation / abs(is_ret)
                        if deg_pct < 0.5:
                            st.success(f"✅ 과최적화 없음 — IS {is_ret:.1%} → OOS {oos_ret:.1%} (열화율 {deg_pct:.0%} < 50%)")
                        elif deg_pct < 0.8:
                            st.warning(f"⚠️ 주의 — IS {is_ret:.1%} → OOS {oos_ret:.1%} (열화율 {deg_pct:.0%}). 파라미터 재검토 권장")
                        else:
                            st.error(f"❌ 과최적화 의심 — IS {is_ret:.1%} → OOS {oos_ret:.1%} (열화율 {deg_pct:.0%}). 전략 조정 필요")


# 하단 정보
st.markdown("---")
st.markdown(
    "<div style='text-align:center;color:#4a5568;font-size:0.8rem'>"
    "AI 퀀트 투자 운용 시스템 | 모의투자 전용 | 투자는 항상 리스크를 동반합니다"
    "</div>",
    unsafe_allow_html=True,
)

# ═══════════════════════════════════════════════════════════
# 탭 10: 👥 사용자 관리 (관리자 전용)
# ═══════════════════════════════════════════════════════════
if _u.get("is_admin") and len(tabs) >= 10:
    with tabs[9]:
        st.markdown("## 👥 사용자 관리")

        # ── 승인 대기 섹션 ────────────────────────────────────
        _pending_users = db.get_pending_users()
        if _pending_users:
            st.markdown(
                f"<div style='background:#2d1b00;border:1px solid #b45309;border-radius:10px;"
                f"padding:1rem 1.25rem;margin-bottom:1.5rem;'>"
                f"<b style='color:#f59e0b'>⏳ 승인 대기 {len(_pending_users)}명</b></div>",
                unsafe_allow_html=True,
            )
            for _pu in _pending_users:
                _puc1, _puc2, _puc3 = st.columns([3, 1, 1])
                with _puc1:
                    st.markdown(
                        f"**{_pu['name']}** &nbsp;·&nbsp; {_pu['email']} &nbsp;·&nbsp; "
                        f"<span style='color:#64748b;font-size:0.8rem'>가입 {str(_pu.get('created_at',''))[:10]}</span>",
                        unsafe_allow_html=True,
                    )
                with _puc2:
                    if st.button("✅ 승인", key=f"approve_{_pu['id']}", use_container_width=True, type="primary"):
                        db.approve_user(_pu["id"])
                        st.success(f"{_pu['name']}님 승인 완료!")
                        st.rerun()
                with _puc3:
                    if st.button("❌ 거절", key=f"reject_{_pu['id']}", use_container_width=True):
                        db.reject_user(_pu["id"])
                        st.warning(f"{_pu['name']}님 계정 삭제")
                        st.rerun()
            st.markdown("---")
        st.markdown(
            "<p style='color:#718096;font-size:0.9rem;margin-top:-0.5rem'>"
            "가입 회원을 조회하고 설정을 관리합니다. 관리자만 접근 가능합니다.</p>",
            unsafe_allow_html=True,
        )

        _all_users = db.get_all_users()
        _total_u = len(_all_users)
        _active_u = sum(1 for u in _all_users if not u.get("emergency_stop"))

        _uc1, _uc2, _uc3 = st.columns(3)
        with _uc1:
            st.markdown(
                f"<div style='background:#1a3350;border:1px solid #1e4a78;border-radius:8px;"
                f"padding:1rem;text-align:center'>"
                f"<div style='color:#718096;font-size:0.75rem'>전체 사용자</div>"
                f"<div style='color:#0ea5e9;font-size:1.6rem;font-weight:700'>{_total_u}</div></div>",
                unsafe_allow_html=True,
            )
        with _uc2:
            st.markdown(
                f"<div style='background:#1a3350;border:1px solid #1e4a78;border-radius:8px;"
                f"padding:1rem;text-align:center'>"
                f"<div style='color:#718096;font-size:0.75rem'>활성 운용 중</div>"
                f"<div style='color:#48bb78;font-size:1.6rem;font-weight:700'>{_active_u}</div></div>",
                unsafe_allow_html=True,
            )
        with _uc3:
            _stopped_u = _total_u - _active_u
            st.markdown(
                f"<div style='background:#1a3350;border:1px solid #1e4a78;border-radius:8px;"
                f"padding:1rem;text-align:center'>"
                f"<div style='color:#718096;font-size:0.75rem'>긴급정지</div>"
                f"<div style='color:#e53e3e;font-size:1.6rem;font-weight:700'>{_stopped_u}</div></div>",
                unsafe_allow_html=True,
            )

        st.markdown("<br>", unsafe_allow_html=True)

        # 사용자 목록 테이블
        if _all_users:
            _risk_icon = {"conservative": "🛡️", "balanced": "⚖️", "aggressive": "⚔️"}
            for _usr in _all_users:
                _is_me    = _usr["id"] == _u["id"]
                _stop_ico = "🔴" if _usr.get("emergency_stop") else "🟢"
                _adm_ico  = "👑" if _usr.get("is_admin") else ""
                _me_tag   = " (나)" if _is_me else ""
                _risk_ico = _risk_icon.get(_usr.get("risk_profile", "balanced"), "⚖️")
                _cap_str  = f"{_usr.get('initial_capital', 1e8)/1e8:.0f}억"
                _created  = str(_usr.get("created_at", ""))[:10]

                with st.expander(
                    f"{_stop_ico} {_adm_ico} {_usr['name']}{_me_tag}  ·  "
                    f"{_usr['email']}  ·  {_risk_ico} 목표 {_usr.get('target_return',0.15):.0%}"
                    f"  ·  {_cap_str}  ·  가입 {_created}",
                    expanded=False,
                ):
                    _ec1, _ec2 = st.columns(2)
                    with _ec1:
                        _new_name = st.text_input("이름", value=_usr["name"],
                                                   key=f"uname_{_usr['id']}")
                        _new_ret  = st.slider("목표 수익률", 5, 50,
                                              int(_usr.get("target_return", 0.15) * 100),
                                              format="%d%%", key=f"uret_{_usr['id']}")
                        _new_risk = st.selectbox(
                            "투자 성향",
                            ["conservative", "balanced", "aggressive"],
                            index=["conservative", "balanced", "aggressive"].index(
                                _usr.get("risk_profile", "balanced")
                            ),
                            key=f"urisk_{_usr['id']}",
                        )
                    with _ec2:
                        _new_cap = st.number_input(
                            "초기 투자금 (원)", value=float(_usr.get("initial_capital", 1e8)),
                            step=1e7, min_value=1e7, key=f"ucap_{_usr['id']}"
                        )
                        _new_stop = st.toggle(
                            "🔴 긴급정지", value=bool(_usr.get("emergency_stop")),
                            key=f"ustop_{_usr['id']}"
                        )

                    if st.button("✅ 설정 저장", key=f"usave_{_usr['id']}"):
                        db.update_user_settings(
                            user_id=_usr["id"],
                            name=_new_name,
                            target_return=_new_ret / 100.0,
                            risk_profile=_new_risk,
                            initial_capital=float(_new_cap),
                            emergency_stop=_new_stop,
                        )
                        st.success(f"✅ {_new_name}님 설정이 업데이트되었습니다.")
                        st.rerun()

        else:
            st.info("가입된 사용자가 없습니다.")

        # 관리자 전용: 전체 사용자 병렬 사이클 실행
        st.markdown("---")
        st.markdown("#### ⚡ 전체 사용자 병렬 매매 사이클")
        st.caption("모든 활성 사용자의 비서실장을 동시에 실행합니다 (ThreadPoolExecutor 병렬 처리)")
        if st.button("🚀 전체 사용자 동시 실행", key="multi_user_cycle_btn", type="primary"):
            with st.spinner(f"{_active_u}명 사용자 병렬 사이클 실행 중..."):
                try:
                    from TradingEngine import TradingEngine as _TE
                    _mt_engine = _TE(config)
                    _mt_results = _mt_engine.run_multi_user_cycle(max_workers=4)
                    _ok  = sum(1 for r in _mt_results if not r.get("error"))
                    _err = sum(1 for r in _mt_results if r.get("error"))
                    st.success(f"✅ 완료 — 성공 {_ok}명 / 실패 {_err}명")
                    for _mr in _mt_results:
                        _ico = "✅" if not _mr.get("error") else "❌"
                        st.markdown(
                            f"  {_ico} **{_mr['user_name']}** (id={_mr['user_id']}) — "
                            f"체결 {_mr['result'].get('trades_executed', 0)}건 "
                            f"| 신호 {_mr['result'].get('signals_generated', 0)}개"
                            + (f" | ⚠️ {_mr['error']}" if _mr.get("error") else "")
                        )
                except Exception as _me:
                    st.error(f"실행 오류: {_me}")


# ── 자동 새로고침 (페이지 최하단에서 sleep → rerun) ─────────
if st.session_state.get("auto_refresh_toggle", True):
    _refresh_sec = st.session_state.get("refresh_interval", 60)
    time.sleep(_refresh_sec)
    st.rerun()
