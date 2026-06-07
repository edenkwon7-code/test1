"""
시뮬레이션 엔진 모듈
- BacktestEngine: 과거 데이터 기반 전략 검증
- OutOfSampleTester: 미지의 데이터(OOS) 검증
- PaperTradingEngine: 가상 잔고 기반 모의투자
- PerformanceMetrics: 성과 지표 계산
"""

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Optional

import numpy as np
import pandas as pd

from config_loader import load_config
from database import QuantDatabase
from KoreaDataProvider import get_provider as _get_kr_provider

logger = logging.getLogger(__name__)


@dataclass
class PerformanceReport:
    strategy_name: str
    start_date: str
    end_date: str
    initial_capital: float
    final_capital: float
    total_return: float
    annual_return: float
    sharpe_ratio: float
    sortino_ratio: float
    max_drawdown: float
    win_rate: float
    total_trades: int
    winning_trades: int
    losing_trades: int
    avg_win: float
    avg_loss: float
    profit_factor: float
    benchmark_return: float
    alpha: float
    equity_curve: pd.Series = field(default_factory=pd.Series)

    def to_dict(self) -> dict:
        return {
            k: v for k, v in self.__dict__.items() if k != "equity_curve"
        }

    def print_summary(self):
        print(f"\n{'='*60}")
        print(f"  {self.strategy_name} 성과 요약")
        print(f"{'='*60}")
        print(f"  기간: {self.start_date} ~ {self.end_date}")
        print(f"  초기 자본: {self.initial_capital:,.0f}")
        print(f"  최종 자본: {self.final_capital:,.0f}")
        print(f"  총 수익률: {self.total_return:.2%}")
        print(f"  연환산 수익률: {self.annual_return:.2%}")
        print(f"  샤프 비율: {self.sharpe_ratio:.3f}")
        print(f"  소르티노 비율: {self.sortino_ratio:.3f}")
        print(f"  최대 낙폭(MDD): {self.max_drawdown:.2%}")
        print(f"  승률: {self.win_rate:.2%}")
        print(f"  총 거래 수: {self.total_trades}")
        print(f"  수익 거래: {self.winning_trades} | 손실 거래: {self.losing_trades}")
        print(f"  평균 수익: {self.avg_win:.2%} | 평균 손실: {self.avg_loss:.2%}")
        print(f"  수익 팩터: {self.profit_factor:.2f}")
        print(f"  벤치마크 수익률: {self.benchmark_return:.2%}")
        print(f"  알파: {self.alpha:.2%}")
        print(f"{'='*60}")


class PerformanceCalculator:
    """성과 지표 계산기"""

    @staticmethod
    def calc_returns(equity_curve: pd.Series) -> pd.Series:
        return equity_curve.pct_change().dropna()

    @staticmethod
    def calc_sharpe(returns: pd.Series, risk_free: float = 0.02) -> float:
        if returns.empty or returns.std() == 0:
            return 0.0
        excess = returns - risk_free / 252
        return float(excess.mean() / excess.std() * np.sqrt(252))

    @staticmethod
    def calc_sortino(returns: pd.Series, target: float = 0.0) -> float:
        if returns.empty:
            return 0.0
        downside = returns[returns < target]
        if len(downside) == 0 or downside.std() == 0:
            return float("inf")
        return float(returns.mean() * 252 / (downside.std() * np.sqrt(252)))

    @staticmethod
    def calc_mdd(equity_curve: pd.Series) -> float:
        if equity_curve.empty:
            return 0.0
        rolling_max = equity_curve.cummax()
        drawdown = (equity_curve - rolling_max) / rolling_max
        return float(drawdown.min())

    @staticmethod
    def calc_annual_return(total_return: float, days: int) -> float:
        if days <= 0:
            return 0.0
        years = days / 365
        return float((1 + total_return) ** (1 / years) - 1)

    @staticmethod
    def calc_win_stats(trade_returns: list[float]) -> dict:
        if not trade_returns:
            return {"win_rate": 0, "avg_win": 0, "avg_loss": 0, "profit_factor": 0,
                    "winning": 0, "losing": 0}
        wins = [r for r in trade_returns if r > 0]
        losses = [r for r in trade_returns if r <= 0]
        avg_win = np.mean(wins) if wins else 0
        avg_loss = np.mean(losses) if losses else 0
        gross_profit = sum(wins)
        gross_loss = abs(sum(losses))
        profit_factor = gross_profit / gross_loss if gross_loss > 0 else float("inf")
        return {
            "win_rate": len(wins) / len(trade_returns),
            "avg_win": avg_win,
            "avg_loss": avg_loss,
            "profit_factor": profit_factor,
            "winning": len(wins),
            "losing": len(losses),
        }


