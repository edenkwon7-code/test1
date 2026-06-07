"""
통합 컨트롤타워 - 비서실장 엔진 (Chief of Staff Engine)
VIX, 이동평균 배열, MACD를 분석해 시장을 3단계로 구분하고
하위 에이전트들의 가동률과 예산을 제어합니다.
"""

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import Enum
from typing import Optional

import numpy as np
import pandas as pd
from KoreaDataProvider import get_provider as _get_kr_provider

from config_loader import load_config

logger = logging.getLogger(__name__)


class MarketRegime(Enum):
    OFFENSIVE = "공격"
    DEFENSIVE = "방어"
    WARTIME = "전시"


@dataclass
class RegimeSignal:
    regime: MarketRegime
    vix: float
    vix_signal: str
    ma_alignment: str
    macd_signal: str
    confidence: float
    timestamp: datetime
    notes: str


@dataclass
class AgentAllocation:
    value_finder: float
    trend_rider: float
    swing_master: float
    micro_sniper: float
    cash: float
    sniper_fixed_amount: float = 0.0   # 스나이퍼 고정 예산 (원화, 비율 배분에서 독립)


def get_regime_briefing(
    vix: float,
    ma_alignment: str,
    macd_signal: str,
    regime: str,
    confidence: float,
) -> str:
    """
    VIX · MA배열 · MACD 지표를 조합하여
    비서실장의 자연어 한국어 브리핑 문장을 생성합니다.
    """
    # ── VIX 번역 ────────────────────────────────────────────
    if vix >= 30:
        vix_text = (
            f"공포지수(VIX)가 {vix:.1f}로 급등하여 "
            "시장이 극단적인 공포 상태에 빠졌습니다."
        )
    elif vix >= 20:
        vix_text = (
            f"공포지수(VIX)가 {vix:.1f}로 상승하여 "
            "시장에 경계 심리가 퍼지고 변동성이 커지고 있습니다."
        )
    else:
        vix_text = (
            f"공포지수(VIX)가 {vix:.1f}로 안정적인 수준을 유지하고 있습니다."
        )

    # ── MA 배열 번역 ─────────────────────────────────────────
    ma_map = {
        "BULLISH":           "코스피 지수는 장·단기 이평선이 정배열을 이루며 뚜렷한 상승 추세를 타고 있습니다.",
        "BEARISH":           "코스피 지수가 이평선 역배열에 진입하여 완연한 하락 장세로 전환되었습니다.",
        "MIXED":             "코스피 이평선들이 얽혀 방향성이 없는 횡보(박스권) 장세입니다.",
        "UNKNOWN":           "이평선 분석 데이터를 집계하고 있습니다.",
        "INSUFFICIENT_DATA": "이평선 분석에 충분한 데이터가 없어 신중히 접근합니다.",
    }
    ma_text = ma_map.get(ma_alignment, f"이평선 상태: {ma_alignment}")

    # ── MACD 번역 ────────────────────────────────────────────
    macd_map = {
        "BULLISH_MOMENTUM": "여기에 상승 모멘텀(MACD)까지 더해져 매수세가 아주 강합니다.",
        "BEARISH_MOMENTUM": "하락 모멘텀이 거세져 추가 하락 위험이 높습니다.",
        "WEAKENING_BULL":   "다만, 상승 에너지가 점차 둔화되고 있어 추세가 꺾일 조짐이 보입니다.",
        "WEAKENING_BEAR":   "하락 에너지가 줄어들고 있어 반등 가능성을 주시해야 합니다.",
        "UNKNOWN":          "",
    }
    macd_text = macd_map.get(macd_signal, "")

    # ── 레짐별 행동 결론 ─────────────────────────────────────
    if regime in ("전시", "WARTIME"):
        action = (
            "따라서 시스템을 '🚨 전시 모드'로 전환합니다. "
            "현금 비중을 80%로 늘리고 신규 매수를 즉시 중단합니다. "
            "자산 방어가 최우선입니다."
        )
    elif regime in ("방어", "DEFENSIVE"):
        action = (
            "따라서 무리한 투자를 멈추고 '🟡 방어 모드'로 설정하여 "
            "예산을 보수적으로 축소합니다. "
            "트렌드라이더의 신규 진입을 제한하고 "
            "밸류파인더·스윙마스터 위주로 운용합니다."
        )
    else:
        action = (
            "시장 상황이 양호하여 '🟢 공격 모드'로 운용합니다. "
            "트렌드라이더와 밸류파인더 비중을 높여 수익 극대화를 추구합니다."
        )

    # ── 신뢰도 표현 ──────────────────────────────────────────
    if confidence >= 0.80:
        conf_text = f" (판단 신뢰도 {confidence:.0%} — 매우 확실)"
    elif confidence >= 0.60:
        conf_text = f" (판단 신뢰도 {confidence:.0%})"
    else:
        conf_text = f" (판단 신뢰도 {confidence:.0%} — 신호 혼조, 보수적 판단)"

    body = f"{vix_text} {ma_text}"
    if macd_text:
        body += f" {macd_text}"

    return f"대표님, {body}\n\n{action}{conf_text}"


