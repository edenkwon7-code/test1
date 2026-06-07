"""
3대 전술 에이전트 모듈
- ValueFinderAgent: 마법공식 + 소르티노 비율 + 피오트로스키 F-스코어
- TrendRiderAgent: 이동평균 교차 + MACD 모멘텀
- SwingMasterAgent: 볼린저 밴드 + RSI 역추세
"""

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Optional

import numpy as np
import pandas as pd

from config_loader import load_config
from KoreaDataProvider import get_provider
from DARTClient import get_dart_client

logger = logging.getLogger(__name__)


@dataclass
class TradeSignal:
    ticker: str
    action: str  # BUY / SELL / HOLD
    agent_name: str
    score: float
    reason: str
    target_pct: float  # 포트폴리오 내 목표 비중
    timestamp: datetime


class BaseAgent(ABC):
    """에이전트 기본 추상 클래스"""

    def __init__(self, config: dict, agent_name: str):
        self.config = config
        self.agent_name = agent_name
        self.agent_cfg = config["agents"][agent_name]
        self.universe = config["universe"]["stocks"]
        self._data_cache = {}
        self._cache_timestamp = {}
        self.cache_ttl_minutes = 60

    def _fetch_price_data(self, ticker: str, period: str = "2y") -> pd.DataFrame:
        cache_key = f"{ticker}_{period}"
        now = datetime.now()
        if cache_key in self._data_cache:
            age = (now - self._cache_timestamp.get(cache_key, datetime.min)).seconds
            if age < self.cache_ttl_minutes * 60:
                return self._data_cache[cache_key]
        data = get_provider().get_price_data(ticker, period=period)
        if not data.empty:
            self._data_cache[cache_key] = data
            self._cache_timestamp[cache_key] = now
        return data

    def _fetch_info(self, ticker: str, market_cap: float = None) -> dict:
        """
        DART API → 재무 지표 딕셔너리 반환.
        DART_API_KEY 미설정 시 빈 dict 반환 (F-스코어 · 마법공식 건너뜀).
        """
        dart = get_dart_client()
        if not dart.is_configured:
            return {}
        return dart.get_financial_info(ticker, market_cap=market_cap)

    @abstractmethod
    def generate_signals(self, budget: float) -> list[TradeSignal]:
        pass

    @abstractmethod
    def get_agent_status(self) -> dict:
        pass


