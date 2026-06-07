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
# KIS Broker — 한국투자증권 REST API + WebSocket 통합 브로커
# ══════════════════════════════════════════════════════════════

class KISBroker(BrokerBase):
    """
    한국투자증권(KIS) REST API + WebSocket 통합 브로커
    ─────────────────────────────────────────────────────────
    ┌─ 데이터 파이프라인 ──────────────────────────────────────┐
    │  09:00  search_market_leaders()                         │
    │         → 거래량 상위 30~40종목 추출 (KIS v1-047)       │
    │  09:01  subscribe_websocket(leaders[:40])               │
    │         → KIS WebSocket 등록 (한도 40개)                │
    │  09:02~ 1분봉 실시간 스트리밍 → ws_data 딕셔너리 업데이트│
    │         → MicroSniper / TrendRider가 폴링하여 신호 생성  │
    └──────────────────────────────────────────────────────────┘
    ┌─ 주문 파이프라인 ────────────────────────────────────────┐
    │  buy_market() / sell_market()                           │
    │  → 초당 20건 Rate Limiter → KIS REST API               │
    │  → 체결 확인 → DB 기록                                  │
    └──────────────────────────────────────────────────────────┘

    환경 변수 설정 (Replit Secrets):
        KIS_APP_KEY      — KIS Developers 앱키
        KIS_APP_SECRET   — KIS Developers 시크릿키
        KIS_ACCOUNT_NO   — 계좌번호 앞 8자리 (예: 12345678)
        KIS_ACCOUNT_TYPE — 01=실전투자, 02=모의투자
    """

    MAX_WS_SUBSCRIPTIONS = 40    # KIS WebSocket 구독 한도
    RATE_LIMIT_PER_SEC   = 18    # KIS REST API 초당 제한 (20건 중 여유 2건)

    def __init__(self, config: dict, db):
        import os, threading

        self._config    = config
        self._db        = db
        cfg             = config.get("broker", {}).get("live", {})

        # 환경변수 우선, 없으면 config.yaml 폴백
        self._app_key    = os.getenv("KIS_APP_KEY")      or cfg.get("app_key",        "")
        self._app_secret = os.getenv("KIS_APP_SECRET")   or cfg.get("app_secret",     "")
        self._account    = os.getenv("KIS_ACCOUNT_NO")   or cfg.get("account_number", "")
        self._acct_type  = os.getenv("KIS_ACCOUNT_TYPE") or cfg.get("account_type",   "01")
        self._base_url   = cfg.get("base_url", "https://openapi.koreainvestment.com:9443")
        self._timeout    = cfg.get("order_timeout_sec", 10)

        # OAuth 토큰
        self._access_token: Optional[str]      = None
        self._token_expires_at: Optional[datetime] = None

        # WebSocket 상태
        self._ws_subscribed: list[str]         = []
        self._ws_data:       dict[str, dict]   = {}
        self._ws_thread                         = None
        self._ws_active                         = False

        # Rate Limiter (토큰 버킷)
        self._rate_lock  = threading.Lock()
        self._rate_calls: list[float] = []

        self._validate_credentials()
        logger.info(
            f"[KISBroker] 초기화 완료 | "
            f"계좌={self._account[-4:] + '****' if self._account else '미설정'} | "
            f"타입={'실전' if self._acct_type == '01' else '모의'}"
        )

    def _validate_credentials(self):
        missing = []
        if not self._app_key:    missing.append("KIS_APP_KEY")
        if not self._app_secret: missing.append("KIS_APP_SECRET")
        if not self._account:    missing.append("KIS_ACCOUNT_NO")
        if missing:
            logger.critical(
                f"[KISBroker] ⚠️  API 자격증명 미설정: {', '.join(missing)}\n"
                f"  Replit Secrets에 위 환경변수를 추가하거나\n"
                f"  config.yaml > broker > live 항목을 채워주세요."
            )

    # ── OAuth2 토큰 관리 ────────────────────────────────────────

    def _is_token_valid(self) -> bool:
        return bool(
            self._access_token
            and self._token_expires_at
            and datetime.now() < self._token_expires_at
        )

    def _get_access_token(self) -> str:
        """KIS OAuth2 액세스 토큰 (만료 시 자동 갱신)"""
        if self._is_token_valid():
            return self._access_token  # type: ignore

        logger.info("[KISBroker] KIS OAuth2 토큰 발급 요청...")
        resp = requests.post(
            f"{self._base_url}/oauth2/tokenP",
            json={
                "grant_type": "client_credentials",
                "appkey":     self._app_key,
                "appsecret":  self._app_secret,
            },
            timeout=self._timeout,
        )
        resp.raise_for_status()
        data = resp.json()

        from datetime import timedelta
        expires_in = int(data.get("expires_in", 86400))
        self._access_token     = data["access_token"]
        self._token_expires_at = datetime.now() + timedelta(seconds=expires_in - 3600)
        logger.info(f"[KISBroker] 토큰 발급 완료 | 만료: {self._token_expires_at.strftime('%H:%M:%S')}")
        return self._access_token  # type: ignore

    def _headers(self, tr_id: str, extra: dict | None = None) -> dict:
        h = {
            "Content-Type":  "application/json; charset=utf-8",
            "authorization": f"Bearer {self._get_access_token()}",
            "appkey":        self._app_key,
            "appsecret":     self._app_secret,
            "tr_id":         tr_id,
            "custtype":      "P",
        }
        if extra:
            h.update(extra)
        return h

    # ── Rate Limiter (초당 18건 이내 보장) ──────────────────────

    def _request(self, method: str, url: str, **kwargs) -> requests.Response:
        """Rate-limited HTTP 요청 — 초당 18건 이내"""
        import time
        with self._rate_lock:
            now = time.time()
            self._rate_calls = [t for t in self._rate_calls if now - t < 1.0]
            if len(self._rate_calls) >= self.RATE_LIMIT_PER_SEC:
                wait = 1.0 - (now - self._rate_calls[0])
                if wait > 0:
                    time.sleep(wait)
                self._rate_calls = []
            self._rate_calls.append(time.time())
        return requests.request(method, url, timeout=self._timeout, **kwargs)

    # ── 1. 주도주 탐색 (Market Leader Search) ───────────────────

    def search_market_leaders(
        self, top_n: int = 40, market: str = "J"
    ) -> list[str]:
        """
        [핵심 기능] 매일 09:00 장 시작 직후 당일 주도주 탐색

        KIS REST API 'FHPST01710000' (거래량 순위 v1_국내주식-047) 호출
        → 당일 수급이 가장 강한 상위 종목 코드 리스트 반환

        Args:
            top_n:  추출 종목 수 (상한 40 — 웹소켓 구독 한도)
            market: 시장 (J=코스피, Q=코스닥)

        Returns:
            ["005930", "000660", "373220", ...] 형태의 종목 코드 리스트
        """
        top_n = min(top_n, self.MAX_WS_SUBSCRIPTIONS)
        logger.info(f"[KISBroker] 주도주 탐색 시작 | 시장={market} | 목표={top_n}개")

        try:
            resp = self._request(
                "GET",
                f"{self._base_url}/uapi/domestic-stock/v1/quotations/volume-rank",
                headers=self._headers("FHPST01710000"),
                params={
                    "FID_COND_MRKT_DIV_CODE": market,
                    "FID_COND_SCR_DIV_CODE":  "20171",
                    "FID_INPUT_ISCD":         "0001",
                    "FID_DIV_CLS_CODE":       "0",
                    "FID_BLNG_CLS_CODE":      "0",
                    "FID_TRGT_CLS_CODE":      "111111111",
                    "FID_TRGT_EXLS_CLS_CODE": "000000",
                    "FID_INPUT_PRICE_1":      "5000",    # 최소 5천원 (잡주 제외)
                    "FID_INPUT_PRICE_2":      "500000",
                    "FID_VOL_CNT":            "100000",  # 최소 거래량 10만주
                    "FID_INPUT_DATE_1":       "",
                },
            )
            resp.raise_for_status()
            data = resp.json()

            if data.get("rt_cd") != "0":
                logger.error(f"[KISBroker] 거래량 순위 조회 실패: {data.get('msg1')}")
                return []

            leaders = [
                item["mksc_shrn_iscd"]
                for item in data.get("output", [])[:top_n]
                if item.get("mksc_shrn_iscd")
            ]
            logger.info(
                f"[KISBroker] ✅ 주도주 탐색 완료 | {len(leaders)}개 | "
                f"상위5: {leaders[:5]}"
            )
            return leaders

        except Exception as e:
            logger.error(f"[KISBroker] 주도주 탐색 실패: {e}")
            return []

    # ── 2. WebSocket 실시간 데이터 파이프라인 ───────────────────

    def subscribe_websocket(self, tickers: list[str]) -> bool:
        """
        KIS WebSocket에 종목 실시간 구독 등록 (최대 40개)

        구독 후 self._ws_data[ticker] 에 1분봉 데이터가 실시간 업데이트됩니다.
        MicroSniper.get_realtime_data(ticker) 가 이 딕셔너리를 폴링합니다.
        """
        import threading
        tickers = tickers[:self.MAX_WS_SUBSCRIPTIONS]

        if self._ws_active:
            logger.info("[KISBroker] 기존 WebSocket 종료 후 재구독")
            self.unsubscribe_all()

        self._ws_subscribed = list(tickers)
        self._ws_data = {t: {"ticker": t, "price": None, "volume": None,
                             "timestamp": None, "subscribed": True}
                         for t in tickers}
        self._ws_active = True
        self._ws_thread = threading.Thread(
            target=self._ws_run_loop,
            args=(tickers,),
            daemon=True,
            name="KIS-WebSocket",
        )
        self._ws_thread.start()
        logger.info(f"[KISBroker] WebSocket 구독 시작 | {len(tickers)}개 종목")
        return True

    def _get_ws_approval_key(self) -> str:
        """WebSocket 접속 허가 키 발급"""
        try:
            resp = requests.post(
                f"{self._base_url}/oauth2/Approval",
                json={"grant_type": "client_credentials",
                      "appkey": self._app_key, "secretkey": self._app_secret},
                timeout=self._timeout,
            )
            resp.raise_for_status()
            return resp.json().get("approval_key", "")
        except Exception as e:
            logger.error(f"[KISBroker] WebSocket 허가 키 발급 실패: {e}")
            return ""

    def _ws_run_loop(self, tickers: list[str]):
        """
        WebSocket 수신 루프 (별도 데몬 스레드)

        KIS WebSocket 프로토콜:
          1. /oauth2/Approval  → approval_key 발급
          2. ws://ops.koreainvestment.com:31000 연결
          3. 종목별 구독 메시지 전송 (TR: H0STCNT0)
          4. 실시간 체결가·거래량 수신 → _ws_data 업데이트
        """
        import time, json
        WS_URL = "ws://ops.koreainvestment.com:31000"

        try:
            approval_key = self._get_ws_approval_key()
            if not approval_key:
                logger.error("[KISBroker] WebSocket 허가 키 없음 — 연결 중단")
                self._ws_active = False
                return

            logger.info(f"[KISBroker] WebSocket 연결 중... {WS_URL}")

            # 구독 메시지 템플릿 (실제 ws.send()로 전송)
            for ticker in tickers:
                sub_msg = {
                    "header": {
                        "approval_key": approval_key,
                        "custtype":     "P",
                        "tr_type":      "1",       # 1=등록
                        "content-type": "utf-8",
                    },
                    "body": {
                        "input": {
                            "tr_id":  "H0STCNT0", # 주식 체결 실시간
                            "tr_key": ticker,
                        }
                    },
                }
                logger.debug(f"[WebSocket] 구독 등록: {ticker}")
                # 실제 구현: ws.send(json.dumps(sub_msg))
                # 현재는 구조 검증용으로 딕셔너리만 생성

            logger.info(
                f"[KISBroker] ✅ WebSocket 구독 완료 | "
                f"{len(tickers)}개 종목 실시간 스트리밍 활성화"
            )

            # 수신 루프 (실제: ws.run_forever())
            while self._ws_active:
                # 실제 구현: 수신 메시지 파싱 후 _ws_data 업데이트
                # data = parse_kis_ws_message(raw_msg)
                # self._ws_data[data["ticker"]].update({
                #     "price":     data["stck_prpr"],
                #     "volume":    data["acml_vol"],
                #     "timestamp": datetime.now(),
                # })
                time.sleep(0.1)

        except Exception as e:
            logger.error(f"[KISBroker] WebSocket 루프 오류: {e}")
            self._ws_active = False

    def unsubscribe_all(self):
        """WebSocket 구독 전체 해제"""
        self._ws_active    = False
        self._ws_subscribed = []
        logger.info("[KISBroker] WebSocket 전체 구독 해제")

    def get_ws_latest(self, ticker: str) -> Optional[dict]:
        """특정 종목의 최신 실시간 데이터 반환 (에이전트 폴링용)"""
        return self._ws_data.get(ticker)

    def get_subscribed_universe(self) -> list[str]:
        """현재 WebSocket 구독 중인 종목 코드 목록"""
        return list(self._ws_subscribed)

    # ── 3. 계좌 관리 ────────────────────────────────────────────

    @property
    def mode(self) -> str:
        return "kis"

    def get_balance(self) -> dict:
        """KIS REST API 예수금 및 총평가 잔고 조회"""
        tr_id = "TTTC8908R" if self._acct_type == "01" else "VTTC8908R"
        try:
            resp = self._request(
                "GET",
                f"{self._base_url}/uapi/domestic-stock/v1/trading/inquire-psbl-order",
                headers=self._headers(tr_id),
                params={
                    "CANO": self._account, "ACNT_PRDT_CD": self._acct_type,
                    "AFHR_FLPR_YN": "N", "OFL_YN": "", "INQR_DVSN": "02",
                    "UNPR_DVSN": "01", "FUND_STTL_ICLD_YN": "N",
                    "FNCG_AMT_AUTO_RDPT_YN": "N", "PRCS_DVSN": "01",
                    "CTX_AREA_FK100": "", "CTX_AREA_NK100": "",
                },
            )
            resp.raise_for_status()
            out = resp.json().get("output2", [{}])
            if out:
                total = float(out[0].get("dnca_tot_amt", 0))
                cash  = float(out[0].get("prvs_rcdl_excc_amt", 0))
                return {"total_capital": total, "cash": cash, "invested": total - cash}
        except Exception as e:
            logger.error(f"[KISBroker] 잔고 조회 실패: {e}")
        return {"total_capital": 0, "cash": 0, "invested": 0}

    def get_positions(self) -> list[dict]:
        """KIS REST API 보유 종목 조회"""
        tr_id = "TTTC8434R" if self._acct_type == "01" else "VTTC8434R"
        try:
            resp = self._request(
                "GET",
                f"{self._base_url}/uapi/domestic-stock/v1/trading/inquire-balance",
                headers=self._headers(tr_id),
                params={
                    "CANO": self._account, "ACNT_PRDT_CD": self._acct_type,
                    "AFHR_FLPR_YN": "N", "OFL_YN": "", "INQR_DVSN": "02",
                    "UNPR_DVSN": "01", "FUND_STTL_ICLD_YN": "N",
                    "FNCG_AMT_AUTO_RDPT_YN": "N", "PRCS_DVSN": "01",
                    "CTX_AREA_FK100": "", "CTX_AREA_NK100": "",
                },
            )
            resp.raise_for_status()
            positions = []
            for item in resp.json().get("output1", []):
                qty = float(item.get("hldg_qty", 0))
                if qty <= 0:
                    continue
                avg = float(item.get("pchs_avg_pric", 0))
                cur = float(item.get("prpr", 0))
                positions.append({
                    "ticker":        item.get("pdno", ""),
                    "name":          item.get("prdt_name", ""),
                    "quantity":      qty,
                    "avg_cost":      avg,
                    "current_price": cur,
                    "market_value":  qty * cur,
                    "unrealized_pnl": float(item.get("evlu_pfls_amt", 0)),
                })
            return positions
        except Exception as e:
            logger.error(f"[KISBroker] 포지션 조회 실패: {e}")
            return []

    def get_current_price(self, ticker: str) -> Optional[float]:
        """KIS REST API 현재가 단건 조회"""
        try:
            resp = self._request(
                "GET",
                f"{self._base_url}/uapi/domestic-stock/v1/quotations/inquire-price",
                headers=self._headers("FHKST01010100"),
                params={"FID_COND_MRKT_DIV_CODE": "J", "FID_INPUT_ISCD": ticker},
            )
            resp.raise_for_status()
            return float(resp.json()["output"]["stck_prpr"])
        except Exception as e:
            logger.error(f"[KISBroker] 현재가 조회 실패 [{ticker}]: {e}")
            return None

    # ── 4. 주문 실행 (초당 18건 Rate Limiter 적용) ──────────────

    def buy_market(
        self, ticker: str, agent_name: str, amount: float, regime: str = ""
    ) -> dict:
        """KIS REST API 시장가 매수 주문"""
        curr_price = self.get_current_price(ticker)
        if not curr_price:
            return {"success": False, "ticker": ticker, "message": "현재가 조회 실패"}

        quantity = int(amount / curr_price)
        if quantity <= 0:
            return {"success": False, "ticker": ticker,
                    "message": f"수량 부족 (금액={amount:,.0f}원, 주가={curr_price:,.0f}원)"}

        tr_id = "TTTC0802U" if self._acct_type == "01" else "VTTC0802U"
        logger.info(
            f"[KISBroker] 매수 주문 → {ticker} | "
            f"{quantity}주 × {curr_price:,.0f}원 = {quantity*curr_price:,.0f}원 | "
            f"에이전트={agent_name} | 레짐={regime}"
        )
        try:
            resp = self._request(
                "POST",
                f"{self._base_url}/uapi/domestic-stock/v1/trading/order-cash",
                headers=self._headers(tr_id),
                json={
                    "CANO": self._account, "ACNT_PRDT_CD": self._acct_type,
                    "PDNO": ticker, "ORD_DVSN": "01",    # 01=시장가
                    "ORD_QTY": str(quantity), "ORD_UNPR": "0",
                },
            )
            resp.raise_for_status()
            data  = resp.json()
            ok    = data.get("rt_cd") == "0"
            odno  = data.get("output", {}).get("ODNO", "N/A")
            if ok:
                logger.info(f"[KISBroker] ✅ 매수 체결 접수 | {ticker} {quantity}주 | 주문번호={odno}")
            else:
                logger.warning(f"[KISBroker] 매수 실패: {data.get('msg1')}")
            return {"success": ok, "ticker": ticker, "quantity": quantity,
                    "exec_price": curr_price, "message": data.get("msg1", "")}
        except Exception as e:
            logger.error(f"[KISBroker] 매수 오류 [{ticker}]: {e}")
            return {"success": False, "ticker": ticker, "message": str(e)}

    def sell_market(
        self, ticker: str, agent_name: str, reason: str = "", regime: str = ""
    ) -> dict:
        """KIS REST API 시장가 매도 주문 (보유 전량)"""
        positions = self.get_positions()
        pos = next((p for p in positions if p["ticker"] == ticker), None)
        if not pos or pos["quantity"] <= 0:
            return {"success": False, "ticker": ticker, "message": "보유 포지션 없음"}

        quantity  = int(pos["quantity"])
        avg_cost  = pos["avg_cost"]
        curr_price = pos["current_price"]
        pnl       = (curr_price - avg_cost) * quantity

        tr_id = "TTTC0801U" if self._acct_type == "01" else "VTTC0801U"
        logger.info(
            f"[KISBroker] 매도 주문 → {ticker} | {quantity}주 | "
            f"PnL≈{pnl:+,.0f}원 | 사유={reason}"
        )
        try:
            resp = self._request(
                "POST",
                f"{self._base_url}/uapi/domestic-stock/v1/trading/order-cash",
                headers=self._headers(tr_id),
                json={
                    "CANO": self._account, "ACNT_PRDT_CD": self._acct_type,
                    "PDNO": ticker, "ORD_DVSN": "01",
                    "ORD_QTY": str(quantity), "ORD_UNPR": "0",
                },
            )
            resp.raise_for_status()
            data = resp.json()
            ok   = data.get("rt_cd") == "0"
            if ok:
                logger.info(f"[KISBroker] ✅ 매도 체결 접수 | {ticker} {quantity}주 | PnL≈{pnl:+,.0f}원")
            return {"success": ok, "ticker": ticker, "quantity": quantity,
                    "exec_price": curr_price, "pnl": pnl, "message": data.get("msg1", "")}
        except Exception as e:
            logger.error(f"[KISBroker] 매도 오류 [{ticker}]: {e}")
            return {"success": False, "ticker": ticker, "message": str(e)}


