"""
BrokerAPI.py — 증권사 주문 실행 추상 인터페이스
─────────────────────────────────────────────────────
config.yaml의 system.mode에 따라 자동 분기됩니다.

  mode: paper  →  PaperBroker  (Replit DB 기반 모의투자, 현재 기본값)
  mode: live   →  LiveBroker   (KiwoomBridge 서버와 HTTP 통신)

실전 투자 아키텍처 (mode: live 시):
  ┌─────────────────────────────────────┐
  │  Replit (AI 전략 엔진)               │
  │  TradingEngine → LiveBroker         │
  └────────────┬────────────────────────┘
               │ HTTP/JSON (인터넷)
  ┌────────────▼────────────────────────┐
  │  KiwoomBridge.py (사용자 Windows PC) │
  │  Flask 서버 → 키움 OpenAPI COM       │
  └────────────┬────────────────────────┘
               │ COM
  ┌────────────▼────────────────────────┐
  │  키움증권 HTS → 실제 주문 체결       │
  └─────────────────────────────────────┘

사용 예:
    from BrokerAPI import get_broker
    broker = get_broker(config, db)
    broker.buy_market("AAPL", amount=1_000_000)
    broker.sell_market("AAPL", quantity=10)
    balance = broker.get_balance()
"""

import logging
from abc import ABC, abstractmethod
from datetime import datetime
from typing import Optional

import requests

logger = logging.getLogger(__name__)


# ══════════════════════════════════════════════════════════════
# 추상 기반 클래스
# ══════════════════════════════════════════════════════════════

class BrokerBase(ABC):
    """모든 브로커 구현체가 상속해야 하는 인터페이스"""

    @abstractmethod
    def get_balance(self) -> dict:
        """
        계좌 잔고 조회
        Returns: {"total_capital": float, "cash": float, "invested": float}
        """

    @abstractmethod
    def get_positions(self) -> list[dict]:
        """
        보유 포지션 목록 조회
        Returns: [{"ticker": str, "quantity": float, "avg_cost": float,
                   "current_price": float, "market_value": float, "unrealized_pnl": float}]
        """

    @abstractmethod
    def get_current_price(self, ticker: str) -> Optional[float]:
        """단일 종목 현재가 조회"""

    @abstractmethod
    def buy_market(self, ticker: str, agent_name: str, amount: float, regime: str = "") -> dict:
        """
        시장가 매수
        Args:
            ticker: 종목 코드 (예: "AAPL", "005930" for 삼성전자)
            agent_name: 주문을 낸 에이전트명
            amount: 매수 금액 (원화 기준)
            regime: 현재 레짐 (기록용)
        Returns: {"success": bool, "ticker": str, "quantity": float,
                  "exec_price": float, "message": str}
        """

    @abstractmethod
    def sell_market(self, ticker: str, agent_name: str, reason: str = "", regime: str = "") -> dict:
        """
        시장가 매도 (전량)
        Returns: {"success": bool, "ticker": str, "quantity": float,
                  "exec_price": float, "pnl": float, "message": str}
        """

    @property
    @abstractmethod
    def mode(self) -> str:
        """'paper' 또는 'live'"""


# ══════════════════════════════════════════════════════════════
# Paper Broker — 기존 DB 기반 모의투자 (변경 없음)
# ══════════════════════════════════════════════════════════════