def _fetch_multi(tickers: list[str], start: str, end: str) -> pd.DataFrame:
    """
    FinanceDataReader 멀티 티커 일괄 다운로드 → Close 가격 DataFrame 반환
    한국 6자리 종목코드 및 KS11/KQ11 지수코드 사용
    """
    return _get_kr_provider().get_multi_prices(tickers, start=start, end=end)


def _build_report(
    strategy_name, start_date, end_date,
    initial_capital, equity_series,
    trade_returns, bm_return
) -> "PerformanceReport":
    final_capital = float(equity_series.iloc[-1])
    total_return = (final_capital - initial_capital) / initial_capital
    days = (pd.Timestamp(end_date) - pd.Timestamp(start_date)).days
    returns = PerformanceCalculator.calc_returns(equity_series)
    ws = PerformanceCalculator.calc_win_stats(trade_returns)
    return PerformanceReport(
        strategy_name=strategy_name,
        start_date=start_date, end_date=end_date,
        initial_capital=initial_capital, final_capital=final_capital,
        total_return=total_return,
        annual_return=PerformanceCalculator.calc_annual_return(total_return, days),
        sharpe_ratio=PerformanceCalculator.calc_sharpe(returns),
        sortino_ratio=PerformanceCalculator.calc_sortino(returns),
        max_drawdown=PerformanceCalculator.calc_mdd(equity_series),
        win_rate=ws["win_rate"],
        total_trades=len(trade_returns),
        winning_trades=ws["winning"],
        losing_trades=ws["losing"],
        avg_win=ws["avg_win"],
        avg_loss=ws["avg_loss"],
        profit_factor=ws["profit_factor"],
        benchmark_return=bm_return,
        alpha=total_return - bm_return,
        equity_curve=equity_series,
    )


def _empty_report(name, start, end, capital) -> "PerformanceReport":
    return PerformanceReport(
        strategy_name=name, start_date=start, end_date=end,
        initial_capital=capital, final_capital=capital,
        total_return=0, annual_return=0, sharpe_ratio=0, sortino_ratio=0,
        max_drawdown=0, win_rate=0, total_trades=0, winning_trades=0,
        losing_trades=0, avg_win=0, avg_loss=0, profit_factor=0,
        benchmark_return=0, alpha=0,
    )


