"""
TradeTranslator.py — 전문 용어 → 일상어 매매 번역기
════════════════════════════════════════════════════════
에이전트가 남긴 기술적 매매 이유(RSI, MACD, 볼린저 등)를
일반인이 이해할 수 있는 자연어로 변환합니다.
"""

from __future__ import annotations
from datetime import datetime, date

AGENT_PERSONA = {
    "value_finder":  ("밸류파인더",  "가치투자"),
    "trend_rider":   ("트렌드라이더", "추세매매"),
    "swing_master":  ("스윙마스터",  "단기 반등"),
}

# ── 내부 헬퍼 ──────────────────────────────────────────────

def _extract_val(part: str) -> str:
    """'RSI과매도=19.6' 또는 'RSI과매도(19.6)' → '19.6'"""
    if "=" in part:
        return part.split("=", 1)[-1].strip()
    if "(" in part and ")" in part:
        return part[part.index("(") + 1: part.index(")")]
    return ""


def _detect(parts: list[str], keywords: list[str]) -> bool:
    return any(any(kw in p for kw in keywords) for p in parts)


# ── 매수 번역 ──────────────────────────────────────────────

def translate_buy(agent_name: str, stock_name: str, reason: str) -> str:
    """
    매수 이유 → 일상어 한국어
    Returns: (매수 이유 문장, 향후 매도 조건 문장)
    """
    parts = [p.strip() for p in reason.split("|") if p.strip()]

    has_bb    = _detect(parts, ["BB하단", "볼린저"])
    has_rsi   = _detect(parts, ["RSI과매도", "RSI"])
    has_macd  = _detect(parts, ["MACD상승", "MACD골든"])
    has_ma    = _detect(parts, ["MA위", "골든크로스", "이평선"])
    has_magic = _detect(parts, ["마법공식"])
    has_f     = _detect(parts, ["F스코어", "피오트로스키"])

    rsi_val = ""
    for p in parts:
        if "RSI" in p:
            v = _extract_val(p)
            if v:
                try:
                    rsi_val = f"(RSI {float(v):.0f})"
                except ValueError:
                    pass
            break

    if agent_name == "swing_master":
        buy_reason = (
            f"사람들의 과도한 공포심으로 {stock_name} 주가가 비정상적으로 급락했습니다{rsi_val}. "
            "볼린저 밴드의 '통계적 하한선' 아래까지 떨어진 상태로, 더 이상 버티기 힘든 과매도 구간입니다. "
            "이런 상황에서는 대부분 주가가 정상 범위로 '튕겨 오르는' 반등이 나타납니다."
        )
        sell_cond = (
            "주가가 볼린저 밴드 중앙선(20일 평균가)까지 회복되거나, "
            "단기 과열(RSI 70 이상) 신호가 나타나면 즉시 매도하겠습니다."
        )

    elif agent_name == "trend_rider":
        ma_desc = "단기·장기 이동평균선이 '골든크로스'를 이루며 " if has_ma else ""
        macd_desc = "MACD 모멘텀까지 상승으로 전환되어 " if has_macd else ""
        buy_reason = (
            f"{stock_name}에 강한 상승 파도가 시작됐습니다. "
            f"{ma_desc}{macd_desc}"
            "상승 추세가 확인된 만큼 이 파도에 올라타기 위해 매수했습니다. "
            "추세 추종이란 오르는 주식은 계속 오르려는 성질을 이용하는 전략입니다."
        )
        sell_cond = (
            "상승 파도가 꺾이는 신호(이동평균선 역배열 또는 MACD 하락 전환)가 나타나면 "
            "미련 없이 즉시 매도하겠습니다."
        )

    elif agent_name == "value_finder":
        magic_desc = (
            "마법공식(수익성 + 저평가 동시 충족) 상위 종목으로 선정되었고, "
            if has_magic else ""
        )
        f_desc = "재무건전성 점수(피오트로스키 F스코어)도 우수합니다. " if has_f else ""
        buy_reason = (
            f"{stock_name}은 재무적으로 탄탄한데도 시장에서 본래 가치보다 싸게 거래되고 있습니다. "
            f"{magic_desc}{f_desc}"
            "빚은 줄고 현금은 쌓이며 수익성이 개선되고 있는 기업입니다. "
            "시장이 제대로 평가하기 시작할 때 수익을 실현하겠습니다."
        )
        sell_cond = (
            "3개월 후 재평가 시 더 좋은 종목이 발견되거나, "
            "기업 실적이 악화(F스코어 하락)되면 교체합니다."
        )

    else:
        buy_reason = f"{stock_name} 매수: {' / '.join(parts[:2])}"
        sell_cond = "목표가 도달 또는 손절 기준 이탈 시 매도합니다."

    return buy_reason, sell_cond


# ── 매도 번역 ──────────────────────────────────────────────