class PaperBroker(BrokerBase):
    """
    모의투자 브로커 — SimulationEngine.PaperTradingEngine을 래핑합니다.
    Replit 서버에서 직접 실행됩니다.
    """

    def __init__(self, config: dict, db):
        from SimulationEngine import PaperTradingEngine
        self._config = config
        self._db = db
        self._engine = PaperTradingEngine(config, db)
        logger.info("[PaperBroker] 모의투자 브로커 초기화 완료")

    @property
    def mode(self) -> str:
        return "paper"

    def get_balance(self) -> dict:
        p = self._db.get_portfolio("paper")
        return {
            "total_capital": p.get("total_capital", 0),
            "cash":          p.get("cash", 0),
            "invested":      p.get("invested", 0),
        }

    def get_positions(self) -> list[dict]:
        return self._db.get_positions("paper")

    def get_current_price(self, ticker: str) -> Optional[float]:
        try:
            import yfinance as yf
            import numpy as np
            data = yf.download(ticker, period="1d", progress=False, auto_adjust=True)
            if data.empty:
                return None
            return float(np.asarray(data["Close"].iloc[-1]).flat[0])
        except Exception as e:
            logger.error(f"[PaperBroker] 현재가 조회 실패 [{ticker}]: {e}")
            return None

    def buy_market(self, ticker: str, agent_name: str, amount: float, regime: str = "") -> dict:
        try:
            success = self._engine.execute_buy(ticker, agent_name, amount, regime=regime)
            return {
                "success":    success,
                "ticker":     ticker,
                "quantity":   0,
                "exec_price": 0,
                "message":    "모의 매수 완료" if success else "모의 매수 실패",
            }
        except Exception as e:
            logger.error(f"[PaperBroker] 매수 오류 [{ticker}]: {e}")
            return {"success": False, "ticker": ticker, "message": str(e)}

    def sell_market(self, ticker: str, agent_name: str, reason: str = "", regime: str = "") -> dict:
        try:
            success = self._engine.execute_sell(ticker, agent_name, reason=reason, regime=regime)
            return {
                "success":    success,
                "ticker":     ticker,
                "quantity":   0,
                "exec_price": 0,
                "pnl":        0,
                "message":    "모의 매도 완료" if success else "모의 매도 실패",
            }
        except Exception as e:
            logger.error(f"[PaperBroker] 매도 오류 [{ticker}]: {e}")
            return {"success": False, "ticker": ticker, "message": str(e)}


# ══════════════════════════════════════════════════════════════
# Live Broker — KiwoomBridge 서버와 HTTP 통신
# ══════════════════════════════════════════════════════════════