class SimpleBacktestRunner:
    """
    벡터화 MA 교차 백테스트 엔진 (트렌드라이더)
    신호를 미리 pandas rolling으로 계산 → 포트폴리오 추적 루프만 실행
    """

    def __init__(self, config: dict):
        self.config = config
        self.commission = config["backtest"]["commission_rate"]
        self.slippage = config["backtest"]["slippage_pct"]

    def _get_benchmark(self, start: str, end: str) -> float:
        """KOSPI 벤치마크 수익률 (FinanceDataReader)"""
        try:
            cfg = load_config()
            bm_ticker = cfg.get("universe", {}).get("benchmark", "KS11")
            return _get_kr_provider().get_benchmark_return(start, end)
        except Exception:
            return 0.0

    def run_momentum_backtest(
        self,
        tickers: list[str],
        start_date: str,
        end_date: str,
        initial_capital: float,
        ma_fast: int = 20,
        ma_slow: int = 60,
        strategy_name: str = "트렌드라이더",
    ) -> PerformanceReport:
        logger.info(f"[백테스트] {strategy_name}: {start_date} ~ {end_date}")

        # ── 1. 데이터 일괄 수집 ──────────────────────────────
        close = _fetch_multi(tickers, start_date, end_date)
        if close.empty:
            return _empty_report(strategy_name, start_date, end_date, initial_capital)

        # ── 2. 신호 벡터화 계산 (룩어헤드 없음: shift(1)) ───
        ma_f = close.rolling(ma_fast).mean().shift(1)
        ma_s = close.rolling(ma_slow).mean().shift(1)
        # +1=매수유지, -1=매도/회피
        signal = (ma_f > ma_s).astype(int)

        valid_cols = signal.columns[signal.notna().any()].tolist()
        if not valid_cols:
            return _empty_report(strategy_name, start_date, end_date, initial_capital)

        # ── 3. 포트폴리오 시뮬레이션 ─────────────────────────
        cash = float(initial_capital)
        positions: dict[str, dict] = {}
        equity_curve: list[float] = []
        trade_returns: list[float] = []
        n_stocks = len(valid_cols)

        for date in close.index:
            # 매도 체크
            for ticker in list(positions.keys()):
                if ticker not in close.columns:
                    continue
                sig_val = signal.at[date, ticker] if ticker in signal.columns else 0
                if sig_val == 0:
                    pos = positions.pop(ticker)
                    price = float(close.at[date, ticker])
                    exec_p = price * (1 - self.slippage)
                    proceeds = pos["qty"] * exec_p * (1 - self.commission)
                    cash += proceeds
                    trade_returns.append((exec_p - pos["cost"]) / pos["cost"])

            # 매수 체크
            for ticker in valid_cols:
                if ticker in positions:
                    continue
                sig_val = signal.at[date, ticker] if ticker in signal.columns else 0
                if sig_val == 1:
                    price = float(close.at[date, ticker])
                    if pd.isna(price) or price <= 0:
                        continue
                    alloc = cash / max(n_stocks, 1)
                    exec_p = price * (1 + self.slippage)
                    cost_total = alloc * (1 + self.commission)
                    if cost_total <= cash and alloc > 0:
                        qty = alloc / exec_p
                        positions[ticker] = {"qty": qty, "cost": exec_p}
                        cash -= cost_total

            # 일별 포트폴리오 평가
            pos_val = sum(
                pos["qty"] * float(close.at[date, t])
                for t, pos in positions.items()
                if t in close.columns and not pd.isna(close.at[date, t])
            )
            equity_curve.append(cash + pos_val)

        equity_series = pd.Series(equity_curve, index=close.index)
        bm_return = self._get_benchmark(start_date, end_date)
        return _build_report(strategy_name, start_date, end_date,
                             initial_capital, equity_series, trade_returns, bm_return)