class ValueFinderAgent(BaseAgent):
    """
    밸류파인더 에이전트
    - 마법공식 (이익수익률 + ROIC)
    - 소르티노 비율 필터 (< 0.2 영구 배제)
    - 피오트로스키 F-스코어 필터 (5항목 중 3개 이상)
    """

    def __init__(self, config: dict):
        super().__init__(config, "value_finder")
        self.cfg = self.agent_cfg
        self.sortino_threshold = self.cfg["sortino_min_threshold"]
        self.piotroski_min = self.cfg["piotroski_min_score"]
        self.top_n = self.cfg["top_n_stocks"]

    def _calc_sortino_ratio(self, returns: pd.Series, target_return: float = 0.0) -> float:
        """소르티노 비율 계산: 하방 리스크만 고려"""
        if len(returns) < 20:
            return 0.0
        excess = returns - target_return
        downside = excess[excess < 0]
        if len(downside) == 0 or downside.std() == 0:
            return float("inf")
        downside_std = downside.std() * np.sqrt(252)
        annual_return = returns.mean() * 252
        return annual_return / downside_std

    def _calc_piotroski_score(self, info: dict) -> tuple[int, list[str]]:
        """
        피오트로스키 F-스코어 (핵심 5항목)
        1. ROA > 0 (수익성)
        2. 영업현금흐름 > 0
        3. ROA 전년 대비 증가
        4. 부채비율 감소 (레버리지)
        5. 유동비율 개선 (유동성)
        """
        score = 0
        passed = []

        # 1. ROA > 0
        roa = info.get("returnOnAssets", None)
        if roa is not None and roa > 0:
            score += 1
            passed.append(f"ROA={roa:.2%}")

        # 2. 영업현금흐름 > 0
        ocf = info.get("operatingCashflow", None)
        total_assets = info.get("totalAssets", 1)
        if ocf is not None and total_assets and ocf > 0:
            score += 1
            passed.append("영업현금흐름 양수")

        # 3. 순이익 마진 > 0 (ROA 증가 대리 지표)
        profit_margin = info.get("profitMargins", None)
        if profit_margin is not None and profit_margin > 0:
            score += 1
            passed.append(f"순이익률={profit_margin:.2%}")

        # 4. 부채비율 양호 (D/E < 2)
        de_ratio = info.get("debtToEquity", None)
        if de_ratio is not None and de_ratio < 200:
            score += 1
            passed.append(f"D/E={de_ratio:.1f}")

        # 5. 유동비율 > 1
        current_ratio = info.get("currentRatio", None)
        if current_ratio is not None and current_ratio > 1.0:
            score += 1
            passed.append(f"유동비율={current_ratio:.2f}")

        return score, passed

    def _calc_magic_formula_rank(self, tickers: list[str]) -> pd.DataFrame:
        """마법공식 순위: 이익수익률 + ROIC 종합 순위"""
        rows = []
        provider = get_provider()
        for ticker in tickers:
            # 현재가로 시가총액 추정 (DART EV 계산용)
            curr_price = provider.get_current_price(ticker) or 0
            # 시가총액 = 현재가 × 임의 발행주수(미조회) → DART에서 계산
            info = self._fetch_info(ticker, market_cap=None)
            if not info:
                continue

            # 이익수익률 = EBIT / EV
            ebit = info.get("ebitda", None)
            ev = info.get("enterpriseValue", None)
            earnings_yield = (ebit / ev) if (ebit and ev and ev > 0) else None

            # ROIC = 영업이익 / 자본총계 (근사치)
            roic = info.get("returnOnEquity", None)

            if earnings_yield is None or roic is None:
                continue

            rows.append(
                {
                    "ticker": ticker,
                    "earnings_yield": earnings_yield,
                    "roic": roic,
                    "market_cap": info.get("marketCap", 0),
                    "info": info,
                }
            )

        if not rows:
            return pd.DataFrame()

        df = pd.DataFrame(rows)
        # 순위 매기기 (낮을수록 좋음)
        df["ey_rank"] = df["earnings_yield"].rank(ascending=False)
        df["roic_rank"] = df["roic"].rank(ascending=False)
        df["magic_rank"] = df["ey_rank"] + df["roic_rank"]
        return df.sort_values("magic_rank")

    def generate_signals(self, budget: float) -> list[TradeSignal]:
        """밸류파인더 매수 신호 생성"""
        logger.info(f"[밸류파인더] 유니버스 {len(self.universe)}개 종목 분석 시작")
        signals = []
        blacklist = set()  # 소르티노 영구 배제 목록

        # 1단계: 소르티노 필터
        valid_tickers = []
        for ticker in self.universe:
            data = self._fetch_price_data(ticker, period="2y")
            if data.empty or len(data) < 60:
                continue
            returns = data["Close"].squeeze().pct_change().dropna()
            sortino = self._calc_sortino_ratio(returns)
            if sortino < self.sortino_threshold:
                blacklist.add(ticker)
                logger.debug(f"[밸류파인더] {ticker} 소르티노={sortino:.3f} < {self.sortino_threshold} → 영구 배제")
            else:
                valid_tickers.append(ticker)

        logger.info(f"[밸류파인더] 소르티노 통과: {len(valid_tickers)}개 / 배제: {len(blacklist)}개")

        # 2단계: 마법공식 순위
        magic_df = self._calc_magic_formula_rank(valid_tickers)
        if magic_df.empty:
            logger.warning("[밸류파인더] 마법공식 계산 가능한 종목 없음")
            return signals

        # 3단계: 피오트로스키 F-스코어 필터
        qualified = []
        for _, row in magic_df.head(self.top_n * 2).iterrows():
            ticker = row["ticker"]
            f_score, passed_items = self._calc_piotroski_score(row["info"])
            if f_score >= self.piotroski_min:
                qualified.append(
                    {
                        "ticker": ticker,
                        "magic_rank": row["magic_rank"],
                        "f_score": f_score,
                        "passed_items": passed_items,
                        "earnings_yield": row["earnings_yield"],
                        "roic": row["roic"],
                    }
                )

        logger.info(f"[밸류파인더] 피오트로스키 통과: {len(qualified)}개")

        # 신호 생성
        top_stocks = qualified[: self.top_n]
        per_stock_budget = budget / len(top_stocks) if top_stocks else 0

        for item in top_stocks:
            reason = (
                f"마법공식순위={item['magic_rank']:.0f} | "
                f"F스코어={item['f_score']}/5 | "
                f"이익수익률={item['earnings_yield']:.2%} | "
                f"ROIC={item['roic']:.2%} | "
                f"통과: {', '.join(item['passed_items'])}"
            )
            signals.append(
                TradeSignal(
                    ticker=item["ticker"],
                    action="BUY",
                    agent_name=self.agent_name,
                    score=item["f_score"] / 5.0,
                    reason=reason,
                    target_pct=per_stock_budget / budget if budget > 0 else 0,
                    timestamp=datetime.now(),
                )
            )

        logger.info(f"[밸류파인더] {len(signals)}개 매수 신호 생성 완료")
        return signals

    def get_agent_status(self) -> dict:
        return {
            "name": "밸류파인더",
            "strategy": "마법공식 + 소르티노 + 피오트로스키",
            "rebalance_days": self.cfg["rebalance_days"],
            "universe_count": len(self.universe),
            "top_n": self.top_n,
            "sortino_threshold": self.sortino_threshold,
            "piotroski_min": self.piotroski_min,
        }


