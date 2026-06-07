"""
카카오 OAuth 2.0 + 카카오톡 메시지 헬퍼
- 인증 URL 생성 / code → token 교환 / 사용자 정보 조회
- 카카오톡 나에게 보내기 (talk_message scope)
"""
import os
import secrets
import urllib.parse
import requests

KAKAO_REST_API_KEY:    str = os.environ.get("KAKAO_REST_API_KEY", "")
KAKAO_CLIENT_SECRET:   str = os.environ.get("KAKAO_CLIENT_SECRET", "")

_REPLIT_DOMAIN = os.environ.get("REPLIT_DOMAINS", "localhost:5000").split(",")[0].strip()
REDIRECT_URI   = f"https://{_REPLIT_DOMAIN}/"

_AUTH_URL  = "https://kauth.kakao.com/oauth/authorize"
_TOKEN_URL = "https://kauth.kakao.com/oauth/token"
_ME_URL    = "https://kapi.kakao.com/v2/user/me"
_MSG_URL   = "https://kapi.kakao.com/v2/api/talk/memo/default/send"


def is_configured() -> bool:
    return bool(KAKAO_REST_API_KEY)


def make_state() -> str:
    return secrets.token_hex(16)


def get_auth_url(state: str) -> str:
    """카카오 로그인 URL (scope: 프로필 + 이메일 + 카카오톡 메시지)"""
    params = {
        "client_id":     KAKAO_REST_API_KEY,
        "redirect_uri":  REDIRECT_URI,
        "response_type": "code",
        "state":         state,
        "scope":         "profile_nickname,talk_message",
    }
    return f"{_AUTH_URL}?{urllib.parse.urlencode(params)}"


def exchange_code(code: str) -> dict | None:
    """authorization_code → access_token. 실패 시 {"_error": ...} 반환."""
    try:
        payload: dict = {
            "grant_type":   "authorization_code",
            "client_id":    KAKAO_REST_API_KEY,
            "redirect_uri": REDIRECT_URI,
            "code":         code,
        }
        if KAKAO_CLIENT_SECRET:
            payload["client_secret"] = KAKAO_CLIENT_SECRET
        r = requests.post(_TOKEN_URL, data=payload, timeout=10)
        body = r.json() if r.content else {}
        if not r.ok:
            return {"_error": f"HTTP {r.status_code} — {body}"}
        return body
    except Exception as _exc:
        return {"_error": str(_exc)}


def get_user_info(access_token: str) -> dict | None:
    """
    access_token → 사용자 정보
    반환: {"kakao_id": str, "name": str, "email": str}
    """
    try:
        r = requests.get(
            _ME_URL,
            headers={"Authorization": f"Bearer {access_token}"},
            timeout=10,
        )
        r.raise_for_status()
        data    = r.json()
        kid     = str(data.get("id", ""))
        account = data.get("kakao_account", {})
        props   = data.get("properties", {})
        email   = account.get("email") or f"kakao_{kid}@kakao.local"
        name    = (
            props.get("nickname")
            or account.get("profile", {}).get("nickname")
            or "카카오사용자"
        )
        return {"kakao_id": kid, "name": name, "email": email}
    except Exception:
        return None


def send_message(access_token: str, title: str, body: str, link_url: str = "") -> bool:
    """
    카카오톡 나에게 보내기 (피드 템플릿).
    성공: True / 실패: False
    """
    if not access_token:
        return False
    link_url = link_url or f"https://{_REPLIT_DOMAIN}/"
    template = {
        "object_type": "feed",
        "content": {
            "title":       title,
            "description": body,
            "link": {
                "web_url":        link_url,
                "mobile_web_url": link_url,
            },
        },
        "buttons": [
            {
                "title": "대시보드 열기",
                "link":  {"web_url": link_url, "mobile_web_url": link_url},
            }
        ],
    }
    try:
        import json
        r = requests.post(
            _MSG_URL,
            headers={"Authorization": f"Bearer {access_token}"},
            data={"template_object": json.dumps(template, ensure_ascii=False)},
            timeout=10,
        )
        return r.status_code == 200
    except Exception:
        return False