class PaperTradingEngine:
    """
    모의투자 엔진 (Paper Trading)
    가상 DB 잔고로 실제와 동일한 거래 흐름 시뮬레이션
    """

    def __init__(self, config: dict, db: QuantDatabase):
        self.config = config
        self.db = db
        self.pt_cfg = config["paper_trading"]
        self.commission_rate = self.pt_cfg["commission_rate"]
        self.slippage_pct = self.pt_cfg["slippage_pct"]
        self.mode = "paper"

        # 일일 MDD 보정용 트래킹 — 입출금을 제외한 실제 손익만 측정
        self._day_str: str = ""             # "YYYY-MM-DD"
        self._day_start_capital: float = 0.0  # 오늘 첫 평가 시 총자산
        self._day_net_cash_flow: float = 0.0  # 오늘 누적 순입출금액

        # 초기 포트폴리오 설정
        portfolio = db.get_portfolio(self.mode)
        if portfolio.get("total_capital", 0) == 0:
            initial = self.pt_cfg["initial_capital"]
            db.upsert_portfolio(
                total_capital=initial,
                cash=initial,
                invested=0,
                total_pnl=0,
                daily_pnl=0,
                daily_pnl_pct=0,
                mode=self.mode,
            )
            logger.info(f"[모의투자] 초기 자본 설정: {initial:,.0f}")

    def _reset_daily_tracking(self, total_value: float) -> None:
        """날짜가 바뀌면 day_start_capital·net_cash_flow를 초기화한다."""
        today = datetime.now().strftime("%Y-%m-%d")
        if self._day_str != today:
            self._day_str = today
            # DB에 이미 기록된 당일 시작 자본이 있으면 재사용, 없으면 지금 값을 기록
            saved = self.db.get_day_start_capital(today, mode=self.mode)
            if saved > 0:
                self._day_start_capital = saved
            else:
                self._day_start_capital = total_value
                self.db.set_day_start_capital(today, total_value, mode=self.mode)
            # 당일 입출금 합계도 DB에서 복원 (재시작 후에도 보정값 유지)
            self._day_net_cash_flow = self.db.get_daily_cash_flow(today, mode=self.mode)
            logger.info(
                f"[일일보정] 날짜 전환 → {today} | "
                f"시작자산={self._day_start_capital:,.0f} | "
                f"누적입출금={self._day_net_cash_flow:+,.0f}"
            )

    def register_cash_flow(self, amount: float, note: str = "") -> None:
        """
        가상 입출금 등록 — MDD 계산에서 해당 금액을 제외해 오인 킬스위치를 방지.

        amount > 0 : 입금 (포트폴리오 현금 증가 + MDD 기준선 보정)
        amount < 0 : 출금 (포트폴리오 현금 감소 + MDD 기준선 보정)
        """
        today = datetime.now().strftime("%Y-%m-%d")
        self.db.add_daily_cash_flow(today, amount, note, mode=self.mode)
        self._day_net_cash_flow += amount

        # 포트폴리오 현금 반영
        portfolio = self.db.get_portfolio(self.mode)
        new_cash = max(0.0, portfolio.get("cash", 0) + amount)
        new_total = new_cash + portfolio.get("invested", 0)
        self.db.upsert_portfolio(
            total_capital=new_total,
            cash=new_cash,
            invested=portfolio.get("invested", 0),
            total_pnl=portfolio.get("total_pnl", 0),
            daily_pnl=portfolio.get("daily_pnl", 0),
            daily_pnl_pct=portfolio.get("daily_pnl_pct", 0),
            mode=self.mode,
        )
        action = "입금" if amount >= 0 else "출금"
        logger.info(
            f"[가상{action}] {abs(amount):,.0f}원 | 현금→{new_cash:,.0f} | "
            f"오늘 누적입출금={self._day_net_cash_flow:+,.0f}"
        )

    def get_portfolio_state(self) -> dict:
        portfolio = self.db.get_portfolio(self.mode)
        positions = self.db.get_positions(self.mode)

        # 현재가로 시가 평가액 업데이트 (KoreaDataProvider)
        provider = _get_kr_provider()
        total_invested = 0
        for pos in positions:
            try:
                curr_price = provider.get_current_price(pos["ticker"])
                if curr_price:
                    self.db.upsert_position(
                        ticker=pos["ticker"],
                        agent_name=pos["agent_name"],
                        quantity=pos["quantity"],
                        avg_cost=pos["avg_cost"],
                        current_price=curr_price,
                        mode=self.mode,
                    )
                    total_invested += pos["quantity"] * curr_price
                else:
                    total_invested += pos.get("market_value", 0)
            except Exception:
                total_invested += pos.get("market_value", 0)

        cash = portfolio.get("cash", self.pt_cfg["initial_capital"])
        total_value = cash + total_invested
        initial = self.pt_cfg["initial_capital"]
        total_pnl = total_value - initial

        # ── 일일 손익 계산 (입출금 보정 포함) ────────────────────────
        # 공식: daily_pnl_pct = (현재총자산 - 시작자산 - 당일순입출금) / 시작자산
        self._reset_daily_tracking(total_value)
        day_start = self._day_start_capital if self._day_start_capital > 0 else total_value
        daily_pnl = total_value - day_start - self._day_net_cash_flow
        daily_pnl_pct = daily_pnl / day_start if day_start > 0 else 0.0

        self.db.upsert_portfolio(
            total_capital=total_value,
            cash=cash,
            invested=total_invested,
            total_pnl=total_pnl,
            daily_pnl=daily_pnl,
            daily_pnl_pct=daily_pnl_pct,
            mode=self.mode,
        )

        return {
            "total_capital": total_value,
            "cash": cash,
            "invested": total_invested,
            "total_pnl": total_pnl,
            "total_pnl_pct": total_pnl / initial if initial > 0 else 0.0,
            "daily_pnl": daily_pnl,
            "daily_pnl_pct": daily_pnl_pct,
            "day_start_capital": day_start,
            "day_net_cash_flow": self._day_net_cash_flow,
            "positions": self.db.get_positions(self.mode),
        }

    def execute_buy(
        self,
        ticker: str,
        agent_name: str,
        amount: float,
        reason: str = "",
        regime: str = "",
    ) -> bool:
        portfolio = self.db.get_portfolio(self.mode)
        cash = portfolio.get("cash", 0)

        if amount > cash:
            amount = cash * 0.95  # 가용 현금의 95%

        if amount <= 0:
            logger.warning(f"[모의투자] {ticker} 매수 실패: 잔고 부족")
            return False

        try:
            price = _get_kr_provider().get_current_price(ticker)
            if price is None:
                return False
        except Exception as e:
            logger.error(f"[모의투자] {ticker} 가격 조회 실패: {e}")
            return False

        exec_price = price * (1 + self.slippage_pct)
        commission = amount * self.commission_rate
        net_amount = amount - commission
        quantity = net_amount / exec_price
        total_cost = amount

        if total_cost > cash:
            logger.warning(f"[모의투자] {ticker} 매수 실패: 잔고 부족")
            return False

        # 기존 포지션 확인 (평균단가 업데이트)
        existing = next(
            (p for p in self.db.get_positions(self.mode)
             if p["ticker"] == ticker and p["agent_name"] == agent_name),
            None,
        )
        if existing:
            total_qty = existing["quantity"] + quantity
            avg_cost = (existing["avg_cost"] * existing["quantity"] + exec_price * quantity) / total_qty
            self.db.upsert_position(ticker, agent_name, total_qty, avg_cost, exec_price, self.mode)
        else:
            self.db.upsert_position(ticker, agent_name, quantity, exec_price, exec_price, self.mode)

        new_cash = cash - total_cost
        self.db.upsert_portfolio(
            total_capital=portfolio.get("total_capital", 0) - commission,
            cash=new_cash,
            invested=portfolio.get("invested", 0) + net_amount,
            total_pnl=portfolio.get("total_pnl", 0),
            daily_pnl=portfolio.get("daily_pnl", 0),
            daily_pnl_pct=portfolio.get("daily_pnl_pct", 0),
            mode=self.mode,
        )

        self.db.record_trade(
            ticker=ticker, agent_name=agent_name, action="BUY",
            quantity=quantity, price=exec_price, commission=commission,
            total_amount=total_cost, reason=reason, regime=regime, mode=self.mode,
        )

        logger.info(
            f"[모의투자] 매수 체결: {ticker} | {quantity:.4f}주 @ {exec_price:,.2f} "
            f"| 총액={total_cost:,.0f} | 수수료={commission:,.0f}"
        )
        return True

    def execute_sell(
        self,
        ticker: str,
        agent_name: str,
        reason: str = "",
        regime: str = "",
    ) -> bool:
        positions = self.db.get_positions(self.mode)
        pos = next(
            (p for p in positions if p["ticker"] == ticker and p["agent_name"] == agent_name),
            None,
        )
        if not pos:
            logger.warning(f"[모의투자] {ticker} 매도 실패: 포지션 없음")
            return False

        try:
            price = _get_kr_provider().get_current_price(ticker)
            if price is None:
                return False
        except Exception as e:
            logger.error(f"[모의투자] {ticker} 가격 조회 실패: {e}")
            return False

        exec_price = price * (1 - self.slippage_pct)
        quantity = pos["quantity"]
        gross_proceeds = quantity * exec_price
        commission = gross_proceeds * self.commission_rate
        net_proceeds = gross_proceeds - commission

        portfolio = self.db.get_portfolio(self.mode)
        new_cash = portfolio.get("cash", 0) + net_proceeds

        self.db.remove_position(ticker, agent_name, self.mode)
        self.db.upsert_portfolio(
            total_capital=portfolio.get("total_capital", 0) - commission,
            cash=new_cash,
            invested=max(0, portfolio.get("invested", 0) - pos.get("market_value", 0)),
            total_pnl=portfolio.get("total_pnl", 0),
            daily_pnl=portfolio.get("daily_pnl", 0),
            daily_pnl_pct=portfolio.get("daily_pnl_pct", 0),
            mode=self.mode,
        )

        self.db.record_trade(
            ticker=ticker, agent_name=agent_name, action="SELL",
            quantity=quantity, price=exec_price, commission=commission,
            total_amount=net_proceeds, reason=reason, regime=regime, mode=self.mode,
        )

        pnl = (exec_price - pos["avg_cost"]) * quantity
        pnl_pct = (exec_price - pos["avg_cost"]) / pos["avg_cost"]
        logger.info(
            f"[모의투자] 매도 체결: {ticker} | {quantity:.4f}주 @ {exec_price:,.2f} "
            f"| PnL={pnl:+,.0f} ({pnl_pct:+.2%})"
        )
        return True