def get_regime_memo(
    vix: float,
    ma_alignment: str,
    macd_signal: str,
    regime: str,
    confidence: float,
) -> tuple[str, dict]:
    """
    RegimeTranslator: 비서실장 자연어 브리핑 + Ground Truth 원본 데이터를 함께 반환.
    할루시네이션 방지 원칙: 외부 LLM 자유 생성 없음. 파이썬 연산 결과에
    매칭되는 조건문(If-Else) 기반 텍스트 템플릿만 조합.

    Returns
    -------
    briefing : str
        자연어 브리핑 문자열 (get_regime_briefing 위임)
    ground_truth : dict
        브리핑 생성의 뼈대가 된 실제 Raw Data — 가감 없이 노출
    """
    briefing = get_regime_briefing(vix, ma_alignment, macd_signal, regime, confidence)

    if vix >= 30:
        vix_level = "극단적 공포 (≥30) ← VIX 하드룰 서킷브레이커 발동"
    elif vix >= 20:
        vix_level = "경계 구간 (20~30) — 변동성 경고"
    else:
        vix_level = "안정 구간 (<20) — 정상 운용"

    if confidence >= 0.80:
        conf_label = "매우 확실 (≥80%)"
    elif confidence >= 0.60:
        conf_label = "보통 (60~80%)"
    else:
        conf_label = "혼조 신호 (<60%) — 보수적 판단 권장"

    ground_truth = {
        "VIX": round(vix, 2),
        "VIX_Level": vix_level,
        "Circuit_Breaker_Triggered": vix >= 30,
        "MA_Alignment": ma_alignment,
        "MACD_Signal": macd_signal,
        "Regime": regime,
        "Confidence": round(confidence, 4),
        "Confidence_Label": conf_label,
        "Analysis_At": datetime.now().isoformat(timespec="seconds"),
    }
    return briefing, ground_truth


