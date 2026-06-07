"""
MicroSniper — 4번째 전술 에이전트 (초단타 스캘핑)
────────────────────────────────────────────────────
전략: ADX(추세필터) + BB%B(가격위치) + RSI(과열침체) + Stochastic(방아쇠)
타임프레임: 1분봉 기반 당일 스캘핑
리스크: 연속 3회 손실 시 당일 가동 자동 중단
예산: 전체 자본의 10% 격리 운용
"""

import logging
from dataclasses import dataclass, field
from datetime import datetime, date
from typing import Optional

import numpy as np
import pandas as pd

from config_loader import load_config

logger = logging.getLogger(__name__)


@dataclass
class SniperSignal:
    ticker: str
    action: str          # BUY / SELL / HOLD
    score: float         # 0.0~1.0
    reason: str
    entry_price: float
    stop_loss: float
    take_profit: float
    timestamp: datetime
    indicators: dict = field(default_factory=dict)


@dataclass
class SniperDailyStats:
    """당일 스나이퍼 실적 추적"""
    date: date
    total_trades: int = 0
    wins: int = 0
    losses: int = 0
    realized_pnl: float = 0.0
    consecutive_losses: int = 0
    halted: bool = False          # 당일 가동 중단 여부
    halt_reason: str = ""


class MicroSniperAgent:
    """
    마이크로 스나이퍼 (Micro Sniper)
    ─────────────────────────────────
    1분봉 4중 지표 결합으로 극단적 단기 역추세 되돌림을 저격합니다.

    진입 조건 (동시 충족 필수):
      1. ADX(15) > 20           — 추세 강도 확인 (횡보장 차단)
      2. BB%B(47, 2σ) < 0.05   — 볼린저 하단 터치 (극단 과매도 위치)
      3. RSI(33) < 21           — 타이트 과매도 구간
      4. Stochastic %K < %D 후 Golden Cross — 마이크로 반전 시그널

    청산 조건:
      - RSI(33) > 33 (과매수) 또는 Stochastic Dead Cross
      - 스탑로스 -2% / 익절 +1.5%
    """

    AGENT_NAME = "마이크로스나이퍼"

    def __init__(self, config: dict):
        self.config = config
        self.cfg = config["agents"]["micro_sniper"]
        self.universe = config["universe"]["stocks"]

        # 지표 파라미터
        self.adx_period   = self.cfg["adx"]["period"]
        self.adx_threshold = self.cfg["adx"]["threshold"]
        self.bb_period    = self.cfg["bollinger"]["period"]
        self.bb_std       = self.cfg["bollinger"]["std_dev"]
        self.bb_mid       = self.cfg["bollinger"]["mid_level"]
        self.rsi_period   = self.cfg["rsi"]["period"]
        self.rsi_oversold  = self.cfg["rsi"]["oversold"]
        self.rsi_overbought = self.cfg["rsi"]["overbought"]
        self.stoch_k      = self.cfg["stochastic"]["k_period"]
        self.stoch_d      = self.cfg["stochastic"]["d_period"]
        self.stoch_os     = self.cfg["stochastic"]["oversold"]
        self.stoch_ob     = self.cfg["stochastic"]["overbought"]

        # 리스크 파라미터
        self.stop_loss_pct   = self.cfg["stop_loss_pct"]
        self.take_profit_pct = self.cfg["take_profit_pct"]
        self.max_daily_trades = self.cfg["max_daily_trades"]
        self.loss_limit      = self.cfg["consecutive_loss_limit"]
        self.top_n           = self.cfg["top_n_stocks"]

        # 당일 통계 (자정마다 리셋)
        self._daily: SniperDailyStats = SniperDailyStats(date=date.today())

        logger.info(
            f"[마이크로스나이퍼] 초기화 완료 | "
            f"ADX({self.adx_period}>{self.adx_threshold}) | "
            f"BB({self.bb_period},{self.bb_std}σ) | "
            f"RSI({self.rsi_period}: {self.rsi_oversold}/{self.rsi_overbought}) | "
            f"Stoch({self.stoch_k},{self.stoch_d})"
        )

    def _reset_daily_if_needed(self):
        """자정 지나면 당일 통계 리셋"""
        today = date.today()
        if self._daily.date != today:
            self._daily = SniperDailyStats(date=today)
            logger.info("[마이크로스나이퍼] 새 거래일 — 당일 통계 리셋")

    @property
    def is_halted(self) -> bool:
        """당일 가동 중단 여부"""
        self._reset_daily_if_needed()
        return self._daily.halted

    @property
    def daily_stats(self) -> SniperDailyStats:
        self._reset_daily_if_needed()
        return self._daily

    def record_trade_result(self, pnl: float):
        """매매 결과 기록 — 연속 손실 카운터 관리"""
        self._reset_daily_if_needed()
        self._daily.total_trades += 1
        self._daily.realized_pnl += pnl

        if pnl < 0:
            self._daily.losses += 1
            self._daily.consecutive_losses += 1
            logger.warning(
                f"[마이크로스나이퍼] 손실 기록 | "
                f"연속={self._daily.consecutive_losses}/{self.loss_limit} | "
                f"P&L={pnl:+,.0f}"
            )
            if self._daily.consecutive_losses >= self.loss_limit:
                self._daily.halted = True
                self._daily.halt_reason = (
                    f"연속 {self._daily.consecutive_losses}회 손실 — 당일 가동 중단"
                )
                logger.critical(
                    f"[마이크로스나이퍼] {self._daily.halt_reason}"
                )
        else:
            self._daily.wins += 1
            self._daily.consecutive_losses = 0  # 수익 발생 시 연속 손실 카운터 리셋

    @staticmethod
    def calculate_sniper_indicators(df: pd.DataFrame) -> pd.DataFrame:
        """
        1분봉 전용 4대 스캘핑 지표 계산 (순수 numpy/pandas 구현)
        ──────────────────────────────────────────────────────────
        입력: Open/High/Low/Close/Volume 컬럼의 DataFrame
        출력: 지표 컬럼 추가된 DataFrame (초기 NaN 행 제거됨)

        지표:
          - ADX_15        : 평균방향성지수 (length=15)
          - BBP_47        : 볼린저밴드 %B (length=47, std=2.0)
          - RSI_33        : RSI (length=33)
          - STOCH_K / D   : 스토캐스틱 (%K=14, %D=3)
        """
        if df is None or df.empty or len(df) < 50:
            return df

        df = df.copy()
        close = df["Close"]
        high  = df["High"]
        low   = df["Low"]

        # ── 1) ADX(15) ────────────────────────────────────────
        n = 15
        tr = pd.concat([
            high - low,
            (high - close.shift(1)).abs(),
            (low  - close.shift(1)).abs(),
        ], axis=1).max(axis=1)
        dm_plus  = (high - high.shift(1)).clip(lower=0)
        dm_minus = (low.shift(1) - low).clip(lower=0)
        dm_plus  = dm_plus.where(dm_plus > dm_minus, 0)
        dm_minus = dm_minus.where(dm_minus > dm_plus, 0)
        atr = tr.ewm(span=n, adjust=False).mean()
        di_plus  = 100 * dm_plus.ewm(span=n, adjust=False).mean() / atr.replace(0, np.nan)
        di_minus = 100 * dm_minus.ewm(span=n, adjust=False).mean() / atr.replace(0, np.nan)
        dx = 100 * (di_plus - di_minus).abs() / (di_plus + di_minus).replace(0, np.nan)
        df["ADX_15"] = dx.ewm(span=n, adjust=False).mean().fillna(0)

        # ── 2) Bollinger Bands %B(47, std=2.0) ───────────────
        bb_n = 47
        ma   = close.rolling(bb_n).mean()
        std  = close.rolling(bb_n).std(ddof=0)
        upper = ma + 2.0 * std
        lower = ma - 2.0 * std
        df["BBP_47"] = (close - lower) / (upper - lower).replace(0, np.nan)

        # ── 3) RSI(33) ────────────────────────────────────────
        rsi_n = 33
        delta = close.diff()
        gain  = delta.clip(lower=0).ewm(com=rsi_n - 1, adjust=False).mean()
        loss  = (-delta.clip(upper=0)).ewm(com=rsi_n - 1, adjust=False).mean()
        rs    = gain / loss.replace(0, np.nan)
        df["RSI_33"] = 100 - (100 / (1 + rs))

        # ── 4) Stochastic(%K=14, %D=3) ───────────────────────
        k_n = 14; d_n = 3
        lowest  = low.rolling(k_n).min()
        highest = high.rolling(k_n).max()
        raw_k   = 100 * (close - lowest) / (highest - lowest).replace(0, np.nan)
        df["STOCH_K"] = raw_k.rolling(3).mean()          # Smooth %K
        df["STOCH_D"] = df["STOCH_K"].rolling(d_n).mean()

        # ── NaN 제거 ──────────────────────────────────────────
        df = df.dropna(subset=["ADX_15", "BBP_47", "RSI_33", "STOCH_K", "STOCH_D"])
        return df

    def _fetch_intraday(self, ticker: str, minutes: int = 60) -> pd.DataFrame:
        """
        1분봉 데이터 수집.
        실전: KiwoomBridge / KoreaDataProvider 1분봉 API 사용
        모의: yfinance 5분봉(최근 1일) 또는 일봉 데이터로 지표 근사 계산
        """
        try:
            from KoreaDataProvider import get_provider
            provider = get_provider()
            # KoreaDataProvider가 1분봉을 지원하면 사용
            if hasattr(provider, "get_intraday_data"):
                df = provider.get_intraday_data(ticker, interval="1m", bars=max(minutes * 2, 200))
                if df is not None and len(df) >= 50:
                    return df

            # 폴백: 일봉 최근 1년치 → 지표 정밀도는 떨어지지만 로직 검증 가능
            df = provider.get_price_data(ticker, period="6mo")
            if df is not None and not df.empty:
                return df
        except Exception as e:
            logger.debug(f"[마이크로스나이퍼] 데이터 수집 실패 [{ticker}]: {e}")

        return pd.DataFrame()

    def _compute_adx(self, df: pd.DataFrame) -> pd.Series:
        """ADX(평균방향성지수) 계산"""
        high  = df["High"]
        low   = df["Low"]
        close = df["Close"]
        n = self.adx_period

        tr = pd.concat([
            high - low,
            (high - close.shift(1)).abs(),
            (low  - close.shift(1)).abs(),
        ], axis=1).max(axis=1)

        dm_plus  = (high - high.shift(1)).clip(lower=0)
        dm_minus = (low.shift(1) - low).clip(lower=0)

        dm_plus  = dm_plus.where(dm_plus > dm_minus, 0)
        dm_minus = dm_minus.where(dm_minus > dm_plus, 0)

        atr = tr.ewm(span=n, adjust=False).mean()
        di_plus  = 100 * dm_plus.ewm(span=n, adjust=False).mean() / atr.replace(0, np.nan)
        di_minus = 100 * dm_minus.ewm(span=n, adjust=False).mean() / atr.replace(0, np.nan)

        dx = 100 * (di_plus - di_minus).abs() / (di_plus + di_minus).replace(0, np.nan)
        adx = dx.ewm(span=n, adjust=False).mean()
        return adx.fillna(0)

    def _compute_bb_pct_b(self, close: pd.Series) -> pd.Series:
        """볼린저 밴드 %B 계산"""
        mid   = close.rolling(self.bb_period).mean()
        std   = close.rolling(self.bb_period).std()
        upper = mid + self.bb_std * std
        lower = mid - self.bb_std * std
        pct_b = (close - lower) / (upper - lower).replace(0, np.nan)
        return pct_b.fillna(0.5)

    def _compute_rsi(self, close: pd.Series) -> pd.Series:
        """RSI 계산"""
        delta = close.diff()
        gain = delta.clip(lower=0).ewm(span=self.rsi_period, adjust=False).mean()
        loss = (-delta.clip(upper=0)).ewm(span=self.rsi_period, adjust=False).mean()
        rs = gain / loss.replace(0, np.nan)
        return (100 - 100 / (1 + rs)).fillna(50)

    def _compute_stochastic(self, df: pd.DataFrame) -> tuple[pd.Series, pd.Series]:
        """%K, %D 스토캐스틱 계산"""
        low_min  = df["Low"].rolling(self.stoch_k).min()
        high_max = df["High"].rolling(self.stoch_k).max()
        k = 100 * (df["Close"] - low_min) / (high_max - low_min).replace(0, np.nan)
        k = k.fillna(50)
        d = k.rolling(self.stoch_d).mean().fillna(50)
        return k, d

    def _evaluate_ticker(self, ticker: str) -> Optional[SniperSignal]:
        """
        단일 종목 스나이퍼 신호 평가
        4중 조건 동시 충족 시에만 BUY 신호 발생
        """
        df = self._fetch_intraday(ticker)
        if df is None or len(df) < max(self.bb_period, self.rsi_period) + 10:
            return None

        try:
            close = df["Close"]

            adx    = self._compute_adx(df)
            pct_b  = self._compute_bb_pct_b(close)
            rsi    = self._compute_rsi(close)
            k, d   = self._compute_stochastic(df)

            cur_adx   = adx.iloc[-1]
            cur_pctb  = pct_b.iloc[-1]
            cur_rsi   = rsi.iloc[-1]
            cur_k     = k.iloc[-1]
            cur_d     = d.iloc[-1]
            prev_k    = k.iloc[-2]
            prev_d    = d.iloc[-2]
            cur_price = float(close.iloc[-1])

            # ── 매수 조건 (4중 동시 충족) ────────────────────────
            adx_ok    = cur_adx > self.adx_threshold          # 추세 강도 있음
            bb_buy    = cur_pctb < 0.1                        # 볼린저 하단 근처
            rsi_buy   = cur_rsi < self.rsi_oversold           # 극단 과매도
            stoch_gc  = (prev_k <= prev_d) and (cur_k > cur_d)  # Stochastic 골든크로스

            if adx_ok and bb_buy and rsi_buy and stoch_gc:
                score = min(
                    1.0,
                    (self.adx_threshold / max(cur_adx, 1)) * 0.25
                    + (1 - cur_pctb) * 0.25
                    + ((self.rsi_oversold - cur_rsi) / self.rsi_oversold) * 0.25
                    + (cur_k - cur_d) / 100 * 0.25,
                )
                score = max(0.1, min(1.0, score))
                return SniperSignal(
                    ticker=ticker,
                    action="BUY",
                    score=score,
                    reason=(
                        f"4중 스나이퍼 매수 | ADX={cur_adx:.1f}(>{self.adx_threshold}) | "
                        f"BB%B={cur_pctb:.3f}(<0.1) | RSI={cur_rsi:.1f}(<{self.rsi_oversold}) | "
                        f"Stoch GC({prev_k:.1f}→{cur_k:.1f}>{cur_d:.1f})"
                    ),
                    entry_price=cur_price,
                    stop_loss=cur_price * (1 - self.stop_loss_pct),
                    take_profit=cur_price * (1 + self.take_profit_pct),
                    timestamp=datetime.now(),
                    indicators={
                        "adx": round(cur_adx, 2),
                        "bb_pct_b": round(cur_pctb, 4),
                        "rsi": round(cur_rsi, 2),
                        "stoch_k": round(cur_k, 2),
                        "stoch_d": round(cur_d, 2),
                    },
                )

            # ── 매도 조건 (포지션 청산 신호) ─────────────────────
            stoch_dc = (prev_k >= prev_d) and (cur_k < cur_d)  # Dead Cross
            rsi_sell = cur_rsi > self.rsi_overbought

            if stoch_dc and rsi_sell:
                return SniperSignal(
                    ticker=ticker,
                    action="SELL",
                    score=0.7,
                    reason=(
                        f"스나이퍼 청산 | RSI={cur_rsi:.1f}(>{self.rsi_overbought}) | "
                        f"Stoch DC({prev_k:.1f}→{cur_k:.1f}<{cur_d:.1f})"
                    ),
                    entry_price=cur_price,
                    stop_loss=0.0,
                    take_profit=0.0,
                    timestamp=datetime.now(),
                    indicators={
                        "adx": round(cur_adx, 2),
                        "rsi": round(cur_rsi, 2),
                        "stoch_k": round(cur_k, 2),
                        "stoch_d": round(cur_d, 2),
                    },
                )

        except Exception as e:
            logger.debug(f"[마이크로스나이퍼] 지표 계산 오류 [{ticker}]: {e}")

        return None

    def generate_signals(self, budget: float) -> list[SniperSignal]:
        """
        스나이퍼 신호 생성 — 전 유니버스 스캔 후 상위 N개 필터링

        Args:
            budget: 배정된 예산 (10% 특수 활동비)

        Returns:
            매매 신호 리스트
        """
        self._reset_daily_if_needed()

        if self._daily.halted:
            logger.warning(
                f"[마이크로스나이퍼] 당일 가동 중단 — {self._daily.halt_reason}"
            )
            return []

        if not self.cfg.get("enabled", True):
            return []

        if self._daily.total_trades >= self.max_daily_trades:
            logger.info(
                f"[마이크로스나이퍼] 일일 최대 매매 횟수 도달 "
                f"({self._daily.total_trades}/{self.max_daily_trades})"
            )
            return []

        logger.info(
            f"[마이크로스나이퍼] 스캔 시작 | 예산={budget:,.0f} | "
            f"당일거래={self._daily.total_trades}/{self.max_daily_trades} | "
            f"연속손실={self._daily.consecutive_losses}/{self.loss_limit}"
        )

        # 유니버스 중 상위 N개만 스캔 (속도 최적화)
        scan_list = self.universe[: self.top_n]
        signals: list[SniperSignal] = []

        for ticker in scan_list:
            sig = self._evaluate_ticker(ticker)
            if sig and sig.action in ("BUY", "SELL"):
                signals.append(sig)

        # BUY 신호만 점수순 정렬
        buy_signals = sorted(
            [s for s in signals if s.action == "BUY"],
            key=lambda x: x.score,
            reverse=True,
        )

        logger.info(
            f"[마이크로스나이퍼] 스캔 완료 | "
            f"총={len(scan_list)}종목 | 매수신호={len(buy_signals)}개"
        )

        return buy_signals[:3]  # 최대 3종목 동시 진입

    def get_agent_status(self) -> dict:
        """대시보드용 상태 딕셔너리"""
        self._reset_daily_if_needed()
        return {
            "name": self.AGENT_NAME,
            "enabled": self.cfg.get("enabled", True),
            "halted": self._daily.halted,
            "halt_reason": self._daily.halt_reason,
            "total_trades": self._daily.total_trades,
            "wins": self._daily.wins,
            "losses": self._daily.losses,
            "consecutive_losses": self._daily.consecutive_losses,
            "realized_pnl": self._daily.realized_pnl,
            "win_rate": (
                self._daily.wins / self._daily.total_trades
                if self._daily.total_trades > 0
                else 0.0
            ),
            "budget_pct": self.cfg["budget_pct"],
            "loss_limit": self.loss_limit,
            "adx_threshold": self.adx_threshold,
            "rsi_oversold": self.rsi_oversold,
            "rsi_overbought": self.rsi_overbought,
        }


if __name__ == "__main__":
    import logging
    logging.basicConfig(level=logging.INFO)
    config = load_config()
    sniper = MicroSniperAgent(config)
    status = sniper.get_agent_status()
    print("\n=== 마이크로 스나이퍼 상태 ===")
    for k, v in status.items():
        print(f"  {k}: {v}")