class TrendRiderAgent(BaseAgent):
    """
    트렌드라이더 에이전트 (Whipsaw 방지 강화판)
    ───────────────────────────────────────────
    매수 조건 3중 AND (모두 충족해야 진입):
      1. 골든크로스: 5일선이 20일선을 상향 돌파
      2. MACD ≥ 0:  MACD 라인이 0선 이상 (양의 모멘텀 확인)
      3. 거래량 급증: 현재 거래량 ≥ 20일 평균 × 1.5배 (가짜 돌파 필터)
    """

    def __init__(self, config: dict):
        super().__init__(config, "trend_rider")
        self.cfg = self.agent_cfg
        self.ma_fast = self.cfg["ma_periods"]["fast"]   # 5일
        self.ma_slow = self.cfg["ma_periods"]["slow"]   # 20일
        self.macd_cfg = self.cfg["macd"]
        self.top_n = self.cfg["top_n_stocks"]
        self.vol_multiplier = self.cfg.get("volume_spike_multiplier", 1.5)
        self.vol_avg_period = self.cfg.get("volume_avg_period", 20)

    def _detect_crossover(self, close: pd.Series) -> tuple[str, float]:
        """이동평균 교차 탐지 (5일선 vs 20일선)"""
        if len(close) < self.ma_slow + 5:
            return "NONE", 0.0

        ma_fast = close.rolling(self.ma_fast).mean()
        ma_slow = close.rolling(self.ma_slow).mean()

        prev_diff = ma_fast.iloc[-2] - ma_slow.iloc[-2]
        curr_diff = ma_fast.iloc[-1] - ma_slow.iloc[-1]
        strength = abs(curr_diff) / close.iloc[-1]

        if prev_diff < 0 and curr_diff > 0:
            return "GOLDEN_CROSS", strength
        elif prev_diff > 0 and curr_diff < 0:
            return "DEATH_CROSS", strength
        elif curr_diff > 0:
            return "ABOVE", strength
        else:
            return "BELOW", strength

    def _calc_macd_value(self, close: pd.Series) -> float:
        """
        MACD 라인 값 반환 — 0선 상향 돌파 여부 판단용
        (MACD ≥ 0 → 강한 상승 모멘텀, MACD < 0 → 하락 모멘텀)
        """
        if len(close) < self.macd_cfg["slow"]:
            return float("nan")
        ema_fast = close.ewm(span=self.macd_cfg["fast"], adjust=False).mean()
        ema_slow = close.ewm(span=self.macd_cfg["slow"], adjust=False).mean()
        macd_line = ema_fast - ema_slow
        return float(macd_line.iloc[-1])

    def _calc_macd_signal(self, close: pd.Series) -> tuple[str, float]:
        """MACD 히스토그램 방향 신호 (방향 강도 보조 지표)"""
        if len(close) < self.macd_cfg["slow"] + self.macd_cfg["signal"]:
            return "NEUTRAL", 0.0

        ema_fast = close.ewm(span=self.macd_cfg["fast"], adjust=False).mean()
        ema_slow = close.ewm(span=self.macd_cfg["slow"], adjust=False).mean()
        macd = ema_fast - ema_slow
        signal = macd.ewm(span=self.macd_cfg["signal"], adjust=False).mean()
        hist = macd - signal

        curr_hist = hist.iloc[-1]
        prev_hist = hist.iloc[-2]

        if curr_hist > 0 and curr_hist > prev_hist:
            return "BULLISH", abs(curr_hist)
        elif curr_hist < 0 and curr_hist < prev_hist:
            return "BEARISH", abs(curr_hist)
        else:
            return "NEUTRAL", abs(curr_hist)

    def _check_volume_spike(self, data: pd.DataFrame) -> tuple[bool, float]:
        """
        거래량 급증 확인 — Whipsaw(가짜 돌파) 필터
        현재 거래량 ≥ 20일 평균 거래량 × 1.5배일 때만 True
        """
        if "Volume" not in data.columns or len(data) < self.vol_avg_period:
            return False, 0.0
        vol = data["Volume"].squeeze()
        curr_vol = float(vol.iloc[-1])
        avg_vol = float(vol.rolling(self.vol_avg_period).mean().iloc[-1])
        if avg_vol <= 0:
            return False, 0.0
        ratio = curr_vol / avg_vol
        return ratio >= self.vol_multiplier, ratio

    def generate_signals(self, budget: float) -> list[TradeSignal]:
        """
        트렌드라이더 매수 신호 생성 — 3중 AND 조건 엄격 적용
        단 하나라도 미충족 시 해당 종목 완전 배제 (Whipsaw 방지)
        """
        logger.info(
            f"[트렌드라이더] {len(self.universe)}개 종목 추세 분석 "
            f"| 조건: 골든크로스(5/20) AND MACD≥0 AND 거래량≥{self.vol_multiplier}x"
        )
        buy_candidates = []
        filtered_gc = filtered_macd = filtered_vol = 0

        for ticker in self.universe:
            data = self._fetch_price_data(ticker, period="1y")
            if data.empty or len(data) < self.ma_slow + 10:
                continue

            close = data["Close"].squeeze()

            # ── AND 조건 1: 골든크로스 전용 (ABOVE 허용 안 함) ──
            cross_signal, cross_strength = self._detect_crossover(close)
            if cross_signal != "GOLDEN_CROSS":
                if cross_signal in ("DEATH_CROSS", "BELOW", "ABOVE", "NONE"):
                    filtered_gc += 1
                continue

            min_strength = self.cfg["min_trend_strength"]
            if cross_strength < min_strength:
                filtered_gc += 1
                continue

            # ── AND 조건 2: MACD 0선 이상 (양의 모멘텀) ──────────
            macd_val = self._calc_macd_value(close)
            if pd.isna(macd_val) or macd_val < 0:
                filtered_macd += 1
                logger.debug(
                    f"[트렌드라이더] {ticker} MACD={macd_val:.4f} < 0 "
                    f"→ 음의 모멘텀, 배제"
                )
                continue

            # ── AND 조건 3: 거래량 급증 (Whipsaw 필터) ───────────
            vol_ok, vol_ratio = self._check_volume_spike(data)
            if not vol_ok:
                filtered_vol += 1
                logger.debug(
                    f"[트렌드라이더] {ticker} 거래량={vol_ratio:.2f}x < {self.vol_multiplier}x "
                    f"→ 가짜 돌파 의심, 배제"
                )
                continue

            # ✅ 3중 AND 모두 충족 — 유효 신호
            macd_signal, macd_strength = self._calc_macd_signal(close)
            score = (
                0.50                                            # 골든크로스 기본
                + (0.25 if macd_signal == "BULLISH" else 0.10)  # MACD 방향 가산
                + min(0.25, (vol_ratio - self.vol_multiplier) * 0.1)  # 거래량 초과분 가산
            )

            reasons = [
                f"골든크로스(5일>{self.ma_slow}일,강도={cross_strength:.4f})",
                f"MACD={macd_val:.4f}≥0(0선돌파)",
                f"거래량={vol_ratio:.2f}x≥{self.vol_multiplier}x(급증확인)",
            ]
            if macd_signal == "BULLISH":
                reasons.append("MACD히스토그램상승")

            logger.info(
                f"[트렌드라이더] ✅ {ticker} 3중조건충족 | 점수={score:.2f} | "
                + " | ".join(reasons)
            )
            buy_candidates.append({"ticker": ticker, "score": score, "reasons": reasons})

        logger.info(
            f"[트렌드라이더] 필터링 결과 | "
            f"골든크로스미충족={filtered_gc} | MACD미충족={filtered_macd} | "
            f"거래량미충족={filtered_vol} | 최종통과={len(buy_candidates)}개"
        )

        buy_candidates.sort(key=lambda x: x["score"], reverse=True)
        top_candidates = buy_candidates[: self.top_n]

        signals = []
        per_stock_budget = budget / len(top_candidates) if top_candidates else 0

        for cand in top_candidates:
            signals.append(
                TradeSignal(
                    ticker=cand["ticker"],
                    action="BUY",
                    agent_name=self.agent_name,
                    score=cand["score"],
                    reason=" | ".join(cand["reasons"]),
                    target_pct=per_stock_budget / budget if budget > 0 else 0,
                    timestamp=datetime.now(),
                )
            )

        logger.info(f"[트렌드라이더] {len(signals)}개 최종 매수 신호 생성 완료")
        return signals

    def get_agent_status(self) -> dict:
        return {
            "name": "트렌드라이더",
            "strategy": (
                f"골든크로스({self.ma_fast}/{self.ma_slow}일) "
                f"AND MACD≥0 AND 거래량≥{self.vol_multiplier}x"
            ),
            "rebalance_days": self.cfg["rebalance_days"],
            "ma_fast": self.ma_fast,
            "ma_slow": self.ma_slow,
            "vol_multiplier": self.vol_multiplier,
        }


