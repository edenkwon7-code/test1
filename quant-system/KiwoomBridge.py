"""
KiwoomBridge.py — 키움증권 OpenAPI 브릿지 서버
════════════════════════════════════════════════════════════
⚠️  이 파일은 사용자의 Windows PC에서 실행해야 합니다.
    키움 OpenAPI는 Windows + 32bit Python 환경에서만 동작합니다.

사전 준비 (Windows PC):
  1. 키움증권 계좌 개설 + HTS(영웅문) 설치 및 로그인
  2. 키움 OpenAPI+ 설치: https://www1.kiwoom.com/nkw.templateFrameSet.do?m=m1408000000
  3. 32bit Python 3.11 설치 (64bit 안됨!)
  4. 패키지 설치:
       pip install pywin32 flask requests
  5. 이 파일을 PC에 복사 후 실행:
       python KiwoomBridge.py --secret YOUR_SECRET --port 7777

config.yaml 설정:
  broker:
    live:
      bridge_url: "http://YOUR_PC_PUBLIC_IP:7777"  ← 공인 IP 또는 내부 IP
      bridge_secret: "YOUR_SECRET"
      account_number: "1234567890"

엔드포인트:
  GET  /ping            — 서버 생존 확인
  GET  /balance         — 실계좌 잔고 조회
  GET  /positions       — 보유 포지션 조회
  GET  /price           — 종목 현재가 조회
  POST /buy             — 시장가 매수 주문
  POST /sell            — 시장가 매도 주문 (전량)
"""

# ──────────────────────────────────────────────────────────────
# ⚠️  아래 코드는 Windows + 키움 OpenAPI 환경에서만 실제 동작합니다.
# ──────────────────────────────────────────────────────────────

import argparse
import logging
import sys
import threading
import time
from datetime import datetime
from functools import wraps

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler("kiwoom_bridge.log", encoding="utf-8"),
    ],
)
logger = logging.getLogger("KiwoomBridge")


# ══════════════════════════════════════════════════════════════
# Flask 앱
# ══════════════════════════════════════════════════════════════

try:
    from flask import Flask, request, jsonify
    app = Flask(__name__)
except ImportError:
    logger.critical("Flask 미설치. pip install flask 실행 후 다시 시작하세요.")
    sys.exit(1)


# ══════════════════════════════════════════════════════════════
# 설정
# ══════════════════════════════════════════════════════════════

BRIDGE_SECRET = ""   # --secret 인자로 주입
_kiwoom = None       # KiwoomAPI 싱글턴


# ══════════════════════════════════════════════════════════════
# 키움 OpenAPI 래퍼 (Windows COM 기반)
# ══════════════════════════════════════════════════════════════