def get_daily_performance_briefing(trades_today: list) -> str:
    """
    장 마감 후(15:32~) 4대 에이전트 당일 활약상 요약 브리핑.
    할루시네이션 방지: 조건문 기반 텍스트 템플릿만 사용 — LLM 없음.

    Parameters
    ----------
    trades_today : list[dict]
        당일 체결된 거래 목록. 각 dict에 agent_name, action, total_amount 필요.
    """
    agent_display = {
        "value_finder": "💎 밸류파인더",
        "trend_rider":  "📈 트렌드라이더",
        "swing_master": "🔄 스윙마스터",
        "micro_sniper": "🎯 마이크로스나이퍼",
    }

    today_str = datetime.now().strftime("%Y년 %m월 %d일")
    lines: list[str] = [f"📊 **비서실장 일일 마감 보고** — {today_str}"]
    total_realized = 0.0
    any_activity   = False

    for ak, aname in agent_display.items():
        ag_trades = [t for t in trades_today if t.get("agent_name") == ak]
        buys      = [t for t in ag_trades if t.get("action") == "BUY"]
        sells     = [t for t in ag_trades if t.get("action") == "SELL"]
        buy_amt   = sum(t.get("total_amount", 0) for t in buys)
        sell_amt  = sum(t.get("total_amount", 0) for t in sells)
        realized  = sell_amt - buy_amt

        if not ag_trades:
            verdict = "오늘 매매 신호 없음 — 관망 유지"
        else:
            any_activity = True
            buy_desc  = f"매수 {len(buys)}건 ({buy_amt:,.0f}원)" if buys else ""
            sell_desc = f"매도 {len(sells)}건 ({sell_amt:,.0f}원)" if sells else ""
            activity  = " / ".join(x for x in [buy_desc, sell_desc] if x)

            if realized > 0:
                verdict = f"{activity} → 실현 이익 **+{realized:,.0f}원** ✅"
            elif realized < 0:
                verdict = f"{activity} → 실현 손실 **{realized:,.0f}원** ⚠️"
            else:
                verdict = f"{activity} → 포지션 보유 중"

        total_realized += realized
        lines.append(f"  {aname}: {verdict}")

    lines.append("")
    if not any_activity:
        lines.append("📌 오늘은 매매 조건을 충족한 종목이 없어 전 에이전트가 관망했습니다.")
    elif total_realized > 0:
        lines.append(f"✅ 당일 총 실현 이익: **+{total_realized:,.0f}원** — 목표 달성")
    elif total_realized < 0:
        lines.append(f"⚠️ 당일 총 실현 손실: **{total_realized:,.0f}원** — 내일 재기를 기약합니다")
    else:
        lines.append("💼 당일 포지션 보유 중 — 미실현 손익으로 계상됩니다")

    lines.append("")
    lines.append("— 이상, 비서실장 마감 보고였습니다.")
    return "\n".join(lines)


