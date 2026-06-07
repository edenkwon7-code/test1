"""
트레이딩 엔진 - 메인 자동화 루프
비서실장 → 에이전트 → 모의투자/실전 실행까지 전 파이프라인 오케스트레이션
킬스위치, 서킷브레이커, 리스크 관리 통합
"""

import logging
import time
from datetime import datetime, timedelta
from typing import Optional

import pandas as pd
import schedule

from ChiefOfStaff import AgentAllocation, ChiefOfStaff, MarketRegime, RegimeSignal
from Agents import AgentFactory, TradeSignal
from SimulationEngine import PaperTradingEngine
from database import QuantDatabase
from config_loader import load_config
import KakaoAuth as _KakaoAuth

# DQN 경험 수집 (선택적 — 임포트 실패해도 동작)
try:
    from DQNChief import DQNChief, build_state, compute_reward, ACTIONS
    _dqn_available = True
except Exception:
    _dqn_available = False
    logger = logging.getLogger(__name__)

logger = logging.getLogger(__name__)

# NotificationManager는 선택적 로드 (환경변수 미설정 시에도 동작)
try:
    from NotificationEngine import NotificationManager
    _notifier = NotificationManager()
except Exception:
    _notifier = None


class RiskManager:
    """4중 리스크 관리 레이어"""

    def __init__(self, config: dict, db: QuantDatabase):
        self.config = config
        self.risk_cfg = config["risk_management"]
        self.db = db

    def check_position_size(self, amount: float, total_capital: float) -> float:
        """포지션 크기 제한 (최대 10%)"""
        max_position = total_capital * self.risk_cfg["position_max_pct"]
        if amount > max_position:
            logger.warning(
                f"[리스크] 포지션 크기 제한 적용: {amount:,.0f} → {max_position:,.0f}"
            )
            return max_position
        return amount

    def check_max_positions(self, mode: str = "paper") -> bool:
        """최대 포지션 수 체크"""
        positions = self.db.get_positions(mode)
        if len(positions) >= self.risk_cfg["max_positions"]:
            logger.warning(f"[리스크] 최대 포지션 수 도달: {len(positions)}/{self.risk_cfg['max_positions']}")
            return False
        return True

    def check_stop_loss(
        self,
        ticker: str,
        agent_name: str,
        current_price: float,
        mode: str = "paper",
    ) -> bool:
        """스탑로스 체크: 손실 7% 이상 시 매도 신호"""
        positions = self.db.get_positions(mode)
        pos = next(
            (p for p in positions if p["ticker"] == ticker and p["agent_name"] == agent_name),
            None,
        )
        if pos and pos["avg_cost"] > 0:
            loss_pct = (current_price - pos["avg_cost"]) / pos["avg_cost"]
            if loss_pct <= -self.risk_cfg["stop_loss_pct"]:
                logger.warning(
                    f"[리스크] 스탑로스 발동: {ticker} | 손실={loss_pct:.2%} "
                    f"(한도={-self.risk_cfg['stop_loss_pct']:.2%})"
                )
                return True
        return False

    def check_take_profit(
        self,
        ticker: str,
        agent_name: str,
        current_price: float,
        mode: str = "paper",
    ) -> bool:
        """이익실현 체크: 수익 15% 이상 시 매도 신호"""
        positions = self.db.get_positions(mode)
        pos = next(
            (p for p in positions if p["ticker"] == ticker and p["agent_name"] == agent_name),
            None,
        )
        if pos and pos["avg_cost"] > 0:
            gain_pct = (current_price - pos["avg_cost"]) / pos["avg_cost"]
            if gain_pct >= self.risk_cfg["take_profit_pct"]:
                logger.info(
                    f"[리스크] 이익실현 발동: {ticker} | 수익={gain_pct:.2%} "
                    f"(목표={self.risk_cfg['take_profit_pct']:.2%})"
                )
                return True
        return False