class BollingerRSIBacktestRunner:
    """
    벡터화 볼린저밴드 + RSI 역추세 전략 백테스트 (스윙마스터)
    신호 전체를 pandas rolling으로 선계산 → 포트폴리오 루프만 실행
    """

    def __init__(self, config: dict):
        self.config = config
        self.commission = config["backtest"]["commission_rate"]
        self.slippage = config["backtest"]["slippage_pct"]
        sw_cfg = config["agents"]["swing_master"]
        self.bb_period = sw_cfg["bollinger"]["period"]
        self.bb_std = sw_cfg["bollinger"]["std_dev"]
        self.rsi_period = sw_cfg["rsi"]["period"]
        self.rsi_oversold = sw_cfg["rsi"]["oversold"]
        self.rsi_overbought = sw_cfg["rsi"]["overbought"]
        self.stop_loss = -0.07  # -7% 손절

    @staticmethod
    def _calc_rsi_df(close_df: pd.DataFrame, period: int) -> pd.DataFrame:
        delta = close_df.diff()
        gain = delta.clip(lower=0).rolling(period).mean()
        loss = (-delta.clip(upper=0)).rolling(period).mean()
        rs = gain / loss.replace(0, float("inf"))
        return 100 - (100 / (1 + rs))

    def run(
        self,
        tickers: list[str],
        start_date: str,
        end_date: str,
        initial_capital: float,
        strategy_name: str = "스윙마스터",
    ) -> PerformanceReport:
        logger.info(f"[백테스트] {strategy_name}: {start_date} ~ {end_date}")

        # ── 1. 데이터 일괄 수집 ──────────────────────────────
        close = _fetch_multi(tickers, start_date, end_date)
        if close.empty:
            return _empty_report(strategy_name, start_date, end_date, initial_capital)

        # ── 2. 신호 벡터화 계산 (shift(1) → 룩어헤드 방지) ──
        mid = close.rolling(self.bb_period).mean().shift(1)
        std = close.rolling(self.bb_period).std().shift(1)
        lower_band = mid - self.bb_std * std
        rsi = self._calc_rsi_df(close, self.rsi_period).shift(1)

        # 매수 조건: 가격 ≤ 하단밴드 AND RSI ≤ 과매도
        buy_sig = (close <= lower_band) & (rsi <= self.rsi_oversold)
        # 매도 조건: 가격 ≥ 중앙선 OR RSI ≥ 과매수
        exit_sig = (close >= mid) | (rsi >= self.rsi_overbought)

        # ── 3. 포트폴리오 시뮬레이션 ─────────────────────────
        cash = float(initial_capital)
        positions: dict[str, dict] = {}
        equity_curve: list[float] = []
        trade_returns: list[float] = []
        cols = close.columns.tolist()

        for date in close.index:
            # 손절 / 익절 매도
            for ticker in list(positions.keys()):
                if ticker not in close.columns:
                    continue
                pos = positions[ticker]
                price = float(close.at[date, ticker])
                if pd.isna(price):
                    continue
                pnl_pct = (price - pos["cost"]) / pos["cost"]
                should_exit = (
                    exit_sig.at[date, ticker] if ticker in exit_sig.columns else False
                ) or pnl_pct <= self.stop_loss
                if should_exit:
                    exec_p = price * (1 - self.slippage)
                    proceeds = pos["qty"] * exec_p * (1 - self.commission)
                    cash += proceeds
                    trade_returns.append((exec_p - pos["cost"]) / pos["cost"])
                    del positions[ticker]

            # 매수
            for ticker in cols:
                if ticker in positions:
                    continue
                should_buy = buy_sig.at[date, ticker] if ticker in buy_sig.columns else False
                if not should_buy:
                    continue
                price = float(close.at[date, ticker])
                if pd.isna(price) or price <= 0:
                    continue
                # 스윙마스터: 현금의 15%를 종목 수로 나눔 (최대 분산)
                alloc = cash * 0.15 / max(len(cols), 1)
                exec_p = price * (1 + self.slippage)
                cost_total = alloc * (1 + self.commission)
                if cost_total <= cash and alloc > 0:
                    qty = alloc / exec_p
                    target = float(mid.at[date, ticker]) if not pd.isna(mid.at[date, ticker]) else price * 1.05
                    positions[ticker] = {"qty": qty, "cost": exec_p, "target": target}
                    cash -= cost_total

            # 일별 평가
            pos_val = sum(
                pos["qty"] * float(close.at[date, t])
                for t, pos in positions.items()
                if t in close.columns and not pd.isna(close.at[date, t])
            )
            equity_curve.append(cash + pos_val)

        equity_series = pd.Series(equity_curve, index=close.index)
        try:
            bm_return = _get_kr_provider().get_benchmark_return(start_date, end_date)
        except Exception:
            bm_return = 0.0

        return _build_report(strategy_name, start_date, end_date,
                             initial_capital, equity_series, trade_returns, bm_return)