class SwingMasterAgent(BaseAgent):
    """
    스윙마스터 에이전트
    - 볼린저 밴드 하단 돌파 + RSI 과매도/과매수 신호
    - 목표 승률 87.5%의 박스권 역추세 단기 매매
    """

    def __init__(self, config: dict):
        super().__init__(config, "swing_master")
        self.cfg = self.agent_cfg
        self.bb_period = self.cfg["bollinger"]["period"]
        self.bb_std = self.cfg["bollinger"]["std_dev"]
        self.rsi_period = self.cfg["rsi"]["period"]
        self.rsi_oversold = self.cfg["rsi"]["oversold"]
        self.rsi_overbought = self.cfg["rsi"]["overbought"]
        self.min_signal = self.cfg["min_signal_score"]
        self.top_n = self.cfg["top_n_stocks"]

    def _calc_bollinger_bands(self, close: pd.Series) -> tuple[pd.Series, pd.Series, pd.Series]:
        """볼린저 밴드 계산"""
        mid = close.rolling(self.bb_period).mean()
        std = close.rolling(self.bb_period).std()
        upper = mid + self.bb_std * std
        lower = mid - self.bb_std * std
        return upper, mid, lower

    def _calc_rsi(self, close: pd.Series) -> pd.Series:
        """RSI 계산"""
        delta = close.diff()
        gain = delta.clip(lower=0)
        loss = -delta.clip(upper=0)
        avg_gain = gain.rolling(self.rsi_period).mean()
        avg_loss = loss.rolling(self.rsi_period).mean()
        rs = avg_gain / avg_loss.replace(0, float("inf"))
        rsi = 100 - (100 / (1 + rs))
        return rsi

    def _calc_bb_position(self, close: pd.Series, upper: pd.Series, lower: pd.Series) -> float:
        """%B: 볼린저 밴드 내 현재 위치 (0=하단, 1=상단)"""
        band_width = upper.iloc[-1] - lower.iloc[-1]
        if band_width == 0:
            return 0.5
        return (close.iloc[-1] - lower.iloc[-1]) / band_width

    def generate_signals(self, budget: float) -> list[TradeSignal]:
        """스윙마스터 매수/매도 신호 생성"""
        logger.info(f"[스윙마스터] {len(self.universe)}개 종목 스윙 신호 분석")
        candidates = []

        for ticker in self.universe:
            data = self._fetch_price_data(ticker, period="6mo")
            if data.empty or len(data) < self.bb_period + self.rsi_period + 5:
                continue

            close = data["Close"].squeeze()
            upper, mid, lower = self._calc_bollinger_bands(close)
            rsi = self._calc_rsi(close)

            current_price = close.iloc[-1]
            current_rsi = rsi.iloc[-1]
            bb_pct = self._calc_bb_position(close, upper, lower)

            signal_score = 0
            reasons = []

            # 볼린저 하단 돌파 (매수 신호)
            if current_price <= lower.iloc[-1]:
                signal_score += 1
                reasons.append(f"BB하단돌파(BB%={bb_pct:.2f})")
            elif bb_pct < 0.2:
                signal_score += 0.5
                reasons.append(f"BB하단근접(BB%={bb_pct:.2f})")

            # RSI 과매도
            if current_rsi <= self.rsi_oversold:
                signal_score += 1
                reasons.append(f"RSI과매도={current_rsi:.1f}")
            elif current_rsi <= self.rsi_oversold + 5:
                signal_score += 0.5
                reasons.append(f"RSI근접과매도={current_rsi:.1f}")

            # RSI 과매수 (매도 신호) - 음수 처리
            if current_rsi >= self.rsi_overbought:
                signal_score -= 1
                reasons.append(f"RSI과매수={current_rsi:.1f}(매도신호)")

            if signal_score >= self.min_signal:
                # 볼린저 밴드 목표가 (중앙선)
                target_price = float(mid.iloc[-1])
                upside = (target_price - current_price) / current_price

                candidates.append(
                    {
                        "ticker": ticker,
                        "score": signal_score,
                        "rsi": current_rsi,
                        "bb_pct": bb_pct,
                        "target_price": target_price,
                        "upside": upside,
                        "reasons": reasons,
                    }
                )

        candidates.sort(key=lambda x: (x["score"], x["upside"]), reverse=True)
        top_candidates = candidates[: self.top_n]

        signals = []
        per_stock_budget = budget / len(top_candidates) if top_candidates else 0

        for cand in top_candidates:
            signals.append(
                TradeSignal(
                    ticker=cand["ticker"],
                    action="BUY",
                    agent_name=self.agent_name,
                    score=cand["score"],
                    reason=" | ".join(cand["reasons"])
                    + f" | 목표가={cand['target_price']:.2f}(상승여력={cand['upside']:.2%})",
                    target_pct=per_stock_budget / budget if budget > 0 else 0,
                    timestamp=datetime.now(),
                )
            )

        logger.info(f"[스윙마스터] {len(signals)}개 신호 생성 (최소신호점수={self.min_signal})")
        return signals

    def get_agent_status(self) -> dict:
        return {
            "name": "스윙마스터",
            "strategy": f"볼린저밴드({self.bb_period},{self.bb_std}σ) + RSI({self.rsi_period})",
            "rebalance_days": self.cfg["rebalance_days"],
            "rsi_oversold": self.rsi_oversold,
            "rsi_overbought": self.rsi_overbought,
            "target_win_rate": self.cfg["target_win_rate"],
        }


class AgentFactory:
    """에이전트 팩토리"""

    @staticmethod
    def create_all(config: dict) -> dict:
        from MicroSniper import MicroSniperAgent
        agents: dict = {
            "value_finder": ValueFinderAgent(config),
            "trend_rider": TrendRiderAgent(config),
            "swing_master": SwingMasterAgent(config),
        }
        try:
            agents["micro_sniper"] = MicroSniperAgent(config)
        except Exception as e:
            logger.warning(f"[AgentFactory] MicroSniper 초기화 실패 (계속 진행): {e}")
        return agents


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    config = load_config()
    agents = AgentFactory.create_all(config)
    for name, agent in agents.items():
        status = agent.get_agent_status()
        print(f"\n=== {status['name']} ===")
        for k, v in status.items():
            if k != "name":
                print(f"  {k}: {v}")