def send_trade_alert(access_token: str, signals: list[dict]) -> bool:
    """거래 신호 요약을 카카오톡으로 전송"""
    if not signals:
        return False
    lines = []
    for s in signals[:5]:
        action = s.get("action", "")
        ticker = s.get("ticker", "")
        agent  = s.get("agent", "")
        price  = s.get("price", 0)
        emoji  = "🟢" if action == "BUY" else "🔴" if action == "SELL" else "⚪"
        lines.append(f"{emoji} {action} {ticker} ({agent}) @{price:,.0f}원")
    if len(signals) > 5:
        lines.append(f"… 외 {len(signals)-5}건")
    body = "\n".join(lines)
    return send_message(access_token, "📈 AI 퀀트 거래 신호", body)


def send_risk_alert(access_token: str, event: str, detail: str) -> bool:
    """리스크 이벤트 알림 전송"""
    return send_message(access_token, f"⚠️ 리스크 경보: {event}", detail)


def send_cycle_summary(access_token: str, result: dict) -> bool:
    """분석 사이클 완료 요약 전송"""
    regime  = result.get("regime", "방어")
    signals = result.get("signals_generated", 0)
    pnl     = result.get("daily_pnl_pct", 0.0) or 0.0
    regime_emoji = {"공격": "⚔️", "방어": "🛡️", "전시": "🚨"}.get(regime, "📊")
    body = (
        f"{regime_emoji} 레짐: {regime}\n"
        f"📊 신호: {signals}건\n"
        f"💰 당일 손익: {pnl:+.2%}"
    )
    return send_message(access_token, "🤖 AI 퀀트 분석 완료", body)


# ──────────────────────────────────────────────────────────────
# 4대 보고서 전용 함수 (규칙 기반 고정 템플릿 — AI 생성 금지)
# ──────────────────────────────────────────────────────────────

_AGENT_LABELS = {
    "value_finder":  "💎 밸류파인더",
    "trend_rider":   "📈 트렌드라이더",
    "swing_master":  "🎢 스윙마스터",
    "micro_sniper":  "🎯 마이크로 스나이퍼",
}

_REGIME_EMOJI = {"공격": "🟢", "방어": "🟡", "전시": "🔴"}


def send_morning_briefing(
    access_token: str,
    regime: str,
    vix: float,
    confidence: float,
    ma_alignment: str,
    macd_signal: str,
    alloc_txt: str,
    sniper_fixed: int,
) -> bool:
    """
    1️⃣ 아침 정기 보고 — 개장 전 비서실장 브리핑
    규칙 기반 고정 템플릿, AI 문장 생성 없음.
    """
    r_icon = _REGIME_EMOJI.get(regime, "⚪")
    if regime == "전시":
        strategy = (
            "VIX 급등으로 전시 레짐이 선언되었습니다.\n"
            "모든 신규 진입을 차단하고 보유 자산을 현금으로 전환합니다.\n"
            "스나이퍼 정액 예산은 자동 회수됩니다."
        )
    elif regime == "방어":
        strategy = (
            f"VIX {vix:.1f}로 시장에 경계 심리가 퍼지고 있습니다.\n"
            f"예산을 보수적으로 운용하며 스나이퍼는 정액 "
            f"{sniper_fixed:,}원으로 독립 가동합니다.\n"
            f"트렌드라이더 신규 진입을 억제하고 스윙마스터 위주로 운용합니다."
        )
    else:
        strategy = (
            f"VIX {vix:.1f} 안정 구간, 전략 전면 가동합니다.\n"
            f"스나이퍼는 정액 {sniper_fixed:,}원으로 독립 스캘핑합니다.\n"
            f"{alloc_txt}"
        )

    body = (
        f"대표님, 좋은 아침입니다.\n\n"
        f"{r_icon} 오늘의 시장 모드: [{regime} 레짐] (신뢰도 {confidence:.0%})\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n"
        f"📐 MA 배열: {ma_alignment}\n"
        f"📉 MACD:  {macd_signal}\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n"
        f"🛡️ 오늘의 운용 전략\n{strategy}\n\n"
        f"자산 배분: {alloc_txt}"
    )
    return send_message(access_token, "🌅 비서실장 모닝 브리핑", body)


