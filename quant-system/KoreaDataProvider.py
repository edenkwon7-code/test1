"""
KoreaDataProvider.py — 한국 주식 전용 데이터 공급자
════════════════════════════════════════════════════════
• 종목/지수 데이터 : FinanceDataReader (fdr) — 6자리 종목코드
• VIX (글로벌 리스크): yfinance (^VIX) — 한국 장에도 글로벌 리스크 지표로 활용
• 벤치마크         : KOSPI (KS11) via fdr

주요 ticker 예시:
  '005930'  → 삼성전자 (KRW)
  'KS11'    → KOSPI 지수
  'KQ11'    → KOSDAQ 지수
  '^VIX'    → CBOE 변동성 지수 (yfinance 전용)
"""

import logging
from datetime import datetime, timedelta
from typing import Optional

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


def _period_to_start(period: str) -> str:
    """'2y','1y','6mo','3mo','1d' → 시작일 문자열(YYYY-MM-DD)"""
    now = datetime.now()
    period = period.strip().lower()
    if period.endswith("y"):
        start = now - timedelta(days=365 * int(period[:-1]))
    elif period.endswith("mo"):
        start = now - timedelta(days=30 * int(period[:-2]))
    elif period.endswith("d"):
        start = now - timedelta(days=int(period[:-1]))
    else:
        start = now - timedelta(days=365)
    return start.strftime("%Y-%m-%d")