class KiwoomAPI:
    """
    키움 OpenAPI+ COM 래퍼
    PyQt5 이벤트 루프가 반드시 필요합니다.
    """

    ORDER_TYPE_BUY  = 1   # 신규 매수
    ORDER_TYPE_SELL = 2   # 신규 매도
    ORDER_MARKET    = "03"  # 시장가

    def __init__(self):
        self._ready = threading.Event()
        self._ocx = None
        self._login_result = None
        self._tr_data = {}
        self._order_result = {}
        self._lock = threading.Lock()

    def connect(self) -> bool:
        """키움 로그인 (이미 HTS가 로그인된 상태여야 합니다)"""
        try:
            from PyQt5.QAxContainer import QAxWidget
            from PyQt5.QtWidgets import QApplication

            app = QApplication.instance() or QApplication(sys.argv)
            self._ocx = QAxWidget("KHOPENAPI.KHOpenAPICtrl.1")

            self._ocx.OnEventConnect.connect(self._on_login)
            self._ocx.OnReceiveTrData.connect(self._on_tr_data)
            self._ocx.OnReceiveMsg.connect(self._on_msg)
            self._ocx.OnReceiveChejanData.connect(self._on_chejan)

            self._ocx.dynamicCall("CommConnect()")
            logger.info("[Kiwoom] 로그인 요청 완료 — HTS 창에서 승인하세요")

            # 로그인 완료까지 대기 (최대 60초)
            if not self._ready.wait(timeout=60):
                logger.error("[Kiwoom] 로그인 타임아웃")
                return False

            return self._login_result == 0
        except ImportError:
            logger.critical(
                "[Kiwoom] PyQt5 또는 pywin32 미설치.\n"
                "  pip install PyQt5 pywin32 을 실행하세요."
            )
            return False

    def _on_login(self, err_code: int):
        self._login_result = err_code
        if err_code == 0:
            logger.info("[Kiwoom] ✅ 로그인 성공")
        else:
            logger.error(f"[Kiwoom] ❌ 로그인 실패 (에러코드: {err_code})")
        self._ready.set()

    def _on_msg(self, screen, rqname, trcode, msg):
        logger.info(f"[Kiwoom] 메시지: {msg}")

    def _on_tr_data(self, screen, rqname, trcode, record, prev_next, *args):
        with self._lock:
            self._tr_data[rqname] = {
                "trcode": trcode,
                "prev_next": prev_next,
                "data": {},
            }
            event = self._tr_data.get(f"_event_{rqname}")
            if event:
                event.set()

    def _on_chejan(self, gubun, item_cnt, fid_list):
        if gubun == "0":  # 주문 접수/체결
            order_no = self._ocx.dynamicCall("GetChejanData(int)", 9203)
            ticker   = self._ocx.dynamicCall("GetChejanData(int)", 9001).strip().lstrip("A")
            qty      = self._ocx.dynamicCall("GetChejanData(int)", 900)
            price    = self._ocx.dynamicCall("GetChejanData(int)", 910)
            status   = self._ocx.dynamicCall("GetChejanData(int)", 913).strip()
            logger.info(
                f"[Kiwoom] 체결통보 | 주문={order_no} | {ticker} "
                f"| {qty}주 @ {price}원 | 상태={status}"
            )
            with self._lock:
                self._order_result[order_no] = {
                    "ticker": ticker,
                    "quantity": abs(int(qty or 0)),
                    "exec_price": abs(int(price or 0)),
                    "status": status,
                }

    def get_account_balance(self, account: str) -> dict:
        """
        opw00018 — 계좌평가잔고내역 조회
        """
        event = threading.Event()
        rqname = "계좌평가잔고내역요청"
        with self._lock:
            self._tr_data[f"_event_{rqname}"] = event

        self._ocx.dynamicCall("SetInputValue(QString, QString)", "계좌번호", account)
        self._ocx.dynamicCall("SetInputValue(QString, QString)", "비밀번호", "")
        self._ocx.dynamicCall("SetInputValue(QString, QString)", "비밀번호입력매체구분", "00")
        self._ocx.dynamicCall("SetInputValue(QString, QString)", "조회구분", "2")
        self._ocx.dynamicCall(
            "CommRqData(QString, QString, int, QString)",
            rqname, "opw00018", 0, "0101"
        )

        event.wait(timeout=10)

        def _get(field):
            val = self._ocx.dynamicCall(
                "GetCommData(QString, QString, int, QString)",
                "opw00018", rqname, 0, field
            ).strip()
            try:
                return abs(int(val))
            except Exception:
                return 0

        total_purchase = _get("총매입금액")
        eval_amount    = _get("총평가금액")
        profit_loss    = _get("총평가손익금액")
        cash           = _get("추정예탁자산")

        return {
            "total_capital": eval_amount + cash,
            "cash":          cash,
            "invested":      eval_amount,
            "total_purchase": total_purchase,
            "profit_loss":   profit_loss,
        }

    def get_positions(self, account: str) -> list[dict]:
        """보유 종목 목록 조회"""
        event = threading.Event()
        rqname = "계좌평가잔고내역요청"
        with self._lock:
            self._tr_data[f"_event_{rqname}"] = event

        self._ocx.dynamicCall("SetInputValue(QString, QString)", "계좌번호", account)
        self._ocx.dynamicCall("SetInputValue(QString, QString)", "비밀번호", "")
        self._ocx.dynamicCall("SetInputValue(QString, QString)", "비밀번호입력매체구분", "00")
        self._ocx.dynamicCall("SetInputValue(QString, QString)", "조회구분", "2")
        self._ocx.dynamicCall(
            "CommRqData(QString, QString, int, QString)",
            rqname, "opw00018", 0, "0101"
        )
        event.wait(timeout=10)

        cnt = self._ocx.dynamicCall(
            "GetRepeatCnt(QString, QString)", "opw00018", rqname
        )
        positions = []
        for i in range(cnt):
            def _get_row(field, idx=i):
                val = self._ocx.dynamicCall(
                    "GetCommData(QString, QString, int, QString)",
                    "opw00018", rqname, idx, field
                ).strip()
                return val

            ticker       = _get_row("종목번호").lstrip("A")
            name         = _get_row("종목명")
            quantity     = abs(int(_get_row("보유수량") or 0))
            avg_cost     = abs(int(_get_row("매입단가") or 0))
            curr_price   = abs(int(_get_row("현재가") or 0))
            market_value = abs(int(_get_row("평가금액") or 0))
            pnl          = int(_get_row("평가손익") or 0)

            if ticker and quantity > 0:
                positions.append({
                    "ticker":         ticker,
                    "name":           name,
                    "quantity":       quantity,
                    "avg_cost":       avg_cost,
                    "current_price":  curr_price,
                    "market_value":   market_value,
                    "unrealized_pnl": pnl,
                    "agent_name":     "live",
                })
        return positions

    def get_current_price(self, ticker: str) -> int:
        """opt10001 — 주식기본정보 현재가 조회"""
        event = threading.Event()
        rqname = "주식기본정보요청"
        with self._lock:
            self._tr_data[f"_event_{rqname}"] = event

        self._ocx.dynamicCall("SetInputValue(QString, QString)", "종목코드", ticker)
        self._ocx.dynamicCall(
            "CommRqData(QString, QString, int, QString)",
            rqname, "opt10001", 0, "0102"
        )
        event.wait(timeout=10)
        val = self._ocx.dynamicCall(
            "GetCommData(QString, QString, int, QString)",
            "opt10001", rqname, 0, "현재가"
        ).strip()
        try:
            return abs(int(val))
        except Exception:
            return 0

    def send_market_order(
        self,
        account: str,
        ticker: str,
        order_type: int,
        quantity: int,
    ) -> str:
        """
        시장가 주문 발송
        order_type: 1=매수, 2=매도
        Returns: 주문번호 (str)
        """
        ret = self._ocx.dynamicCall(
            "SendOrder(QString, QString, QString, int, QString, int, int, QString, QString)",
            ["주문", "0101", account, order_type, ticker, quantity, 0,
             self.ORDER_MARKET, ""]
        )
        if ret == 0:
            logger.info(
                f"[Kiwoom] 주문 접수 완료 | {'매수' if order_type == 1 else '매도'} "
                f"| {ticker} | {quantity}주"
            )
            return "OK"
        else:
            logger.error(f"[Kiwoom] 주문 실패 (err={ret})")
            return ""