def translate_sell(
    agent_name: str,
    stock_name: str,
    reason: str,
    realized_pnl_pct: float | None = None,
) -> str:
    """매도 이유 → 일상어 한국어"""
    parts = [p.strip() for p in reason.split("|") if p.strip()]

    has_stoploss = _detect(parts, ["스탑로스", "손절", "비상청산"])
    has_profit   = _detect(parts, ["이익실현", "목표가"])
    has_dead     = _detect(parts, ["데드크로스", "MA아래", "역배열"])
    has_bb_mid   = _detect(parts, ["BB중앙", "볼린저중앙"])

    pnl_str = ""
    if realized_pnl_pct is not None:
        sign = "+" if realized_pnl_pct >= 0 else ""
        word = "실현 이익" if realized_pnl_pct >= 0 else "실현 손실"
        pnl_str = f" 이번 거래로 **{sign}{realized_pnl_pct:.1f}%**의 {word}을 확정했습니다."

    if has_stoploss:
        core = (
            "설정된 손절 기준(매입가 대비 일정 % 하락)에 도달했습니다. "
            "손실이 더 커지기 전에 원칙에 따라 매도했습니다. "
            "작은 손실로 막는 것이 큰 손실을 피하는 가장 확실한 방법입니다."
        )
    elif has_profit:
        if agent_name == "swing_master":
            core = (
                f"예상대로 {stock_name}이 반등하여 목표 가격(볼린저 중앙선)에 도달했습니다. "
                "욕심 부리지 않고 계획한 수익을 확정했습니다."
            )
        else:
            core = (
                f"{stock_name}이 목표 수익률에 도달했습니다. "
                "계획한 이익을 실현했습니다."
            )
    elif has_dead and agent_name == "trend_rider":
        core = (
            f"{stock_name}의 상승 파도가 꺾이고 이동평균선이 하락 배열로 전환됐습니다. "
            "더 큰 손실을 방지하기 위해 신속하게 청산했습니다."
        )
    elif agent_name == "value_finder":
        core = (
            f"3개월 보유 기간 만료 또는 더 우수한 가치주가 발견되어 "
            f"{stock_name}을 정리했습니다."
        )
    elif agent_name == "swing_master":
        core = (
            f"{stock_name}이 반등하여 단기 과열 구간에 진입했습니다. "
            "짧게 치고 빠지는 전략으로 수익을 확정했습니다."
        )
    else:
        core = " / ".join(parts[:2]) if parts else "매도 조건 충족"

    return core + pnl_str


# ── 에이전트 일일 활약 요약 (브리핑용) ────────────────────────

def agent_daily_summary(
    trades_today: list[dict],
    stock_names: dict[str, str],
) -> dict[str, dict]:
    """
    오늘 거래 목록 → 에이전트별 자연어 활약 요약
    Returns:
        {agent_name: {label, strategy, headline, detail, realized_pnl}}
    """
    from collections import defaultdict

    grouped: dict[str, list] = defaultdict(list)
    for t in trades_today:
        grouped[t.get("agent_name", "unknown")].append(t)

    result = {}
    for agent, trades in grouped.items():
        label, strategy = AGENT_PERSONA.get(agent, ("AI 에이전트", "자동매매"))
        buys  = [t for t in trades if t.get("action") == "BUY"]
        sells = [t for t in trades if t.get("action") == "SELL"]

        total_pnl = 0.0
        sell_descs = []
        for t in sells:
            name = stock_names.get(t.get("ticker", ""), t.get("ticker", ""))
            amt  = t.get("total_amount", 0) or 0
            sell_descs.append(f"{name} 매도")
            # realized_pnl 필드가 있으면 집계
            total_pnl += t.get("realized_pnl", 0) or 0

        buy_descs = []
        for t in buys:
            name = stock_names.get(t.get("ticker", ""), t.get("ticker", ""))
            buy_descs.append(f"{name} 매수")

        all_acts = buy_descs + sell_descs

        if not all_acts:
            headline = f"{label}은 오늘 거래를 하지 않고 시장을 관망했습니다."
            detail   = "신호 조건 미충족으로 대기 중입니다."
        else:
            acts_str = ", ".join(all_acts)
            if total_pnl > 0:
                pnl_desc = f" 오늘 실현 이익: +{total_pnl:,.0f}원"
            elif total_pnl < 0:
                pnl_desc = f" 오늘 실현 손실: {total_pnl:,.0f}원"
            else:
                pnl_desc = ""
            headline = f"{label}이 오늘 {acts_str}를 체결했습니다.{pnl_desc}"

            if agent == "swing_master" and buys:
                detail = "과매도 종목의 반등을 노린 단기 매수입니다."
            elif agent == "swing_master" and sells:
                detail = "반등 목표가 달성 후 수익을 확정했습니다."
            elif agent == "trend_rider" and buys:
                detail = "상승 추세 확인 후 파도에 올라탔습니다."
            elif agent == "trend_rider" and sells:
                detail = "추세 전환 신호 감지 후 신속히 청산했습니다."
            elif agent == "value_finder" and buys:
                detail = "저평가 우량주를 발굴하여 장기 투자로 편입했습니다."
            elif agent == "value_finder" and sells:
                detail = "보유 기간 만료 또는 더 좋은 종목으로 교체했습니다."
            else:
                detail = acts_str

        result[agent] = {
            "label":        label,
            "strategy":     strategy,
            "headline":     headline,
            "detail":       detail,
            "realized_pnl": total_pnl,
            "buy_count":    len(buys),
            "sell_count":   len(sells),
        }

    return result