def send_trade_execution(
    access_token: str,
    action: str,
    ticker: str,
    ticker_name: str,
    agent_key: str,
    amount: float,
    reason: str,
    realized_pnl: float = 0.0,
) -> bool:
    """
    2️⃣ 실시간 거래 내역 보고 — 에이전트 매매 알림
    규칙 기반 고정 템플릿, AI 문장 생성 없음.
    """
    agent_label = _AGENT_LABELS.get(agent_key, agent_key)
    disp_name   = ticker_name or ticker

    if action == "BUY":
        title = f"🛒 [{agent_label} 매수 알림]"
        body  = (
            f"종목: {disp_name} ({ticker})\n"
            f"진입 금액: {amount:,.0f}원\n"
            f"━━━━━━━━━━━━━━━━━━━━━\n"
            f"📈 매수 이유\n{reason[:200]}\n\n"
            f"목표가 도달 또는 손절선 이탈 시 자동 매도합니다."
        )
    else:
        pnl_sign = "+" if realized_pnl >= 0 else ""
        title = f"💰 [{agent_label} 매도 알림]"
        body  = (
            f"종목: {disp_name} ({ticker})\n"
            f"청산 금액: {amount:,.0f}원\n"
            f"━━━━━━━━━━━━━━━━━━━━━\n"
            f"📉 매도 이유\n{reason[:200]}\n\n"
            f"✅ 실현 손익: {pnl_sign}{realized_pnl:,.0f}원"
        )
    return send_message(access_token, title, body)


def send_retire_alert(
    access_token: str,
    agent_key: str,
    target_pct: float,
    actual_pct: float,
    realized_krw: int,
    budget_krw: int,
    trade_count: int,
) -> bool:
    """
    3️⃣ 에이전트 조기 퇴근 보고 — 목표 수익 달성 알림
    결정론적 계산값을 그대로 삽입. AI 문장 생성 없음.
    """
    agent_label = _AGENT_LABELS.get(agent_key, agent_key)
    body = (
        f"🔒 수익 락인(Lock-in) 완료\n\n"
        f"{agent_label}이(가) 금일 목표 수익을 달성하고 조기 퇴근합니다.\n\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n"
        f"🎯 목표 수익률: {target_pct:.1%}\n"
        f"✅ 실제 달성:  {actual_pct:.1%}\n"
        f"💰 실현 손익:  {realized_krw:+,}원\n"
        f"📦 배정 예산:  {budget_krw:,}원\n"
        f"🔁 거래 횟수:  {trade_count}건\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"오늘 남은 시간 동안 {agent_label}은(는)\n"
        f"뇌동매매 방지를 위해 신규 진입을 전면 차단합니다.\n\n"
        f"📊 [Ground Truth 검증]\n"
        f"계산식: {realized_krw:,}원 ÷ {budget_krw:,}원 = {actual_pct:.4%}\n"
        f"LLM 개입: 없음 (순수 파이썬 사칙연산)"
    )
    return send_message(
        access_token,
        f"🏆 [{agent_label}] 조기 퇴근 — 목표 {target_pct:.1%} 달성!",
        body,
    )


def send_kill_switch_kakao(
    access_token: str,
    reason: str,
    positions_closed: int = 0,
    total_value: float = 0.0,
) -> bool:
    """
    4️⃣ 긴급 통제 보고 — 킬스위치 발동 알림
    규칙 기반 고정 템플릿, AI 문장 생성 없음.
    """
    body = (
        f"⚠️ 시스템이 아래 사유로 긴급 종료되었으며,\n"
        f"전량 청산이 완료되었습니다.\n\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n"
        f"🔴 발동 사유: {reason}\n"
        f"📦 청산 포지션: {positions_closed}개\n"
        f"💰 현금 전환: {total_value:,.0f}원\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"현재 모든 에이전트 가동이 중단되었으며\n"
        f"자산은 100% 현금으로 대기 중입니다.\n"
        f"대시보드에 접속하여 상태를 확인해 주십시오."
    )
    return send_message(access_token, "🚨 비서실장 긴급 통제 발동", body)