class TradingEngine:
    """
    메인 트레이딩 엔진

    실행 파이프라인:
    1. 비서실장 시장 레짐 분석
    2. 레짐별 에이전트 예산 배분
    3. 각 에이전트 신호 생성
    4. 리스크 관리 필터 적용
    5. 모의투자/실전 주문 실행
    6. DB 기록 및 성과 추적
    """

    def __init__(self, config: dict = None):
        self.config = config or load_config()
        self.mode = self.config["system"]["mode"]

        # 핵심 모듈 초기화
        self.db = QuantDatabase(self.config["system"]["db_path"])
        self.chief = ChiefOfStaff(self.config)
        self.agents = AgentFactory.create_all(self.config)
        self.risk = RiskManager(self.config, self.db)

        # 모의투자 엔진
        self.paper_engine = PaperTradingEngine(self.config, self.db)

        self._running = False
        self._last_regime: Optional[RegimeSignal] = None
        self._cycle_count = 0

        logger.info(f"[트레이딩엔진] 초기화 완료 | 모드: {self.mode.upper()}")

    @property
    def is_running(self) -> bool:
        return self._running

    def activate_kill_switch(self, reason: str = "수동"):
        """긴급 킬스위치 활성화 — DB 영구 저장 + 이메일 발송 + 전량 청산"""
        self.chief.activate_kill_switch(reason)
        self.db.set_kill_switch(True, reason)
        self.db.log_system_event("CRITICAL", "TradingEngine", f"킬스위치 발동: {reason}")
        closed = self.emergency_liquidate_all(reason)
        if _notifier:
            portfolio = self.db.get_portfolio(self.mode)
            _notifier.send_kill_switch_alert(
                reason=reason,
                positions_closed=closed,
                total_value=portfolio.get("total_capital", 0),
            )

    def deactivate_kill_switch(self):
        """킬스위치 해제 — DB 상태 초기화"""
        self.chief.deactivate_kill_switch()
        self.db.set_kill_switch(False, "수동 해제")
        self.db.log_system_event("WARNING", "TradingEngine", "킬스위치 해제됨")

    def emergency_liquidate_all(self, reason: str = "킬스위치") -> int:
        """
        비상 전량 청산 — 보유 포지션을 모두 시장가 매도
        Returns: 청산된 포지션 수
        """
        positions = self.db.get_positions(self.mode)
        closed = 0

        logger.critical("=" * 55)
        logger.critical("[비상청산] ⚠️  전량 청산 명령 수신!")
        logger.critical(f"[비상청산] 사유: {reason}")
        logger.critical(f"[비상청산] 청산 대상 포지션: {len(positions)}개")

        if not positions:
            logger.critical("[비상청산] 보유 포지션 없음 — 현금 보유 상태 확인됨")
            logger.critical("[비상청산] ✅ 모든 포지션을 시장가로 전량 청산(매도)하고 가동을 중지합니다")
            logger.critical("=" * 55)
            return 0

        for pos in positions:
            ticker = pos["ticker"]
            agent = pos["agent_name"]
            qty = pos["quantity"]
            avg_cost = pos["avg_cost"]
            try:
                from KoreaDataProvider import get_provider as _krp
                curr_price = _krp().get_current_price(ticker) or avg_cost

                pnl_pct = (curr_price - avg_cost) / avg_cost if avg_cost > 0 else 0
                self.paper_engine.execute_sell(ticker, agent, reason=f"비상청산: {reason}", regime="비상정지")
                closed += 1
                logger.critical(
                    f"[비상청산] ✅ {ticker} 청산 완료 | {qty:.4f}주 @ {curr_price:,.2f} | PnL={pnl_pct:+.2%}"
                )
            except Exception as e:
                logger.error(f"[비상청산] ❌ {ticker} 청산 실패: {e}")
                # 실패해도 DB에서 포지션 기록 삭제
                try:
                    self.db.remove_position(ticker, agent, self.mode)
                    closed += 1
                except Exception:
                    pass

        portfolio = self.db.get_portfolio(self.mode)
        logger.critical(f"[비상청산] 청산 완료: {closed}/{len(positions)}개 포지션")
        logger.critical(f"[비상청산] 현금 전환 총액: {portfolio.get('cash', 0):,.0f}원")
        logger.critical("[비상청산] ✅ 모든 포지션을 시장가로 전량 청산(매도)하고 가동을 중지합니다")
        logger.critical("=" * 55)

        self.db.log_system_event(
            "CRITICAL", "TradingEngine",
            f"비상청산 완료: {closed}개 포지션 청산 | 사유={reason}"
        )
        return closed

    def _check_stoploss_takeprofit(self, regime: str):
        """기존 포지션 스탑로스/이익실현 체크"""
        from KoreaDataProvider import get_provider as _krp

        positions = self.db.get_positions(self.mode)
        for pos in positions:
            try:
                curr_price = _krp().get_current_price(pos["ticker"])
                if curr_price is None:
                    continue

                if self.risk.check_stop_loss(pos["ticker"], pos["agent_name"], curr_price, self.mode):
                    self.paper_engine.execute_sell(
                        pos["ticker"], pos["agent_name"],
                        reason="스탑로스 발동", regime=regime
                    )
                elif self.risk.check_take_profit(pos["ticker"], pos["agent_name"], curr_price, self.mode):
                    self.paper_engine.execute_sell(
                        pos["ticker"], pos["agent_name"],
                        reason="이익실현 발동", regime=regime
                    )
            except Exception as e:
                logger.error(f"[트레이딩엔진] 스탑로스 체크 오류 [{pos['ticker']}]: {e}")

    def _execute_agent_signals(
        self,
        agent_name: str,
        signals: list[TradeSignal],
        budget: float,
        regime_str: str,
    ):
        """에이전트 신호를 실제 주문으로 변환 및 실행"""
        if not signals or budget <= 0:
            return

        portfolio = self.db.get_portfolio(self.mode)
        total_capital = portfolio.get("total_capital", 0)

        for signal in signals:
            if signal.action == "BUY":
                # 포지션 수 제한 체크
                if not self.risk.check_max_positions(self.mode):
                    break

                # 이미 보유 중인 종목 스킵
                existing = next(
                    (p for p in self.db.get_positions(self.mode)
                     if p["ticker"] == signal.ticker and p["agent_name"] == agent_name),
                    None,
                )
                if existing:
                    continue

                # 배분 예산 내에서 매수 금액 계산
                alloc_amount = budget * signal.target_pct if signal.target_pct > 0 else budget / max(len(signals), 1)
                alloc_amount = self.risk.check_position_size(alloc_amount, total_capital)

                success = self.paper_engine.execute_buy(
                    ticker=signal.ticker,
                    agent_name=agent_name,
                    amount=alloc_amount,
                    reason=signal.reason,
                    regime=regime_str,
                )
                if success:
                    self.db.log_system_event(
                        "INFO", agent_name,
                        f"매수 체결: {signal.ticker} | {signal.reason[:100]}"
                    )
                    # ── 카카오톡 거래 체결 알림 (2️⃣ 실시간 거래 내역 보고) ─
                    try:
                        for _ku in self.db.get_kakao_notify_users():
                            _KakaoAuth.send_trade_execution(
                                _ku["kakao_access_token"],
                                "BUY", signal.ticker, signal.ticker,
                                agent_name, alloc_amount,
                                signal.reason[:150],
                            )
                    except Exception:
                        pass

    def _check_db_kill_switch(self) -> bool:
        """DB Emergency_Stop 상태 감지 — True면 즉시 청산 후 정지"""
        ks = self.db.get_kill_switch()
        if ks["emergency_stop"] and not self.chief.is_kill_switch_active:
            reason = ks.get("kill_switch_reason", "DB 비상정지 감지")
            logger.critical(f"[트레이딩엔진] DB Emergency_Stop=True 감지 | 사유: {reason}")
            self.chief.activate_kill_switch(reason)
            self.emergency_liquidate_all(reason)
            if _notifier:
                portfolio = self.db.get_portfolio(self.mode)
                _notifier.send_kill_switch_alert(
                    reason=reason,
                    positions_closed=len(self.db.get_positions(self.mode)),
                    total_value=portfolio.get("total_capital", 0),
                )
            return True
        return self.chief.is_kill_switch_active

    def run_monitoring_cycle(self) -> dict:
        """
        모니터링 사이클 — 장 중 매시간 실행
        ─────────────────────────────────────
        • 비서실장 레짐 재분석 (VIX·지수 감시)
        • 기존 포지션 스탑로스 / 이익실현 체크
        • MDD 일일 한도 체크
        신호 생성 없음, 신규 포지션 없음
        """
        self._monitor_count = getattr(self, "_monitor_count", 0) + 1
        cycle_start = datetime.now()
        logger.info(f"\n{'─'*50}")
        logger.info(
            f"[모니터링] #{self._monitor_count} 시작: "
            f"{cycle_start.strftime('%H:%M:%S')} KST"
        )

        result = {
            "type": "monitoring",
            "cycle": self._monitor_count,
            "timestamp": cycle_start.isoformat(),
            "regime": None,
            "vix": 0,
            "closed": 0,
            "error": None,
        }

        if self._check_db_kill_switch():
            result["error"] = "킬스위치 활성 — 모니터링 중단"
            return result

        try:
            # 1. 비서실장 레짐 분석
            regime_signal, _alloc, can_trade, reason = self.chief.run_analysis()
            self._last_regime = regime_signal
            self.db.record_regime(regime_signal)
            result["regime"] = regime_signal.regime.value
            result["vix"]    = regime_signal.vix

            if not can_trade:
                logger.warning(f"[모니터링] 거래 정지 상태: {reason}")
                return result

            regime_str = regime_signal.regime.name

            # 2. 스탑로스 / 익절 체크
            positions_before = len(self.db.get_positions(self.mode))
            self._check_stoploss_takeprofit(regime_str)
            positions_after = len(self.db.get_positions(self.mode))
            closed = max(positions_before - positions_after, 0)
            result["closed"] = closed

            # 3. MDD 일일 손실 한도 체크
            portfolio_state  = self.paper_engine.get_portfolio_state()
            daily_pnl_pct    = portfolio_state.get("daily_pnl_pct", 0)
            self.chief.update_daily_pnl(daily_pnl_pct)

            daily_loss_limit = self.config["risk_management"].get("daily_max_drawdown", 0.05)
            if daily_pnl_pct <= -daily_loss_limit and not self.chief.is_kill_switch_active:
                mdd_reason = (
                    f"일일 손실 한도 초과 "
                    f"(손실={daily_pnl_pct:.2%}, 한도={-daily_loss_limit:.2%})"
                )
                logger.critical(f"[MDD 방어] {mdd_reason}")
                self.db.set_kill_switch(True, mdd_reason, daily_loss_pct=daily_pnl_pct)
                self.db.log_system_event("CRITICAL", "TradingEngine", f"MDD 초과: {mdd_reason}")
                self.activate_kill_switch(mdd_reason)
                if _notifier:
                    _notifier.send_circuit_breaker_alert(daily_pnl_pct, mdd_reason)
                result["error"] = mdd_reason
                return result

            elapsed = (datetime.now() - cycle_start).seconds
            logger.info(
                f"[모니터링] #{self._monitor_count} 완료 | "
                f"레짐={result['regime']} | VIX={result['vix']:.1f} | "
                f"청산={closed}건 | {elapsed}초"
            )

        except Exception as e:
            logger.error(f"[모니터링] 사이클 오류: {e}", exc_info=True)
            result["error"] = str(e)
            self.db.log_system_event("ERROR", "TradingEngine", f"모니터링 오류: {str(e)[:200]}")

        return result

    def run_cycle(self) -> dict:
        """
        단일 트레이딩 사이클 실행

        Returns: 사이클 결과 요약 dict
        """
        self._cycle_count += 1
        cycle_start = datetime.now()
        logger.info(f"\n{'='*50}")
        logger.info(f"[트레이딩엔진] 사이클 #{self._cycle_count} 시작: {cycle_start.strftime('%Y-%m-%d %H:%M:%S')}")

        result = {
            "cycle": self._cycle_count,
            "timestamp": cycle_start.isoformat(),
            "regime": None,
            "tradeable": False,
            "signals_generated": 0,
            "trades_executed": 0,
            "error": None,
        }

        # ── 사이클 시작 즉시 DB 킬스위치 감지 ──────────────
        if self._check_db_kill_switch():
            result["error"] = "킬스위치/비상정지 활성 — 사이클 중단"
            result["tradeable"] = False
            logger.critical("[트레이딩엔진] 킬스위치 활성 상태 — 사이클 강제 종료")
            return result

        try:
            # 1. 비서실장 분석
            regime_signal, allocation, can_trade, reason = self.chief.run_analysis()
            self._last_regime = regime_signal
            self.db.record_regime(regime_signal)

            result["regime"] = regime_signal.regime.value
            result["tradeable"] = can_trade
            result["vix"] = regime_signal.vix

            # 거래 불가 상태
            if not can_trade:
                logger.warning(f"[트레이딩엔진] 거래 정지: {reason}")
                self.db.log_system_event("WARNING", "TradingEngine", f"거래 정지: {reason}")
                return result

            # 2. 포트폴리오 현황
            portfolio_state = self.paper_engine.get_portfolio_state()
            total_capital = portfolio_state["total_capital"]
            cash = portfolio_state["cash"]
            regime_str = regime_signal.regime.name

            logger.info(
                f"[포트폴리오] 총 자산={total_capital:,.0f} | "
                f"현금={cash:,.0f} | 투자={portfolio_state['invested']:,.0f}"
            )

            # 3. 기존 포지션 스탑로스/이익실현 체크
            self._check_stoploss_takeprofit(regime_str)

            # 4. 에이전트별 예산 배분 및 신호 생성
            invest_cash = portfolio_state["cash"]  # 재조회

            # ── 자본 분리: 스나이퍼 고정 예산 먼저 차감 ─────────
            # 전시 레짐이면 allocation.sniper_fixed_amount = 0 (비서실장이 이미 처리)
            sniper_budget = min(
                float(allocation.sniper_fixed_amount),
                invest_cash,
            )
            core_cash = max(0.0, invest_cash - sniper_budget)

            budgets = {
                "value_finder": core_cash * allocation.value_finder,
                "trend_rider":  core_cash * allocation.trend_rider,
                "swing_master": core_cash * allocation.swing_master,
                "micro_sniper": sniper_budget,           # 정액제 — 비율 무관
            }

            logger.info(
                f"[자본분리] 투자가능현금={invest_cash:,.0f}원 | "
                f"스나이퍼 고정={sniper_budget:,.0f}원 | "
                f"핵심자본={core_cash:,.0f}원 "
                f"(밸류={budgets['value_finder']:,.0f} / "
                f"트렌드={budgets['trend_rider']:,.0f} / "
                f"스윙={budgets['swing_master']:,.0f})"
            )

            total_signals = 0
            agent_map = {k: v for k, v in self.agents.items()}

            # ── 에이전트별 개별 목표 수익 설정 로드 ─────────────
            _agent_tp_map: dict[str, float] = {}
            try:
                _tp_users = self.db.list_users()
                if _tp_users:
                    _tu = _tp_users[0]
                    _agent_tp_map = {
                        "value_finder": float(_tu.get("target_profit_value",  0.0) or 0.0),
                        "trend_rider":  float(_tu.get("target_profit_trend",  0.0) or 0.0),
                        "swing_master": float(_tu.get("target_profit_swing",  0.0) or 0.0),
                        "micro_sniper": float(_tu.get("target_profit_sniper", 0.0) or 0.0),
                    }
            except Exception:
                pass

            for agent_key, agent in agent_map.items():
                budget = budgets.get(agent_key, 0.0)
                agent_cfg = self.config["agents"].get(agent_key, {})
                if budget <= 0 or not agent_cfg.get("enabled", True):
                    logger.info(f"[{agent_key}] 예산 0 또는 비활성 → 스킵")
                    continue

                # ── 에이전트별 가동 중단(halted) 여부 체크 ──────
                _halted = False
                if hasattr(agent, "is_halted"):
                    _halted = agent.is_halted
                elif hasattr(agent, "halted"):
                    _halted = agent.halted
                if _halted:
                    logger.warning(f"[{agent_key}] 당일 가동 중단 상태 → 스킵")
                    continue

                # ── 에이전트별 개별 목표 수익 달성 시 자동 퇴근 ──
                # 결정론적(Deterministic) 계산 — LLM 개입 없음, 순수 파이썬 사칙연산
                _ag_tp = _agent_tp_map.get(agent_key, 0.0)
                if _ag_tp > 0:
                    try:
                        _today_trades = self.db.get_trades(mode=self.mode, limit=500)
                        from datetime import date as _date_cls
                        import json as _json
                        _today_str = _date_cls.today().isoformat()
                        _ag_trades = [
                            t for t in _today_trades
                            if t.get("agent_name") == agent_key
                            and str(t.get("executed_at", ""))[:10] == _today_str
                        ]
                        # ── Ground Truth: 매수 총액 / 매도 총액 분리 계산 ──
                        # 공식: (매도 총액 - 매수 총액) / 배정 예산
                        _buy_total  = sum(t.get("total_amount", 0) for t in _ag_trades if t.get("action") == "BUY")
                        _sell_total = sum(t.get("total_amount", 0) for t in _ag_trades if t.get("action") == "SELL")
                        _ag_realized = _sell_total - _buy_total  # 실현 손익 (양수=이익)
                        _ag_budget   = max(budget, 1)            # 에이전트 배정 예산
                        _ag_pnl_pct  = _ag_realized / _ag_budget # 배정 예산 기준 수익률
                        if _ag_pnl_pct >= _ag_tp:
                            # ── 고정 템플릿 메시지 (AI 생성 금지) ──────────
                            _retire_template = (
                                f"🏆 [{agent_key}] 금일 목표 수익 달성 "
                                f"(목표: {_ag_tp:.1%} / 실제: {_ag_pnl_pct:.1%}) "
                                f"— 전량 익절 후 조기 퇴근(Sleep)합니다."
                            )
                            # ── Ground Truth 딕셔너리 (검증용 원본 데이터) ─
                            _ground_truth = {
                                "에이전트":      agent_key,
                                "판정_일자":     _today_str,
                                "판정_시각":     datetime.now().strftime("%H:%M:%S"),
                                "당일_매수_총액": int(_buy_total),
                                "당일_매도_총액": int(_sell_total),
                                "실현_손익":     int(_ag_realized),
                                "배정_예산":     int(_ag_budget),
                                "수익률_pct":    round(_ag_pnl_pct * 100, 4),
                                "목표_수익률_pct": round(_ag_tp * 100, 4),
                                "거래_건수":     len(_ag_trades),
                                "계산_공식":     "(매도총액 - 매수총액) / 배정예산",
                                "LLM_개입":      False,
                            }
                            logger.info(f"[개별 TP] {_retire_template}")
                            logger.info(f"[Ground Truth] {_ground_truth}")
                            # 퇴근 이벤트 DB 기록 (템플릿 + Ground Truth 분리 저장)
                            self.db.log_system_event("INFO", agent_key, _retire_template)
                            self.db.log_system_event(
                                "INFO", agent_key,
                                f"RETIRE_EVENT:{_json.dumps(_ground_truth, ensure_ascii=False)}",
                            )
                            # ── 카카오톡 조기 퇴근 알림 (3️⃣ 목표 달성 보고) ─
                            try:
                                for _ku in self.db.get_kakao_notify_users():
                                    _KakaoAuth.send_retire_alert(
                                        _ku["kakao_access_token"],
                                        agent_key, _ag_tp, _ag_pnl_pct,
                                        int(_ag_realized), int(_ag_budget),
                                        len(_ag_trades),
                                    )
                            except Exception:
                                pass
                            # ── 물리적 매매 차단 (sleep_mode = True) ────────
                            if hasattr(agent, "_daily"):
                                agent._daily.halted = True
                                agent._daily.halt_reason = (
                                    f"목표 수익 달성 "
                                    f"(목표={_ag_tp:.1%} / 실제={_ag_pnl_pct:.1%})"
                                )
                            elif hasattr(agent, "halted"):
                                agent.halted = True
                            continue
                    except Exception as _atp_err:
                        logger.debug(f"[개별 TP 체크] {agent_key}: {_atp_err}")

                try:
                    signals = agent.generate_signals(budget)
                    total_signals += len(signals)
                    self._execute_agent_signals(agent_key, signals, budget, regime_str)
                except Exception as e:
                    logger.error(f"[{agent_key}] 신호 생성 오류: {e}")
                    self.db.log_system_event("ERROR", agent_key, f"신호 생성 오류: {str(e)[:200]}")

            result["signals_generated"] = total_signals

            # 5. 일일 손익 업데이트 + MDD 한도 체크
            final_state = self.paper_engine.get_portfolio_state()
            initial_capital = self.config["paper_trading"]["initial_capital"]
            total_pnl_pct = (final_state["total_capital"] - initial_capital) / initial_capital
            daily_pnl_pct = portfolio_state.get("daily_pnl_pct", 0)
            self.chief.update_daily_pnl(daily_pnl_pct)

            # ── MDD 일일 손실 한도(-5%) 도달 시 자동 비상청산 ──
            daily_loss_limit = self.config["risk_management"].get("daily_max_drawdown", 0.05)
            if daily_pnl_pct <= -daily_loss_limit and not self.chief.is_kill_switch_active:
                mdd_reason = f"일일 손실 한도 초과 (손실={daily_pnl_pct:.2%}, 한도={-daily_loss_limit:.2%})"
                logger.critical(f"[MDD 방어] {mdd_reason}")
                self.db.set_kill_switch(True, mdd_reason, daily_loss_pct=daily_pnl_pct)
                self.db.log_system_event("CRITICAL", "TradingEngine", f"MDD 한도 초과: {mdd_reason}")
                self.activate_kill_switch(mdd_reason)
                if _notifier:
                    _notifier.send_circuit_breaker_alert(daily_pnl_pct, mdd_reason)
                result["error"] = mdd_reason
                return result

            # ── Daily Take Profit — 단타 목표 수익 달성 시 에이전트 Sleep ──
            try:
                _daily_tp = self.config.get("risk_management", {}).get("daily_target_profit", 0.0)
                if _daily_tp <= 0:
                    # DB에 저장된 첫 번째 사용자 설정에서 읽기 (단일 테넌트 모의투자)
                    _all_users = self.db.list_users()
                    if _all_users:
                        _daily_tp = float(_all_users[0].get("daily_target_profit", 0.0))

                if _daily_tp > 0 and daily_pnl_pct >= _daily_tp:
                    _tp_agents = ["swing_master", "micro_sniper"]
                    _halted_any = False
                    for _ak in _tp_agents:
                        _ag = self.agents.get(_ak)
                        if _ag is None:
                            continue
                        # 마이크로 스나이퍼: halt 플래그 설정
                        if hasattr(_ag, "_daily") and not _ag._daily.halted:
                            _ag._daily.halted = True
                            _ag._daily.halt_reason = (
                                f"일일 단타 목표 수익 달성 ({daily_pnl_pct:.2%} ≥ {_daily_tp:.2%}) — 당일 매매 종료"
                            )
                            _halted_any = True
                        # 스윙마스터: 동일 패턴 (halted 속성이 있으면 설정)
                        elif hasattr(_ag, "halted") and not _ag.halted:
                            _ag.halted = True
                            _halted_any = True
                    if _halted_any:
                        _tp_msg = (
                            f"🏆 금일 단타 목표 수익 달성! "
                            f"수익={daily_pnl_pct:.2%} ≥ 목표={_daily_tp:.2%}. "
                            f"스윙마스터·마이크로스나이퍼 당일 매매 종료."
                        )
                        logger.info(f"[Daily TP] {_tp_msg}")
                        self.db.log_system_event("INFO", "TradingEngine", _tp_msg)
                        result["daily_tp_triggered"] = True
            except Exception as _tp_err:
                logger.debug(f"[Daily TP] 체크 오류 (무시): {_tp_err}")

            # 6. 성과 기록
            self.db.record_daily_performance(
                total_value=final_state["total_capital"],
                daily_return=daily_pnl_pct,
                cumulative_return=total_pnl_pct,
                drawdown=0,
                mode=self.mode,
            )

            # 7. DQN 경험 저장 (리플레이 버퍼 축적)
            if _dqn_available:
                try:
                    _dqn_inst = getattr(self, "_dqn_chief", None)
                    if _dqn_inst is None:
                        self._dqn_chief = DQNChief(db_path=self.config["system"]["db_path"])
                        _dqn_inst = self._dqn_chief

                    # 에이전트 성과 지표 계산
                    _trades_all = self.db.get_trades(mode=self.mode, limit=200)
                    _vf_m = DQNChief.compute_agent_metrics(_trades_all, "value_finder")
                    _tr_m = DQNChief.compute_agent_metrics(_trades_all, "trend_rider")
                    _sm_m = DQNChief.compute_agent_metrics(_trades_all, "swing_master")

                    _cash_ratio = final_state["cash"] / max(final_state["total_capital"], 1)
                    _perf_hist  = self.db.get_performance_history(mode=self.mode, days=30)
                    _mdd_val    = _perf_hist[-1]["drawdown"] if _perf_hist else 0.0

                    # 현재 상태 벡터
                    _cur_state = build_state(
                        vix=regime_signal.vix,
                        ma_alignment=regime_signal.ma_alignment,
                        macd_signal=regime_signal.macd_signal,
                        vf_winrate=_vf_m["win_rate"],  vf_sharpe=_vf_m["sharpe"],
                        tr_winrate=_tr_m["win_rate"],  tr_sharpe=_tr_m["sharpe"],
                        sm_winrate=_sm_m["win_rate"],  sm_sharpe=_sm_m["sharpe"],
                        portfolio_daily_return=daily_pnl_pct,
                        portfolio_mdd=_mdd_val,
                        cash_ratio=_cash_ratio,
                    )

                    # 현재 배분 → 가장 가까운 액션 ID 매핑
                    _alloc_vec = [
                        allocation.value_finder,
                        allocation.trend_rider,
                        allocation.swing_master,
                    ]
                    _best_match = 0
                    _best_dist  = float("inf")
                    for _ai, _act in enumerate(ACTIONS):
                        _dist = (
                            abs(_act["value_finder"] - _alloc_vec[0]) +
                            abs(_act["trend_rider"]  - _alloc_vec[1]) +
                            abs(_act["swing_master"] - _alloc_vec[2])
                        )
                        if _dist < _best_dist:
                            _best_dist  = _dist
                            _best_match = _ai

                    # 보상 계산
                    _hit_risk = (
                        daily_pnl_pct <= -(self.config["risk_management"].get("daily_max_drawdown", 0.05))
                    )
                    _reward = compute_reward(
                        daily_return=daily_pnl_pct,
                        vix=regime_signal.vix,
                        hit_risk_limit=_hit_risk,
                    )

                    # 이전 상태가 있으면 경험 저장
                    _prev_state = getattr(self, "_dqn_prev_state", None)
                    if _prev_state is not None:
                        _dqn_inst.store_experience(
                            state=_prev_state,
                            action=_best_match,
                            reward=_reward,
                            next_state=_cur_state,
                            done=False,
                        )
                        logger.info(
                            f"[DQN] 경험 저장 | 액션={ACTIONS[_best_match]['label']} | "
                            f"보상={_reward:.4f} | 버퍼={_dqn_inst.get_buffer_size()}건"
                        )

                        # 버퍼 32건 이상이면 자동 미니 학습 (3배치)
                        if _dqn_inst.get_buffer_size() >= 32:
                            _train_res = _dqn_inst.train_episode(n_batches=3)
                            logger.info(f"[DQN] 자동 학습 | {_train_res['msg']}")

                    self._dqn_prev_state = _cur_state

                except Exception as _dqn_err:
                    logger.warning(f"[DQN] 경험 저장 오류 (무시): {_dqn_err}")

            elapsed = (datetime.now() - cycle_start).seconds
            logger.info(
                f"[트레이딩엔진] 사이클 #{self._cycle_count} 완료 | "
                f"소요={elapsed}초 | 신호={total_signals}개"
            )

        except Exception as e:
            logger.error(f"[트레이딩엔진] 사이클 오류: {e}", exc_info=True)
            result["error"] = str(e)
            self.db.log_system_event("ERROR", "TradingEngine", f"사이클 오류: {str(e)[:200]}")

        return result

    def start_scheduler(self, interval_hours: int = 24):
        """스케줄러 기반 자동 실행 (매일 장 시작 후)"""
        self._running = True
        logger.info(f"[트레이딩엔진] 스케줄러 시작 | 주기: {interval_hours}시간")

        # 즉시 1회 실행
        self.run_cycle()

        # 이후 정기 실행
        schedule.every(interval_hours).hours.do(self.run_cycle)

        try:
            while self._running:
                schedule.run_pending()
                time.sleep(60)
        except KeyboardInterrupt:
            logger.info("[트레이딩엔진] 사용자 중단")
        finally:
            self._running = False

    def stop(self):
        """엔진 정지"""
        self._running = False
        logger.info("[트레이딩엔진] 엔진 정지")

    # ═══════════════════════════════════════════════════════════
    # 다중 사용자 병렬 처리 엔진
    # ═══════════════════════════════════════════════════════════

    @staticmethod
    def _run_user_cycle(user: dict, config: dict, db_path: str) -> dict:
        """
        단일 사용자 사이클 (Thread 내부 실행용).
        각 사용자 독립 엔진 인스턴스 생성 → 사이클 실행.
        """
        user_id    = user["id"]
        user_mode  = QuantDatabase.user_mode(user_id)
        user_cfg   = {**config}
        user_cfg["system"]         = {**config["system"], "mode": user_mode, "db_path": db_path}
        user_cfg["paper_trading"]  = {**config["paper_trading"],
                                       "initial_capital": user.get("initial_capital",
                                           config["paper_trading"]["initial_capital"])}

        try:
            engine = TradingEngine(user_cfg)
            result = engine.run_cycle()
            return {
                "user_id":   user_id,
                "user_name": user.get("name", "?"),
                "result":    result,
                "error":     None,
            }
        except Exception as e:
            logger.error(f"[멀티유저] user_id={user_id} 오류: {e}")
            return {
                "user_id":   user_id,
                "user_name": user.get("name", "?"),
                "result":    {},
                "error":     str(e),
            }

    def run_multi_user_cycle(self, max_workers: int = 4) -> list[dict]:
        """
        전체 사용자 병렬 사이클 실행 (ThreadPoolExecutor).
        긴급정지(emergency_stop=1) 사용자는 자동 제외.
        """
        from concurrent.futures import ThreadPoolExecutor, as_completed
        users = self.db.get_all_users()
        active_users = [u for u in users if not u.get("emergency_stop")]
        if not active_users:
            logger.info("[멀티유저] 활성 사용자 없음")
            return []

        db_path = self.config["system"]["db_path"]
        results = []
        logger.info(f"[멀티유저] {len(active_users)}명 병렬 사이클 시작 (workers={max_workers})")

        with ThreadPoolExecutor(max_workers=max_workers) as pool:
            futures = {
                pool.submit(
                    TradingEngine._run_user_cycle, u, self.config, db_path
                ): u
                for u in active_users
            }
            for fut in as_completed(futures):
                res = fut.result()
                results.append(res)
                status = "✅" if not res["error"] else "❌"
                logger.info(
                    f"[멀티유저] {status} {res['user_name']}(id={res['user_id']}) "
                    f"| {res['result'].get('trades_executed', 0)}건 체결"
                )

        logger.info(f"[멀티유저] 전체 완료 — {len(results)}/{len(active_users)}명 처리")
        return results

    def get_system_status(self) -> dict:
        """시스템 전체 상태 반환 (대시보드용)"""
        portfolio = self.db.get_portfolio(self.mode)
        positions = self.db.get_positions(self.mode)

        chief_info = {
            "kill_switch": self.chief.is_kill_switch_active,
            "circuit_breaker": self.chief.is_circuit_breaker_active,
            "regime": self._last_regime.regime.value if self._last_regime else "분석 전",
            "vix": self._last_regime.vix if self._last_regime else 0,
            "confidence": self._last_regime.confidence if self._last_regime else 0,
        }

        return {
            "mode": self.mode,
            "cycle_count": self._cycle_count,
            "is_running": self._running,
            "chief": chief_info,
            "portfolio": portfolio,
            "positions": positions,
            "agent_status": {k: v.get_agent_status() for k, v in self.agents.items()},
        }


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    config = load_config()
    engine = TradingEngine(config)
    print("=== 퀀트 트레이딩 엔진 단일 사이클 실행 ===")
    result = engine.run_cycle()
    print(f"\n결과: {result}")