class MarketRegimeAnalyzer:
    """시장 상태(레짐)를 분석하는 핵심 분석기"""

    def __init__(self, config: dict):
        self.cfg = config["chief_of_staff"]
        self.vix_ticker = config["universe"]["vix_ticker"]
        self.market_index = config.get("universe", {}).get("market_index", "KS11")
        self.vix_thresholds = self.cfg["market_regime"]["vix_thresholds"]
        self.ma_periods = self.cfg["market_regime"]["ma_periods"]
        self.macd_cfg = self.cfg["market_regime"]["macd"]
        self._cache = {}
        self._cache_time = None
        self._cache_ttl_minutes = 30

    def _fetch_market_data(self, ticker: str, period: str = "1y") -> pd.DataFrame:
        """
        시장 데이터 수집 — KoreaDataProvider 사용
        VIX(^VIX)는 yfinance 경유, 그 외 지수는 fdr 사용
        """
        cache_key = f"{ticker}_{period}"
        now = datetime.now()
        if (
            cache_key in self._cache
            and self._cache_time
            and (now - self._cache_time).seconds < self._cache_ttl_minutes * 60
        ):
            return self._cache[cache_key]

        provider = _get_kr_provider()
        try:
            if ticker == "^VIX":
                data = provider.get_vix_data(period=period)
            else:
                data = provider.get_price_data(ticker, period=period)
            if data is not None and not data.empty:
                self._cache[cache_key] = data
                self._cache_time = now
            return data if (data is not None and not data.empty) else pd.DataFrame()
        except Exception as e:
            logger.error(f"시장 데이터 수집 실패 [{ticker}]: {e}")
            return pd.DataFrame()

    def _analyze_vix(self, vix: float) -> str:
        if vix >= self.vix_thresholds["wartime"]:
            return "WARTIME"
        elif vix >= self.vix_thresholds["defensive"]:
            return "DEFENSIVE"
        else:
            return "OFFENSIVE"

    def _analyze_ma_alignment(self, close_series: pd.Series) -> str:
        """이동평균선 배열 분석: 단기 > 중기 > 장기 = 공격적 배열"""
        if len(close_series) < self.ma_periods["long"]:
            return "INSUFFICIENT_DATA"

        short = close_series.rolling(self.ma_periods["short"]).mean().iloc[-1]
        medium = close_series.rolling(self.ma_periods["medium"]).mean().iloc[-1]
        long = close_series.rolling(self.ma_periods["long"]).mean().iloc[-1]

        if short > medium > long:
            return "BULLISH"
        elif short < medium < long:
            return "BEARISH"
        else:
            return "MIXED"

    def _analyze_macd(self, close_series: pd.Series) -> str:
        """MACD 모멘텀 분석"""
        if len(close_series) < self.macd_cfg["slow"] + self.macd_cfg["signal"]:
            return "INSUFFICIENT_DATA"

        ema_fast = close_series.ewm(span=self.macd_cfg["fast"], adjust=False).mean()
        ema_slow = close_series.ewm(span=self.macd_cfg["slow"], adjust=False).mean()
        macd_line = ema_fast - ema_slow
        signal_line = macd_line.ewm(span=self.macd_cfg["signal"], adjust=False).mean()
        histogram = macd_line - signal_line

        latest_hist = histogram.iloc[-1]
        prev_hist = histogram.iloc[-2] if len(histogram) > 1 else 0

        if latest_hist > 0 and latest_hist > prev_hist:
            return "BULLISH_MOMENTUM"
        elif latest_hist < 0 and latest_hist < prev_hist:
            return "BEARISH_MOMENTUM"
        elif latest_hist > 0:
            return "WEAKENING_BULL"
        else:
            return "WEAKENING_BEAR"

    def analyze(self) -> RegimeSignal:
        """종합 시장 레짐 분석 수행"""
        now = datetime.now()

        # VIX 데이터
        vix_data = self._fetch_market_data(self.vix_ticker, period="3mo")
        if vix_data.empty:
            logger.warning("VIX 데이터를 가져올 수 없어 DEFENSIVE 레짐 기본값 적용")
            return RegimeSignal(
                regime=MarketRegime.DEFENSIVE,
                vix=20.0,
                vix_signal="DEFENSIVE",
                ma_alignment="UNKNOWN",
                macd_signal="UNKNOWN",
                confidence=0.3,
                timestamp=now,
                notes="VIX 데이터 수집 실패 - 방어 모드 기본 적용",
            )

        current_vix = float(np.asarray(vix_data["Close"].iloc[-1]).flat[0])
        vix_signal = self._analyze_vix(current_vix)

        # KOSPI 지수 데이터로 MA 배열, MACD 분석 (한국 시장 기준)
        spx_data = self._fetch_market_data(self.market_index, period="1y")
        if spx_data.empty:
            ma_alignment = "UNKNOWN"
            macd_signal = "UNKNOWN"
        else:
            close = spx_data["Close"].squeeze()
            ma_alignment = self._analyze_ma_alignment(close)
            macd_signal = self._analyze_macd(close)

        # 레짐 결정 로직 (가중 투표 방식)
        scores = {MarketRegime.OFFENSIVE: 0, MarketRegime.DEFENSIVE: 0, MarketRegime.WARTIME: 0}

        # VIX 기반 점수 (가중치 40%)
        if vix_signal == "WARTIME":
            scores[MarketRegime.WARTIME] += 2
        elif vix_signal == "DEFENSIVE":
            scores[MarketRegime.DEFENSIVE] += 2
        else:
            scores[MarketRegime.OFFENSIVE] += 2

        # VIX 30 이상이면 무조건 전시 (하드 룰)
        if current_vix >= self.vix_thresholds["wartime"]:
            final_regime = MarketRegime.WARTIME
            confidence = 0.95
            notes = f"VIX={current_vix:.1f} (≥30) → 소프트웨어 서킷 브레이커 발동 조건 충족"
        else:
            # MA 배열 기반 점수 (가중치 35%)
            if ma_alignment == "BULLISH":
                scores[MarketRegime.OFFENSIVE] += 1.5
            elif ma_alignment == "BEARISH":
                scores[MarketRegime.DEFENSIVE] += 1.5
            else:
                scores[MarketRegime.DEFENSIVE] += 0.5

            # MACD 기반 점수 (가중치 25%)
            if macd_signal in ("BULLISH_MOMENTUM",):
                scores[MarketRegime.OFFENSIVE] += 1
            elif macd_signal in ("BEARISH_MOMENTUM",):
                scores[MarketRegime.DEFENSIVE] += 1
            elif macd_signal == "WEAKENING_BULL":
                scores[MarketRegime.OFFENSIVE] += 0.3
                scores[MarketRegime.DEFENSIVE] += 0.7
            else:
                scores[MarketRegime.DEFENSIVE] += 0.5

            final_regime = max(scores, key=scores.get)
            total_score = sum(scores.values())
            confidence = scores[final_regime] / total_score if total_score > 0 else 0.33
            notes = f"VIX={current_vix:.1f} | MA={ma_alignment} | MACD={macd_signal}"

        signal = RegimeSignal(
            regime=final_regime,
            vix=current_vix,
            vix_signal=vix_signal,
            ma_alignment=ma_alignment,
            macd_signal=macd_signal,
            confidence=round(confidence, 3),
            timestamp=now,
            notes=notes,
        )

        logger.info(f"[비서실장] 레짐 분석 완료: {final_regime.value} | {notes}")
        return signal