# ── 목표 수익률 → 에이전트 배분 권장 ─────────────────────────

def recommend_allocation_for_target(
    target_pct: float,
    current_regime: str,
    vix: float = 20.0,
) -> tuple[dict, str, str]:
    """
    목표 연간 수익률(%) + 현재 레짐 → (배분 비중, 비서실장 조언, 위험 등급)

    Returns:
        alloc  : {value_finder, trend_rider, swing_master, cash}
        advice : 비서실장 조언 자연어
        tier   : '안정' | '균형' | '공격' | '초공격'
    """
    # 전시 모드 우선
    if current_regime == "전시" or vix >= 30:
        alloc  = {"value_finder": 0.10, "trend_rider": 0.00,
                  "swing_master": 0.10, "cash": 0.80}
        advice = (
            f"대표님, 현재 VIX가 {vix:.1f}로 시장 공포 구간(전시 레짐)입니다. "
            "목표 수익률에 관계없이 지금은 현금을 80% 보유하며 안전을 최우선으로 해야 합니다. "
            "폭풍이 지나간 뒤 다시 공격적으로 움직이는 것이 현명합니다."
        )
        return alloc, advice, "전시"

    # 수익률 구간별 기본 배분
    if target_pct <= 12:
        tier = "안정"
        base = {"value_finder": 0.50, "trend_rider": 0.10,
                "swing_master": 0.25, "cash": 0.15}
        risk_note = (
            "은행 이자보다 높으면서도 잃지 않는 투자를 최우선으로 설정했습니다. "
            "우량 가치주(밸류파인더)를 주축으로, 단기 반등(스윙마스터)으로 보조 수익을 노립니다. "
            "MDD(최대 낙폭) 허용치를 낮게 유지해 원금 보전을 우선합니다."
        )
        caution = ""
    elif target_pct <= 20:
        tier = "균형"
        base = {"value_finder": 0.35, "trend_rider": 0.25,
                "swing_master": 0.25, "cash": 0.15}
        risk_note = (
            "성장과 안정을 균형 있게 배분했습니다. "
            "가치주(밸류파인더)와 추세 종목(트렌드라이더)을 고르게 운용합니다. "
            "시장이 흔들릴 때 약 -10~15% 수준의 일시적 하락은 감내해야 할 수 있습니다."
        )
        caution = ""
    elif target_pct <= 30:
        tier = "공격"
        base = {"value_finder": 0.20, "trend_rider": 0.50,
                "swing_master": 0.20, "cash": 0.10}
        risk_note = (
            f"연 {target_pct}%는 상당히 공격적인 목표입니다. "
            "상승 추세 종목에 집중하는 트렌드라이더 비중을 50%로 높였습니다. "
            "좋은 장에서 큰 수익을 낼 수 있지만, 시장이 하락 시 -20% 이상 손실 가능성을 "
            "미리 각오해야 합니다."
        )
        caution = f"⚠️ 연 {target_pct}% 목표는 상당한 리스크를 동반합니다."
    else:
        tier = "초공격"
        base = {"value_finder": 0.10, "trend_rider": 0.70,
                "swing_master": 0.15, "cash": 0.05}
        risk_note = (
            f"대표님, 연 {target_pct}%는 현재 횡보장에서 극히 공격적인 목표입니다. "
            "이 수익을 달성하려면 트렌드라이더가 크게 이기는 장세가 와야 합니다. "
            "반대로 시장이 역추세를 탈 경우 -30% 이상 손실도 감내해야 합니다. "
            "VIX 민감도를 낮춰 웬만한 하락에도 버티게 설정합니다."
        )
        caution = f"⚠️ 연 {target_pct}% 목표는 매우 높은 리스크를 동반합니다. 신중히 결정하세요."

    # 방어 레짐이면 현금 비중 5%p 추가 보수 조정
    alloc = base.copy()
    if current_regime == "방어":
        alloc["cash"] = min(alloc["cash"] + 0.05, 0.40)
        adj = alloc["cash"] - base["cash"]
        alloc["trend_rider"] = max(alloc["trend_rider"] - adj, 0.05)

    # 합계 보정 (부동소수점 오차)
    total = sum(alloc.values())
    if abs(total - 1.0) > 0.001:
        alloc["cash"] += (1.0 - total)

    regime_note = {
        "공격": "현재 공격 레짐으로 목표 배분을 그대로 적용합니다.",
        "방어": "현재 방어 레짐이므로 현금 비중을 5%p 더 확보했습니다.",
    }.get(current_regime, "")

    advice = f"{risk_note}"
    if regime_note:
        advice += f" {regime_note}"
    if caution:
        advice = caution + "\n\n" + advice

    return alloc, advice, tier