class KoreaDataProvider:
    """
    한국 주식 시장 데이터 공급자 (싱글턴 권장)

    모든 가격 데이터는 FinanceDataReader를 통해 수집합니다.
    VIX만 예외적으로 yfinance를 사용합니다 (글로벌 리스크 지표).
    """

    KOSPI_TICKER = "KS11"
    KOSDAQ_TICKER = "KQ11"
    VIX_TICKER = "^VIX"

    def __init__(self):
        self._cache: dict = {}
        self._cache_time: dict = {}
        self._cache_ttl_sec = 3600  # 1시간 캐시

    # ── 내부 캐시 관리 ──────────────────────────────────

    def _is_valid(self, key: str) -> bool:
        if key not in self._cache:
            return False
        age = (datetime.now() - self._cache_time.get(key, datetime.min)).total_seconds()
        return age < self._cache_ttl_sec

    def _set(self, key: str, df: pd.DataFrame):
        self._cache[key] = df
        self._cache_time[key] = datetime.now()

    # ── 핵심 데이터 수집 메서드 ──────────────────────────

    def get_price_data(
        self,
        ticker: str,
        start: str = None,
        end: str = None,
        period: str = None,
    ) -> pd.DataFrame:
        """
        한국 주식 / KOSPI 지수 가격 데이터 수집 (fdr)

        Args:
            ticker: 6자리 종목코드 ('005930') 또는 지수 코드 ('KS11')
            start:  시작일 'YYYY-MM-DD'  (period보다 우선)
            end:    종료일 'YYYY-MM-DD'  (미지정 시 오늘)
            period: '2y' / '1y' / '6mo' / '3mo' / '1d'  (start 미지정 시 사용)

        Returns:
            DataFrame(Open/High/Low/Close/Volume), DatetimeIndex
        """
        if period and not start:
            start = _period_to_start(period)
        if not end:
            end = datetime.now().strftime("%Y-%m-%d")

        cache_key = f"fdr_{ticker}_{start}_{end}"
        if self._is_valid(cache_key):
            return self._cache[cache_key]

        try:
            import FinanceDataReader as fdr
            df = fdr.DataReader(ticker, start, end)
            if df is None or df.empty:
                logger.warning(f"[KoreaData] 빈 데이터 [{ticker}]")
                return pd.DataFrame()
            # 인덱스 DatetimeIndex 보장
            df.index = pd.to_datetime(df.index)
            # 컬럼명 정규화 (소문자 → 대문자 시작)
            rename = {c: c.capitalize() for c in df.columns if c.islower()}
            if rename:
                df = df.rename(columns=rename)
            self._set(cache_key, df)
            return df
        except Exception as e:
            logger.error(f"[KoreaData] 가격 데이터 수집 실패 [{ticker}]: {e}")
            return pd.DataFrame()

    def get_kospi_data(
        self,
        start: str = None,
        end: str = None,
        period: str = "1y",
    ) -> pd.DataFrame:
        """KOSPI 지수 데이터"""
        return self.get_price_data(self.KOSPI_TICKER, start=start, end=end, period=period)

    def get_vix_data(self, period: str = "3mo") -> pd.DataFrame:
        """VIX 지수 데이터 (yfinance 전용)"""
        cache_key = f"vix_{period}"
        if self._is_valid(cache_key):
            return self._cache[cache_key]
        try:
            import yfinance as yf
            df = yf.download(self.VIX_TICKER, period=period,
                             progress=False, auto_adjust=True)
            if not df.empty:
                self._set(cache_key, df)
            return df
        except Exception as e:
            logger.error(f"[KoreaData] VIX 데이터 수집 실패: {e}")
            return pd.DataFrame()

    def get_current_price(self, ticker: str) -> Optional[float]:
        """현재가 조회 (최근 10거래일 중 최신 종가)"""
        try:
            end = datetime.now().strftime("%Y-%m-%d")
            start = (datetime.now() - timedelta(days=10)).strftime("%Y-%m-%d")
            df = self.get_price_data(ticker, start=start, end=end)
            if df.empty:
                return None
            col = "Close" if "Close" in df.columns else df.columns[0]
            val = df[col].dropna()
            if val.empty:
                return None
            return float(np.asarray(val.iloc[-1]).flat[0])
        except Exception as e:
            logger.error(f"[KoreaData] 현재가 조회 실패 [{ticker}]: {e}")
            return None

    def get_multi_prices(
        self,
        tickers: list,
        start: str,
        end: str = None,
    ) -> pd.DataFrame:
        """
        여러 종목 종가 일괄 수집
        Returns: DataFrame(index=날짜, columns=ticker코드)
        """
        if not end:
            end = datetime.now().strftime("%Y-%m-%d")

        series_map = {}
        for ticker in tickers:
            df = self.get_price_data(ticker, start=start, end=end)
            if not df.empty:
                col = "Close" if "Close" in df.columns else df.columns[0]
                series_map[ticker] = df[col]

        if not series_map:
            return pd.DataFrame()

        result = pd.DataFrame(series_map)
        result.index = pd.to_datetime(result.index)
        return result.sort_index().dropna(how="all").ffill()

    def get_benchmark_return(self, start: str, end: str) -> float:
        """KOSPI 벤치마크 수익률 계산 (단순 수익률)"""
        try:
            df = self.get_kospi_data(start=start, end=end, period=None)
            if df.empty:
                return 0.0
            col = "Close" if "Close" in df.columns else df.columns[0]
            closes = df[col].dropna()
            if len(closes) < 2:
                return 0.0
            return float(closes.iloc[-1]) / float(closes.iloc[0]) - 1
        except Exception as e:
            logger.error(f"[KoreaData] 벤치마크 수익률 계산 실패: {e}")
            return 0.0


    def get_intraday_data(
        self,
        ticker: str,
        interval: str = "1m",
        bars: int = 200,
    ) -> pd.DataFrame:
        """
        분봉 데이터 수집 — MicroSniper 전용

        실전(키움 브릿지): KiwoomBridge get_minute_data() 우선 시도
        모의/폴백: yfinance 5분봉 (1d 범위) → 일봉 근사값 사용
        반환 컬럼: Open / High / Low / Close / Volume (DatetimeIndex)
        """
        cache_key = f"intraday_{ticker}_{interval}_{bars}"
        if self._is_valid(cache_key):
            return self._cache[cache_key]

        df = pd.DataFrame()

        # ── 1) KiwoomBridge REST 시도 (실전 모드 — Windows 브릿지 서버 필요) ──
        # KiwoomBridge.py는 Windows 전용이므로 직접 import 하지 않고
        # HTTP REST 요청으로만 호출한다 (모의투자 환경에서는 항상 폴백).
        try:
            import requests as _req
            _bridge_cfg = self._bridge_url()
            if _bridge_cfg:
                _resp = _req.get(
                    f"{_bridge_cfg}/minute",
                    params={"code": ticker, "count": bars, "tick": 1},
                    timeout=5,
                )
                if _resp.ok:
                    _raw = _resp.json()
                    if _raw:
                        df = pd.DataFrame(_raw)
                        df = self._normalize_ohlcv(df)
                        self._set(cache_key, df)
                        logger.info(f"[KoreaData] 키움 브릿지 1분봉 [{ticker}] {len(df)}행")
                        return df
        except Exception:
            pass

        # ── 2) yfinance 분봉 폴백 ──────────────────────────
        try:
            import yfinance as yf
            yf_ticker = f"{ticker}.KS" if not ticker.startswith("^") else ticker
            tf = yf.Ticker(yf_ticker)
            raw = tf.history(period="5d", interval="5m")
            if raw is not None and not raw.empty:
                df = raw[["Open", "High", "Low", "Close", "Volume"]].copy()
                df = df.dropna().tail(bars)
                self._set(cache_key, df)
                logger.info(f"[KoreaData] yfinance 5분봉 폴백 [{ticker}] {len(df)}행")
                return df
        except Exception as e:
            logger.debug(f"[KoreaData] yfinance 분봉 실패 [{ticker}]: {e}")

        # ── 3) 일봉 폴백 (지표 계산용 근사) ────────────────
        try:
            df_day = self.get_price_data(ticker, period="6mo")
            if not df_day.empty:
                df = df_day.tail(bars).copy()
                self._set(cache_key, df)
                logger.debug(f"[KoreaData] 일봉 폴백 [{ticker}] {len(df)}행")
                return df
        except Exception as e:
            logger.error(f"[KoreaData] 분봉 전체 실패 [{ticker}]: {e}")

        return pd.DataFrame()

    def _bridge_url(self) -> str | None:
        """키움 브릿지 서버 URL (config에 설정된 경우에만 반환)"""
        try:
            from config_loader import load_config
            cfg = load_config()
            url = cfg.get("broker", {}).get("live", {}).get("bridge_url", "")
            return url if url and url.startswith("http") else None
        except Exception:
            return None

    def _normalize_ohlcv(self, df: pd.DataFrame) -> pd.DataFrame:
        """컬럼명 정규화 + 오름차순 정렬 + NaN 제거"""
        rename = {}
        for c in df.columns:
            cl = c.lower()
            if cl in ("open", "시가"):    rename[c] = "Open"
            elif cl in ("high", "고가"):  rename[c] = "High"
            elif cl in ("low", "저가"):   rename[c] = "Low"
            elif cl in ("close", "종가"): rename[c] = "Close"
            elif cl in ("volume", "거래량"): rename[c] = "Volume"
        if rename:
            df = df.rename(columns=rename)
        df.index = pd.to_datetime(df.index)
        df = df.sort_index().dropna(subset=["Open", "High", "Low", "Close"])
        return df


# ── 싱글턴 ──────────────────────────────────────────────
_provider: Optional[KoreaDataProvider] = None


def get_provider() -> KoreaDataProvider:
    """프로세스 전역 KoreaDataProvider 싱글턴 반환"""
    global _provider
    if _provider is None:
        _provider = KoreaDataProvider()
    return _provider