class ChiefOfStaff:
    """
    통합 컨트롤타워 - 비서실장 엔진

    시장 레짐에 따라 3대 에이전트의 가동률과 예산 배분을 결정합니다.
    서킷 브레이커와 킬스위치 상태를 관리합니다.

    ┌── 의사결정 우선순위 (높을수록 먼저 적용) ─────────────────┐
    │  Lv.1  1차 하드코딩 서킷 브레이커 (이 파일 최상단)        │
    │        VIX≥30 OR 이평선 완전 역배열 → 즉각 0% 강제 청산   │
    │  Lv.2  일일 MDD 서킷 브레이커 (손실 한도 초과)            │
    │  Lv.3  킬스위치 (수동 긴급 정지)                          │
    │  Lv.4  레짐 기반 자동 배분 (공격/방어/전시)               │
    │  Lv.5  (미래) DQN AI 동적 재배분 ← Lv.1~4가 항상 Override │
    └───────────────────────────────────────────────────────────┘
    """

    def __init__(self, config: dict):
        self.config = config
        self.cfg = config["chief_of_staff"]
        self.risk_cfg = config["risk_management"]
        self.analyzer = MarketRegimeAnalyzer(config)

        self._circuit_breaker_active = False
        self._circuit_breaker_triggered_at: Optional[datetime] = None
        self._kill_switch_active = False
        self._daily_pnl_pct = 0.0
        self._current_regime: Optional[RegimeSignal] = None
        self._liquidation_pending = False          # 전량 청산 대기 플래그
        self._supreme_cb_reason: str = ""          # 1차 서킷브레이커 발동 사유

    @property
    def is_circuit_breaker_active(self) -> bool:
        return self._circuit_breaker_active

    @property
    def is_kill_switch_active(self) -> bool:
        return self._kill_switch_active

    @property
    def current_regime(self) -> Optional[RegimeSignal]:
        return self._current_regime

    @property
    def is_liquidation_pending(self) -> bool:
        """1차 서킷 브레이커 발동으로 전량 청산 대기 중인지 여부"""
        return self._liquidation_pending

    @property
    def supreme_cb_reason(self) -> str:
        """1차 서킷 브레이커 발동 사유"""
        return self._supreme_cb_reason

    # ══════════════════════════════════════════════════════════════════
    # 🚨 Lv.1: 1차 하드코딩 서킷 브레이커 — 절대 권력 (DQN Override)
    # ══════════════════════════════════════════════════════════════════

    def _check_supreme_circuit_breaker(
        self,
        current_vix: float,
        close_series: pd.Series,
    ) -> tuple[bool, str]:
        """
        절대 권력의 1차 방어선 — 어떤 AI 판단도 이 함수를 이길 수 없습니다.

        ┌─────────────────────────────────────────────────────────────┐
        │  조건 A: VIX ≥ 30  (공포지수 임계치, 극단적 시장 공포)     │
        │  조건 B: 60일선 > 20일선 > 5일선  (이평선 완전 역배열)     │
        │                                                             │
        │  A OR B 충족 시:                                            │
        │  → 총예산 가동률 0%  (현금 100%)                           │
        │  → 신규 매수 전면 금지                                      │
        │  → 보유 종목 전량 청산 대기 (liquidate_pending = True)      │
        │  → 향후 DQN AI의 긍정적 예측 결과도 무시                   │
        └─────────────────────────────────────────────────────────────┘
        """
        # ── 조건 A: VIX 임계치 ───────────────────────────────────────
        if current_vix >= 30:
            reason = (
                f"VIX OVERRIDE: VIX={current_vix:.1f} ≥ 30 "
                f"(공포지수 임계치 초과 — 극단적 시장 공포 감지)"
            )
            logger.critical(
                f"\n{'═'*60}\n"
                f"  🚨 [1차 서킷브레이커 — 조건A] {reason}\n"
                f"{'═'*60}"
            )
            return True, reason

        # ── 조건 B: 이동평균선 완전 역배열 ───────────────────────────
        if len(close_series) >= 60:
            ma5  = float(close_series.rolling(5).mean().iloc[-1])
            ma20 = float(close_series.rolling(20).mean().iloc[-1])
            ma60 = float(close_series.rolling(60).mean().iloc[-1])

            if ma60 > ma20 > ma5:
                reason = (
                    f"MA역배열 OVERRIDE: MA60={ma60:,.2f} > MA20={ma20:,.2f} > MA5={ma5:,.2f} "
                    f"(이평선 완전 역배열 — 구조적 하락 추세 확인)"
                )
                logger.critical(
                    f"\n{'═'*60}\n"
                    f"  🚨 [1차 서킷브레이커 — 조건B] {reason}\n"
                    f"  MA5={ma5:,.2f} | MA20={ma20:,.2f} | MA60={ma60:,.2f}\n"
                    f"{'═'*60}"
                )
                return True, reason

        return False, ""

    def activate_kill_switch(self, reason: str = "수동 발동"):
        """긴급 킬스위치 - 즉시 모든 거래 정지"""
        self._kill_switch_active = True
        logger.critical(f"[킬스위치] 긴급 거래 정지 발동! 사유: {reason}")

    def deactivate_kill_switch(self):
        """킬스위치 해제 (수동)"""
        self._kill_switch_active = False
        logger.warning("[킬스위치] 킬스위치 해제됨")

    def update_daily_pnl(self, pnl_pct: float):
        """일일 손익률 업데이트 및 서킷 브레이커 체크"""
        self._daily_pnl_pct = pnl_pct
        daily_loss_limit = self.cfg["circuit_breaker"]["daily_loss_trigger"]

        if pnl_pct <= -daily_loss_limit and not self._circuit_breaker_active:
            self._circuit_breaker_active = True
            self._circuit_breaker_triggered_at = datetime.now()
            logger.critical(
                f"[서킷브레이커] 일일 손실 한도 초과! 손실률={pnl_pct:.2%} | 한도={daily_loss_limit:.2%}"
            )

    def _check_circuit_breaker_reset(self):
        """서킷 브레이커 쿨다운 후 자동 해제"""
        cooldown_hours = self.risk_cfg["circuit_breaker_cooldown_hours"]
        if (
            self._circuit_breaker_active
            and self._circuit_breaker_triggered_at
            and (datetime.now() - self._circuit_breaker_triggered_at).seconds
            >= cooldown_hours * 3600
        ):
            self._circuit_breaker_active = False
            self._circuit_breaker_triggered_at = None
            logger.info("[서킷브레이커] 쿨다운 완료 - 서킷 브레이커 해제")

    def can_trade(self) -> tuple[bool, str]:
        """거래 가능 여부 및 사유 반환"""
        if self._kill_switch_active:
            return False, "킬스위치 발동 중 - 모든 거래 정지"

        self._check_circuit_breaker_reset()
        if self._circuit_breaker_active:
            return False, f"서킷 브레이커 발동 중 (일일 손실 한도 초과)"

        if self._current_regime and self._current_regime.vix >= self.cfg["circuit_breaker"]["vix_trigger"]:
            return False, f"VIX={self._current_regime.vix:.1f} ≥ {self.cfg['circuit_breaker']['vix_trigger']} - 전시 레짐 거래 제한"

        return True, "정상 거래 가능"

    def get_allocation(
        self,
        regime: MarketRegime,
        user: dict | None = None,
    ) -> AgentAllocation:
        """레짐에 따른 에이전트 예산 배분 반환.

        user 딕셔너리가 전달되고 allocation_mode == 'manual' 이면
        비서실장 거시경제 판단을 **완전히 우회**하고
        사용자가 DB에 저장해 둔 수동 배분 비율을 그대로 반환한다.
        """
        # ── 스나이퍼 정액 분리 (자본 독립 운용) ────────────
        # 전시 레짐(VIX 서킷브레이커)이면 스나이퍼 예산 0원 강제 회수
        is_wartime = (regime.name == "WARTIME")
        sniper_fixed = float(user.get("sniper_fixed_budget", 5_000_000) if user else 5_000_000)
        sniper_amount = 0.0 if is_wartime else sniper_fixed

        # ── Manual Override 바이패스 ────────────────────────
        if user and user.get("allocation_mode") == "manual":
            # 스나이퍼는 정액제이므로 3대 에이전트 비율만 정규화
            vf  = float(user.get("budget_value_pct",  0.35))
            tr  = float(user.get("budget_trend_pct",  0.35))
            sw  = float(user.get("budget_swing_pct",  0.20))
            total = vf + tr + sw
            if total > 0:
                vf /= total; tr /= total; sw /= total
            cash = max(0.0, 1.0 - (vf + tr + sw))
            logger.info(
                f"[비서실장] 수동 배분 모드 — "
                f"핵심 자본: 밸류:{vf:.0%} 트렌드:{tr:.0%} 스윙:{sw:.0%} | "
                f"스나이퍼 정액: {sniper_amount:,.0f}원 ({'전시회수' if is_wartime else '독립운용'})"
            )
            return AgentAllocation(
                value_finder=vf,
                trend_rider=tr,
                swing_master=sw,
                micro_sniper=0.0,         # 정액제로 TradingEngine에서 별도 처리
                cash=cash,
                sniper_fixed_amount=sniper_amount,
            )

        # ── 자동 배분 (레짐 기반) ───────────────────────────
        alloc_cfg = self.cfg["regime_allocation"][regime.name]
        logger.info(
            f"[비서실장] 자동 배분 — 레짐:{regime.name} | "
            f"핵심 자본: 밸류:{alloc_cfg['value_finder']:.0%} 트렌드:{alloc_cfg['trend_rider']:.0%} "
            f"스윙:{alloc_cfg['swing_master']:.0%} | "
            f"스나이퍼 정액: {sniper_amount:,.0f}원 ({'전시회수' if is_wartime else '독립운용'})"
        )
        return AgentAllocation(
            value_finder=alloc_cfg["value_finder"],
            trend_rider=alloc_cfg["trend_rider"],
            swing_master=alloc_cfg["swing_master"],
            micro_sniper=0.0,             # 정액제로 TradingEngine에서 별도 처리
            cash=alloc_cfg["cash"],
            sniper_fixed_amount=sniper_amount,
        )

    def run_analysis(self) -> tuple[RegimeSignal, AgentAllocation, bool, str]:
        """
        전체 비서실장 분석 사이클 실행

        ┌── 실행 순서 ──────────────────────────────────────────────┐
        │  STEP 0  레짐 분석 (VIX + MA배열 + MACD)                 │
        │  STEP 1  🚨 1차 하드코딩 서킷 브레이커 체크 (최우선)     │
        │          → 발동 시 즉시 0% 배분 + 청산 대기 반환         │
        │  STEP 2  일일 MDD 서킷 브레이커 체크                     │
        │  STEP 3  킬스위치 체크                                    │
        │  STEP 4  레짐 기반 에이전트 배분 결정                     │
        └───────────────────────────────────────────────────────────┘

        Returns:
            (레짐 신호, 에이전트 배분, 거래가능여부, 사유)
        """
        # ── STEP 0: 레짐 분석 ────────────────────────────────────────
        regime_signal = self.analyzer.analyze()
        self._current_regime = regime_signal

        # ════════════════════════════════════════════════════════════
        # 🚨 STEP 1: 1차 하드코딩 서킷 브레이커 (절대 최우선)
        #    DQN AI가 아무리 긍정적인 수익을 예측해도 이 블록을 넘을 수 없음
        # ════════════════════════════════════════════════════════════
        spx_data = self.analyzer._fetch_market_data(
            self.analyzer.market_index, period="1y"
        )
        close_for_cb = (
            spx_data["Close"].squeeze()
            if not spx_data.empty
            else pd.Series(dtype=float)
        )
        supreme_triggered, supreme_reason = self._check_supreme_circuit_breaker(
            regime_signal.vix, close_for_cb
        )

        if supreme_triggered:
            self._liquidation_pending = True
            self._supreme_cb_reason = supreme_reason
            self._circuit_breaker_active = True
            self._circuit_breaker_triggered_at = datetime.now()

            liquidation_alloc = AgentAllocation(
                value_finder=0.0,
                trend_rider=0.0,
                swing_master=0.0,
                micro_sniper=0.0,
                cash=1.0,              # 현금 100% — 투자 전면 중단
                sniper_fixed_amount=0.0,
            )
            stop_reason = f"[1차서킷브레이커] {supreme_reason} → 전량청산대기·신규매수금지"
            logger.critical(
                f"[비서실장] 최종 지시: 가동률=0% | 현금=100% | 전량청산대기=True\n"
                f"  사유: {supreme_reason}\n"
                f"  ※ 이 지시는 DQN AI 예측, 레짐 분석, 수동 설정 모두를 Override합니다."
            )
            return regime_signal, liquidation_alloc, False, stop_reason

        # ── STEP 1 미발동 시 청산 플래그 해제 ───────────────────────
        self._liquidation_pending = False
        self._supreme_cb_reason = ""

        # ── STEP 2: VIX 기반 일반 서킷 브레이커 ─────────────────────
        if regime_signal.vix >= self.cfg["circuit_breaker"]["vix_trigger"]:
            if not self._circuit_breaker_active:
                self._circuit_breaker_active = True
                self._circuit_breaker_triggered_at = datetime.now()
                logger.critical(
                    f"[서킷브레이커] VIX 트리거 발동! VIX={regime_signal.vix:.1f}"
                )

        # ── STEP 3~4: 배분 결정 및 거래 가능 여부 ───────────────────
        allocation = self.get_allocation(regime_signal.regime)
        can_trade, reason = self.can_trade()

        logger.info(
            f"[비서실장] 레짐={regime_signal.regime.value} | "
            f"배분=밸류:{allocation.value_finder:.0%} 트렌드:{allocation.trend_rider:.0%} "
            f"스윙:{allocation.swing_master:.0%} 스나이퍼:{allocation.micro_sniper:.0%} "
            f"현금:{allocation.cash:.0%} | 거래가능={can_trade}"
        )

        return regime_signal, allocation, can_trade, reason


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    config = load_config()
    cos = ChiefOfStaff(config)
    signal, alloc, tradeable, reason = cos.run_analysis()
    print(f"\n=== 비서실장 분석 결과 ===")
    print(f"레짐: {signal.regime.value}")
    print(f"VIX: {signal.vix:.2f}")
    print(f"신뢰도: {signal.confidence:.1%}")
    print(f"노트: {signal.notes}")
    print(f"배분 - 밸류:{alloc.value_finder:.0%} | 트렌드:{alloc.trend_rider:.0%} | 스윙:{alloc.swing_master:.0%} | 현금:{alloc.cash:.0%}")
    print(f"거래 가능: {tradeable} ({reason})")