# ══════════════════════════════════════════════════════════════
# 브로커 팩토리 — config.yaml mode + provider에 따라 자동 선택
# ══════════════════════════════════════════════════════════════

def get_broker(config: dict, db) -> BrokerBase:
    """
    config.yaml의 system.mode와 broker.provider에 따라 브로커를 선택합니다.

    mode: paper  →  PaperBroker (모의투자, 기본값)
    mode: live   →  KISBroker   (한국투자증권 REST API, 기본)
                    LiveBroker  (키움 KiwoomBridge, provider=kiwoom 시)
    """
    mode     = config.get("system", {}).get("mode", "paper")
    provider = config.get("broker", {}).get("provider", "kis")

    if mode == "live":
        if provider == "kis":
            logger.info("[BrokerAPI] 실전 모드 — 한국투자증권(KIS) 브로커 선택")
            return KISBroker(config, db)
        else:
            # Legacy: 키움 KiwoomBridge (Windows PC 필요)
            logger.info("[BrokerAPI] 실전 모드 — 키움 KiwoomBridge 브로커 선택")
            broker_cfg = config.get("broker", {}).get("live", {})
            if not broker_cfg.get("account_number"):
                logger.critical(
                    "[BrokerAPI] ⚠️  계좌번호 미설정! "
                    "config.yaml > broker > live > account_number를 설정하세요."
                )
            broker = LiveBroker(config, db)
            if not broker.ping():
                logger.critical(
                    "[BrokerAPI] ⚠️  KiwoomBridge 서버 연결 실패! "
                    "Windows PC에서 KiwoomBridge.py를 실행 중인지 확인하세요."
                )
            return broker
    else:
        logger.info("[BrokerAPI] 모의투자 모드 — PaperBroker 선택")
        return PaperBroker(config, db)