# ══════════════════════════════════════════════════════════════
# 보안 데코레이터
# ══════════════════════════════════════════════════════════════

def require_secret(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if BRIDGE_SECRET:
            token = request.headers.get("X-Bridge-Secret", "")
            if token != BRIDGE_SECRET:
                logger.warning(
                    f"[Bridge] ⛔ 인증 실패 — IP: {request.remote_addr}"
                )
                return jsonify({"error": "Unauthorized"}), 401
        return f(*args, **kwargs)
    return decorated


# ══════════════════════════════════════════════════════════════
# Flask 라우트
# ══════════════════════════════════════════════════════════════

@app.route("/ping", methods=["GET"])
def ping():
    return jsonify({
        "status": "ok",
        "kiwoom_connected": _kiwoom is not None,
        "timestamp": datetime.now().isoformat(),
    })


@app.route("/balance", methods=["GET"])
@require_secret
def balance():
    account = request.args.get("account", "")
    if not _kiwoom:
        return jsonify({"error": "키움 API 미연결"}), 503
    try:
        data = _kiwoom.get_account_balance(account)
        return jsonify(data)
    except Exception as e:
        logger.error(f"[/balance] 오류: {e}")
        return jsonify({"error": str(e)}), 500


@app.route("/positions", methods=["GET"])
@require_secret
def positions():
    account = request.args.get("account", "")
    if not _kiwoom:
        return jsonify({"error": "키움 API 미연결"}), 503
    try:
        pos = _kiwoom.get_positions(account)
        return jsonify({"positions": pos})
    except Exception as e:
        logger.error(f"[/positions] 오류: {e}")
        return jsonify({"error": str(e)}), 500


@app.route("/price", methods=["GET"])
@require_secret
def price():
    ticker = request.args.get("ticker", "")
    if not _kiwoom:
        return jsonify({"error": "키움 API 미연결"}), 503
    try:
        p = _kiwoom.get_current_price(ticker)
        return jsonify({"ticker": ticker, "price": p})
    except Exception as e:
        logger.error(f"[/price] 오류: {e}")
        return jsonify({"error": str(e)}), 500


@app.route("/buy", methods=["POST"])
@require_secret
def buy():
    data = request.get_json()
    account    = data.get("account", "")
    ticker     = data.get("ticker", "")
    amount     = float(data.get("amount", 0))
    agent_name = data.get("agent_name", "")

    if not _kiwoom:
        return jsonify({"success": False, "message": "키움 API 미연결"}), 503
    if not ticker or amount <= 0:
        return jsonify({"success": False, "message": "종목코드 또는 금액 오류"}), 400

    try:
        curr_price = _kiwoom.get_current_price(ticker)
        if not curr_price:
            return jsonify({"success": False, "message": f"현재가 조회 실패: {ticker}"}), 400

        quantity = int(amount // curr_price)
        if quantity < 1:
            return jsonify({
                "success": False,
                "message": f"매수 금액({amount:,.0f}원)이 현재가({curr_price:,.0f}원)보다 작음",
            }), 400

        logger.info(
            f"[/buy] {ticker} | 금액={amount:,.0f}원 | 현재가={curr_price:,.0f}원 "
            f"| 수량={quantity}주 | 에이전트={agent_name}"
        )
        ret = _kiwoom.send_market_order(account, ticker, KiwoomAPI.ORDER_TYPE_BUY, quantity)

        if ret:
            # 체결 대기 (최대 5초)
            time.sleep(5)
            return jsonify({
                "success":    True,
                "ticker":     ticker,
                "quantity":   quantity,
                "exec_price": curr_price,
                "amount":     curr_price * quantity,
                "agent_name": agent_name,
                "message":    "시장가 매수 주문 접수 완료",
            })
        else:
            return jsonify({"success": False, "message": "키움 주문 접수 실패"}), 500

    except Exception as e:
        logger.error(f"[/buy] 오류: {e}")
        return jsonify({"success": False, "message": str(e)}), 500


@app.route("/sell", methods=["POST"])
@require_secret
def sell():
    data    = request.get_json()
    account = data.get("account", "")
    ticker  = data.get("ticker", "")
    reason  = data.get("reason", "")

    if not _kiwoom:
        return jsonify({"success": False, "message": "키움 API 미연결"}), 503

    try:
        positions = _kiwoom.get_positions(account)
        pos = next((p for p in positions if p["ticker"] == ticker), None)

        if not pos or pos["quantity"] <= 0:
            return jsonify({
                "success": False,
                "message": f"보유 포지션 없음: {ticker}",
            }), 400

        quantity  = pos["quantity"]
        avg_cost  = pos["avg_cost"]
        curr_price = _kiwoom.get_current_price(ticker) or avg_cost
        pnl = (curr_price - avg_cost) * quantity

        logger.info(
            f"[/sell] {ticker} | {quantity}주 | 현재가={curr_price:,.0f}원 "
            f"| PnL={pnl:+,.0f}원 | 사유={reason}"
        )
        ret = _kiwoom.send_market_order(account, ticker, KiwoomAPI.ORDER_TYPE_SELL, quantity)

        if ret:
            time.sleep(5)
            return jsonify({
                "success":    True,
                "ticker":     ticker,
                "quantity":   quantity,
                "exec_price": curr_price,
                "pnl":        pnl,
                "message":    "시장가 매도 주문 접수 완료",
            })
        else:
            return jsonify({"success": False, "message": "키움 주문 접수 실패"}), 500

    except Exception as e:
        logger.error(f"[/sell] 오류: {e}")
        return jsonify({"success": False, "message": str(e)}), 500


# ══════════════════════════════════════════════════════════════
# 메인 진입점
# ══════════════════════════════════════════════════════════════

def _run_qt_loop():
    """PyQt5 이벤트 루프는 메인 스레드에서 실행해야 함"""
    try:
        from PyQt5.QtWidgets import QApplication
        qt_app = QApplication.instance() or QApplication(sys.argv)
        qt_app.exec_()
    except ImportError:
        pass


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="KiwoomBridge 서버")
    parser.add_argument("--secret", default="", help="보안 키 (빈값이면 인증 없음)")
    parser.add_argument("--port",   default=7777, type=int, help="브릿지 서버 포트")
    parser.add_argument("--host",   default="0.0.0.0", help="바인드 주소")
    parser.add_argument("--no-kiwoom", action="store_true",
                        help="키움 연결 없이 테스트 모드로 실행 (개발용)")
    args = parser.parse_args()

    BRIDGE_SECRET = args.secret

    if not args.no_kiwoom:
        logger.info("=" * 55)
        logger.info("  AI 퀀트 운용 시스템 — KiwoomBridge 서버 시작")
        logger.info("=" * 55)
        logger.info(f"  포트      : {args.port}")
        logger.info(f"  보안 키   : {'설정됨' if BRIDGE_SECRET else '미설정 (비추천)'}")
        logger.info("  키움 OpenAPI 연결 중...")
        logger.info("=" * 55)

        _kiwoom = KiwoomAPI()
        if not _kiwoom.connect():
            logger.critical("키움 OpenAPI 연결 실패 — HTS 로그인 상태를 확인하세요.")
            sys.exit(1)
        logger.info("✅ 키움 OpenAPI 연결 완료 — 주문 수신 대기 중")
    else:
        logger.warning("⚠️  --no-kiwoom 모드: 키움 연결 없이 실행 (테스트 전용)")

    app.run(host=args.host, port=args.port, debug=False, threaded=True)