class BuyAndHoldRunner:
    """벤치마크: 균등 비중 매수 후 보유 (Buy & Hold) — 벡터화"""

    def __init__(self, config: dict):
        self.commission = config["backtest"]["commission_rate"]

    def run(
        self,
        tickers: list[str],
        start_date: str,
        end_date: str,
        initial_capital: float,
        strategy_name: str = "균등비중 Buy & Hold",
    ) -> PerformanceReport:
        logger.info(f"[백테스트] {strategy_name}: {start_date} ~ {end_date}")

        close = _fetch_multi(tickers, start_date, end_date)
        if close.empty:
            return _empty_report(strategy_name, start_date, end_date, initial_capital)

        n = len(close.columns)
        per_stock = initial_capital / n
        # 초기 주수 계산 (수수료 차감)
        p0 = close.iloc[0]
        shares = ((per_stock * (1 - self.commission)) / p0).where(p0 > 0, 0)
        # 벡터화 시가평가
        equity_series = (close * shares).sum(axis=1)

        try:
            bm_return = _get_kr_provider().get_benchmark_return(start_date, end_date)
        except Exception:
            bm_return = 0.0

        final_capital = float(equity_series.iloc[-1])
        total_return = (final_capital - initial_capital) / initial_capital
        days = (pd.Timestamp(end_date) - pd.Timestamp(start_date)).days
        returns = PerformanceCalculator.calc_returns(equity_series)

        return PerformanceReport(
            strategy_name=strategy_name,
            start_date=start_date, end_date=end_date,
            initial_capital=initial_capital, final_capital=final_capital,
            total_return=total_return,
            annual_return=PerformanceCalculator.calc_annual_return(total_return, days),
            sharpe_ratio=PerformanceCalculator.calc_sharpe(returns),
            sortino_ratio=PerformanceCalculator.calc_sortino(returns),
            max_drawdown=PerformanceCalculator.calc_mdd(equity_series),
            win_rate=1.0, total_trades=n, winning_trades=n, losing_trades=0,
            avg_win=total_return, avg_loss=0,
            profit_factor=float("inf") if total_return > 0 else 0,
            benchmark_return=bm_return,
            alpha=total_return - bm_return,
            equity_curve=equity_series,
        )