class LiveBroker(BrokerBase):
    """
    실전 투자 브로커 — 사용자 Windows PC에서 실행 중인
    KiwoomBridge.py 서버와 HTTP/JSON으로 통신합니다.

    설정 위치: config.yaml > broker > live
      bridge_url: "http://YOUR_PC_IP:7777"   ← Windows PC의 내부 IP 또는 공인 IP
      bridge_secret: "your-secret-key"       ← 보안 키 (선택)
      account_number: "1234567890"           ← 키움 계좌번호
    """

    def __init__(self, config: dict, db):
        self._config = config
        self._db = db
        broker_cfg = config.get("broker", {}).get("live", {})
        self._bridge_url = broker_cfg.get("bridge_url", "http://localhost:7777").rstrip("/")
        self._secret = broker_cfg.get("bridge_secret", "")
        self._account = broker_cfg.get("account_number", "")
        self._timeout = broker_cfg.get("order_timeout_sec", 10)

        logger.info(
            f"[LiveBroker] 실전 브로커 초기화 | Bridge={self._bridge_url} "
            f"| 계좌={self._account[-4:] if self._account else '미설정'}(뒷4자리)"
        )

    @property
    def mode(self) -> str:
        return "live"

    def _headers(self) -> dict:
        h = {"Content-Type": "application/json"}
        if self._secret:
            h["X-Bridge-Secret"] = self._secret
        return h

    def _post(self, path: str, payload: dict) -> dict:
        """브릿지 서버에 POST 요청"""
        url = f"{self._bridge_url}{path}"
        try:
            resp = requests.post(url, json=payload, headers=self._headers(),
                                 timeout=self._timeout)
            resp.raise_for_status()
            return resp.json()
        except requests.ConnectionError:
            msg = f"KiwoomBridge 서버에 연결할 수 없습니다 ({url}). Windows PC가 실행 중인지 확인하세요."
            logger.error(f"[LiveBroker] {msg}")
            raise ConnectionError(msg)
        except requests.Timeout:
            msg = f"KiwoomBridge 응답 시간 초과 ({self._timeout}초)"
            logger.error(f"[LiveBroker] {msg}")
            raise TimeoutError(msg)
        except Exception as e:
            logger.error(f"[LiveBroker] 브릿지 통신 오류: {e}")
            raise

    def _get(self, path: str, params: dict = None) -> dict:
        """브릿지 서버에 GET 요청"""
        url = f"{self._bridge_url}{path}"
        try:
            resp = requests.get(url, params=params, headers=self._headers(),
                                timeout=self._timeout)
            resp.raise_for_status()
            return resp.json()
        except Exception as e:
            logger.error(f"[LiveBroker] 브릿지 GET 오류 [{path}]: {e}")
            raise

    def ping(self) -> bool:
        """브릿지 서버 생존 확인"""
        try:
            resp = requests.get(f"{self._bridge_url}/ping",
                                headers=self._headers(), timeout=5)
            return resp.status_code == 200
        except Exception:
            return False

    def get_balance(self) -> dict:
        """키움 실계좌 잔고 조회"""
        try:
            data = self._get("/balance", {"account": self._account})
            return {
                "total_capital": data.get("total_capital", 0),
                "cash":          data.get("cash", 0),
                "invested":      data.get("invested", 0),
            }
        except Exception as e:
            logger.error(f"[LiveBroker] 잔고 조회 실패: {e}")
            return {"total_capital": 0, "cash": 0, "invested": 0}

    def get_positions(self) -> list[dict]:
        """키움 실계좌 보유 포지션 조회"""
        try:
            data = self._get("/positions", {"account": self._account})
            return data.get("positions", [])
        except Exception as e:
            logger.error(f"[LiveBroker] 포지션 조회 실패: {e}")
            return []

    def get_current_price(self, ticker: str) -> Optional[float]:
        """키움 실시간 현재가 조회"""
        try:
            data = self._get("/price", {"ticker": ticker})
            return data.get("price")
        except Exception as e:
            logger.error(f"[LiveBroker] 현재가 조회 실패 [{ticker}]: {e}")
            return None

    def buy_market(self, ticker: str, agent_name: str, amount: float, regime: str = "") -> dict:
        """키움 시장가 매수 주문"""
        payload = {
            "account":    self._account,
            "ticker":     ticker,
            "agent_name": agent_name,
            "amount":     amount,
            "regime":     regime,
            "timestamp":  datetime.now().isoformat(),
        }
        logger.info(f"[LiveBroker] 실전 매수 주문 → {ticker} | 금액={amount:,.0f}원")
        try:
            result = self._post("/buy", payload)
            if result.get("success"):
                logger.info(
                    f"[LiveBroker] 매수 체결 확인 | {ticker} "
                    f"{result.get('quantity', 0):.2f}주 @ {result.get('exec_price', 0):,.2f}"
                )
            else:
                logger.warning(f"[LiveBroker] 매수 실패: {result.get('message')}")
            return result
        except Exception as e:
            return {"success": False, "ticker": ticker, "message": str(e)}

    def sell_market(self, ticker: str, agent_name: str, reason: str = "", regime: str = "") -> dict:
        """키움 시장가 매도 주문 (전량)"""
        payload = {
            "account":    self._account,
            "ticker":     ticker,
            "agent_name": agent_name,
            "reason":     reason,
            "regime":     regime,
            "timestamp":  datetime.now().isoformat(),
        }
        logger.info(f"[LiveBroker] 실전 매도 주문 → {ticker} | 사유={reason}")
        try:
            result = self._post("/sell", payload)
            if result.get("success"):
                logger.info(
                    f"[LiveBroker] 매도 체결 확인 | {ticker} "
                    f"PnL={result.get('pnl', 0):+,.0f}원"
                )
            else:
                logger.warning(f"[LiveBroker] 매도 실패: {result.get('message')}")
            return result
        except Exception as e:
            return {"success": False, "ticker": ticker, "message": str(e)}


# ══════════════════════════════════════════════════════════════
# 브로커 팩토리 — config.yaml mode에 따라 자동 선택
# ══════════════════════════════════════════════════════════════

def get_broker(config: dict, db) -> BrokerBase:
    """
    config.yaml의 system.mode에 따라 적절한 브로커를 반환합니다.

    mode: paper  →  PaperBroker  (모의투자, 기본값)
    mode: live   →  LiveBroker   (실전투자, KiwoomBridge 필요)
    """
    mode = config.get("system", {}).get("mode", "paper")

    if mode == "live":
        broker_cfg = config.get("broker", {}).get("live", {})
        if not broker_cfg.get("account_number"):
            logger.critical(
                "[BrokerAPI] ⚠️  mode=live 이지만 계좌번호가 설정되지 않았습니다! "
                "config.yaml > broker > live > account_number 를 설정하세요."
            )
        broker = LiveBroker(config, db)
        if not broker.ping():
            logger.critical(
                "[BrokerAPI] ⚠️  KiwoomBridge 서버에 연결할 수 없습니다! "
                f"Windows PC에서 KiwoomBridge.py를 실행하고 "
                f"config.yaml > broker > live > bridge_url 을 확인하세요."
            )
        return broker
    else:
        return PaperBroker(config, db)