class BacktestEngine:
    """전체 백테스트 오케스트레이터 (5년치 + OOS + DB 저장)"""

    def __init__(self, config: dict, db: Optional[QuantDatabase] = None):
        self.config = config
        self.db = db
        self.momentum_runner = SimpleBacktestRunner(config)
        self.swing_runner = BollingerRSIBacktestRunner(config)
        self.bnh_runner = BuyAndHoldRunner(config)

    def run_all_strategies(self, save_to_db: bool = True) -> dict[str, PerformanceReport]:
        import uuid
        cfg = self.config["backtest"]
        stocks = self.config["universe"]["stocks"]

        # 5년치 IS 기간 (코로나 폭락 2020 포함)
        is_start = "2019-01-01"
        is_end   = "2023-12-31"
        oos_start = cfg.get("out_of_sample_start", "2024-01-01")
        oos_end   = cfg.get("out_of_sample_end",   "2024-12-31")
        capital   = cfg["initial_capital"]

        tr_cfg = self.config["agents"]["trend_rider"]
        results = {}
        run_id = datetime.now().strftime("%Y%m%d_%H%M%S") + "_" + str(uuid.uuid4())[:8]

        # ── 1. 트렌드라이더 IS (2019-2023) ──────────────────────
        logger.info("[백테스트] ① 트렌드라이더 IS (2019-2023, 코로나 포함)...")
        results["trend_rider_is"] = self.momentum_runner.run_momentum_backtest(
            tickers=stocks, start_date=is_start, end_date=is_end,
            initial_capital=capital,
            ma_fast=tr_cfg["ma_periods"]["fast"],
            ma_slow=tr_cfg["ma_periods"]["slow"],
            strategy_name="트렌드라이더 IS (2019-2023)",
        )

        # ── 2. 트렌드라이더 OOS (2024) ──────────────────────────
        logger.info("[백테스트] ② 트렌드라이더 OOS (2024)...")
        results["trend_rider_oos"] = self.momentum_runner.run_momentum_backtest(
            tickers=stocks, start_date=oos_start, end_date=oos_end,
            initial_capital=capital,
            ma_fast=tr_cfg["ma_periods"]["fast"],
            ma_slow=tr_cfg["ma_periods"]["slow"],
            strategy_name="트렌드라이더 OOS (2024)",
        )

        # ── 3. 스윙마스터 IS (2019-2023) ────────────────────────
        logger.info("[백테스트] ③ 스윙마스터 IS (2019-2023)...")
        results["swing_master_is"] = self.swing_runner.run(
            tickers=stocks, start_date=is_start, end_date=is_end,
            initial_capital=capital,
            strategy_name="스윙마스터 IS (2019-2023)",
        )

        # ── 4. 스윙마스터 OOS (2024) ────────────────────────────
        logger.info("[백테스트] ④ 스윙마스터 OOS (2024)...")
        results["swing_master_oos"] = self.swing_runner.run(
            tickers=stocks, start_date=oos_start, end_date=oos_end,
            initial_capital=capital,
            strategy_name="스윙마스터 OOS (2024)",
        )

        # ── 5. 벤치마크: Buy & Hold (2019-2023) ─────────────────
        logger.info("[백테스트] ⑤ 벤치마크 Buy & Hold (2019-2023)...")
        results["buy_and_hold"] = self.bnh_runner.run(
            tickers=stocks, start_date=is_start, end_date=is_end,
            initial_capital=capital,
            strategy_name="균등비중 Buy & Hold (2019-2023)",
        )

        # ── DB 저장 ──────────────────────────────────────────────
        if save_to_db and self.db is not None:
            logger.info(f"[백테스트] 결과 DB 저장 중... (run_id={run_id})")
            for key, report in results.items():
                try:
                    self.db.save_backtest_result(run_id, report)
                    logger.info(f"[백테스트] DB 저장 완료: {report.strategy_name}")
                except Exception as e:
                    logger.error(f"[백테스트] DB 저장 실패: {e}")

        return results


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
    )
    config = load_config()
    db = QuantDatabase(config["system"]["db_path"])
    engine = BacktestEngine(config, db=db)
    print("\n" + "="*60)
    print("  AI 퀀트 시스템 — 백테스트 실행")
    print("  기간: 2019-2023 (IS, 코로나 폭락 포함) + 2024 (OOS)")
    print("="*60)
    results = engine.run_all_strategies(save_to_db=True)
    for name, report in results.items():
        report.print_summary()
    print("\n✅ 백테스트 결과가 DB에 저장되었습니다. 대시보드 '백테스트' 탭에서 확인하세요.")
