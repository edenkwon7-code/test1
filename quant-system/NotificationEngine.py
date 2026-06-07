"""
알림 엔진 (NotificationEngine)
────────────────────────────────
• 이메일 발송: Python 내장 smtplib + email.mime (외부 패키지 불필요)
• FRED API: VIX·CPI·연준금리 등 거시지표 HTTP 조회 (requests)
• 환경변수: SENDER_EMAIL, SENDER_PASSWORD, RECEIVER_EMAIL, FRED_API_KEY
"""

import logging
import os
import smtplib
import socket
from datetime import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Optional

import requests

logger = logging.getLogger(__name__)


# ──────────────────────────────────────────────
# 이메일 발송기
# ──────────────────────────────────────────────

class EmailNotifier:
    """smtplib 기반 Gmail SMTP 발송기"""

    SMTP_HOST = "smtp.gmail.com"
    SMTP_PORT = 587

    def __init__(self):
        self.sender = os.environ.get("SENDER_EMAIL", "")
        self.password = os.environ.get("SENDER_PASSWORD", "")
        self.receiver = os.environ.get("RECEIVER_EMAIL", "")
        self._configured = bool(self.sender and self.password and self.receiver)

        if not self._configured:
            logger.warning(
                "[알림] 이메일 환경변수 미설정 — SENDER_EMAIL / SENDER_PASSWORD / RECEIVER_EMAIL 확인"
            )

    @property
    def is_configured(self) -> bool:
        return self._configured

    def send(
        self,
        subject: str,
        body: str,
        html_body: Optional[str] = None,
        receiver: Optional[str] = None,
    ) -> bool:
        """
        이메일 발송
        Returns True on success, False on failure
        """
        if not self._configured:
            logger.error("[알림] 이메일 미설정 — 발송 건너뜀")
            return False

        to_addr = receiver or self.receiver

        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"] = self.sender
        msg["To"] = to_addr
        msg["X-Priority"] = "1"

        # Plain text 파트
        msg.attach(MIMEText(body, "plain", "utf-8"))

        # HTML 파트 (선택)
        if html_body:
            msg.attach(MIMEText(html_body, "html", "utf-8"))

        try:
            with smtplib.SMTP(self.SMTP_HOST, self.SMTP_PORT, timeout=15) as server:
                server.ehlo()
                server.starttls()
                server.login(self.sender, self.password)
                server.sendmail(self.sender, to_addr, msg.as_string())
            logger.info(f"[알림] 이메일 발송 완료 → {to_addr} | 제목: {subject}")
            return True
        except smtplib.SMTPAuthenticationError:
            logger.error("[알림] Gmail 인증 실패 — 앱 비밀번호 확인 (2단계 인증 필수)")
            return False
        except (smtplib.SMTPException, socket.timeout, OSError) as e:
            logger.error(f"[알림] 이메일 발송 실패: {e}")
            return False


# ──────────────────────────────────────────────
# FRED API 클라이언트
# ──────────────────────────────────────────────

class FredClient:
    """
    FRED REST API 클라이언트
    API Key: FRED_API_KEY 환경변수
    문서: https://fred.stlouisfed.org/docs/api/fred/
    """

    BASE_URL = "https://api.stlouisfed.org/fred/series/observations"

    # 주요 시리즈 ID
    SERIES = {
        "vix": "VIXCLS",          # CBOE VIX (일별)
        "cpi": "CPIAUCSL",        # 소비자물가지수 (월별)
        "fed_rate": "FEDFUNDS",   # 연방기금금리 (월별)
        "treasury_10y": "GS10",   # 10년 국채금리 (월별)
        "unemployment": "UNRATE", # 실업률 (월별)
    }

    def __init__(self):
        self.api_key = os.environ.get("FRED_API_KEY", "")
        self._configured = bool(self.api_key)
        if not self._configured:
            logger.warning("[FRED] FRED_API_KEY 미설정 — VIX는 yfinance로 대체")

    @property
    def is_configured(self) -> bool:
        return self._configured

    def get_latest(self, series_id: str) -> Optional[float]:
        """시리즈 최신 관측값 반환"""
        if not self._configured:
            return None
        try:
            resp = requests.get(
                self.BASE_URL,
                params={
                    "series_id": series_id,
                    "api_key": self.api_key,
                    "file_type": "json",
                    "sort_order": "desc",
                    "limit": 5,
                },
                timeout=10,
            )
            resp.raise_for_status()
            observations = resp.json().get("observations", [])
            for obs in observations:
                val = obs.get("value", ".")
                if val != ".":
                    return float(val)
            return None
        except Exception as e:
            logger.error(f"[FRED] {series_id} 조회 실패: {e}")
            return None

    def get_vix(self) -> Optional[float]:
        return self.get_latest(self.SERIES["vix"])

    def get_macro_snapshot(self) -> dict:
        """주요 거시지표 일괄 조회"""
        snap = {}
        for name, sid in self.SERIES.items():
            snap[name] = self.get_latest(sid)
        return snap


# ──────────────────────────────────────────────
# 통합 알림 관리자
# ──────────────────────────────────────────────

class NotificationManager:
    """
    시스템 전역 알림 관리자
    TradingEngine / ChiefOfStaff 에서 주입받아 사용
    """

    def __init__(self):
        self.email = EmailNotifier()
        self.fred = FredClient()

    # ── 공통 헬퍼 ──────────────────────────────

    def _html_card(self, title: str, rows: list[tuple[str, str]], color: str = "#e53e3e") -> str:
        row_html = "".join(
            f"<tr><td style='padding:6px 12px;color:#718096'>{k}</td>"
            f"<td style='padding:6px 12px;font-weight:bold'>{v}</td></tr>"
            for k, v in rows
        )
        return f"""
        <div style='font-family:sans-serif;max-width:560px;margin:auto;border:1px solid #e2e8f0;border-radius:8px;overflow:hidden'>
          <div style='background:{color};padding:16px 20px;color:white;font-size:18px;font-weight:bold'>{title}</div>
          <table style='width:100%;border-collapse:collapse'>{row_html}</table>
          <div style='background:#f7fafc;padding:10px 20px;font-size:12px;color:#a0aec0'>
            AI 퀀트 운용 시스템 · {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
          </div>
        </div>"""

    # ── 알림 유형별 메서드 ───────────────────────

    def send_system_check(self) -> bool:
        """Step 3 통신 점검 테스트 메일"""
        fred_vix = self.fred.get_vix()
        vix_str = f"{fred_vix:.2f}" if fred_vix else "yfinance 대체"

        subject = "🚨 시스템 통신 점검: 비서실장 API 및 이메일 알림 시스템 정상 작동 중"
        body = (
            subject + "\n\n"
            f"점검 시각: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
            f"FRED VIX: {vix_str}\n"
            "이메일 채널: 정상\n"
            "AI 퀀트 운용 시스템"
        )
        html = self._html_card(
            "✅ 시스템 통신 점검 완료",
            [
                ("점검 시각", datetime.now().strftime("%Y-%m-%d %H:%M:%S")),
                ("FRED VIX", vix_str),
                ("이메일 채널", "정상 ✅"),
                ("FRED API", "정상 ✅" if self.fred.is_configured else "미설정 (yfinance 대체)"),
            ],
            color="#2f855a",
        )
        return self.email.send(subject, body, html)

    def send_kill_switch_alert(
        self, reason: str, positions_closed: int, total_value: float
    ) -> bool:
        """킬스위치 발동 + 전량 청산 완료 알림"""
        subject = "🚨 킬스위치 가동: 전량 청산 완료"
        body = (
            f"{subject}\n\n"
            f"발동 사유: {reason}\n"
            f"청산 포지션 수: {positions_closed}개\n"
            f"포트폴리오 전환 총액: {total_value:,.0f}원\n"
            f"발동 시각: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
            "AI 퀀트 운용 시스템"
        )
        html = self._html_card(
            "🚨 킬스위치 가동: 전량 청산 완료",
            [
                ("발동 사유", reason),
                ("청산 포지션", f"{positions_closed}개"),
                ("현금 전환 총액", f"{total_value:,.0f}원"),
                ("발동 시각", datetime.now().strftime("%Y-%m-%d %H:%M:%S")),
                ("시스템 상태", "🔴 가동 중지"),
            ],
            color="#c53030",
        )
        return self.email.send(subject, body, html)

    def send_circuit_breaker_alert(self, daily_loss_pct: float, reason: str) -> bool:
        """서킷브레이커 발동 알림"""
        subject = f"⚠️ 서킷브레이커 발동: 일일 손실 {daily_loss_pct:.2%}"
        body = (
            f"{subject}\n\n사유: {reason}\n"
            f"시각: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
        )
        html = self._html_card(
            f"⚠️ 서킷브레이커 발동",
            [
                ("일일 손실률", f"{daily_loss_pct:.2%}"),
                ("사유", reason),
                ("시각", datetime.now().strftime("%Y-%m-%d %H:%M:%S")),
                ("상태", "거래 일시 정지"),
            ],
            color="#d69e2e",
        )
        return self.email.send(subject, body, html)

    def send_regime_change(self, old_regime: str, new_regime: str, vix: float) -> bool:
        """레짐 전환 알림"""
        subject = f"📊 레짐 전환: {old_regime} → {new_regime} (VIX={vix:.1f})"
        body = (
            f"{subject}\n\n"
            f"시각: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
        )
        return self.email.send(subject, body)

    def send_trade_alert(
        self, action: str, ticker: str, quantity: float, price: float,
        agent: str, reason: str
    ) -> bool:
        """거래 체결 알림"""
        subject = f"💹 [{action}] {ticker} × {quantity:.2f}주 @ {price:,.2f}"
        body = (
            f"{subject}\n에이전트: {agent}\n사유: {reason}\n"
            f"시각: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
        )
        return self.email.send(subject, body)

    def send_launch_notification(
        self, interval_minutes: int, initial_capital: float
    ) -> bool:
        """🚀 자동매매 가동 시작 알림"""
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        subject = "🚀 AI 퀀트 시스템: 실전 모의투자가 무중단으로 가동을 시작했습니다"
        body = (
            f"{subject}\n\n"
            f"가동 시각   : {now_str}\n"
            f"운용 모드   : 실전 모의투자 (Paper Trading)\n"
            f"초기 자본   : {initial_capital:,.0f}원\n"
            f"매매 주기   : {interval_minutes}분마다 자동 실행\n"
            f"3대 에이전트: 밸류파인더 · 트렌드라이더 · 스윙마스터\n"
            f"리스크 관리 : VIX 서킷브레이커 + MDD -5% + 킬스위치\n\n"
            "대시보드에서 실시간으로 포트폴리오를 모니터링하세요.\n"
            "AI 퀀트 운용 시스템"
        )
        html = self._html_card(
            "🚀 AI 퀀트 시스템 가동 시작",
            [
                ("가동 시각",    now_str),
                ("운용 모드",    "실전 모의투자 (Paper Trading)"),
                ("초기 자본",    f"{initial_capital:,.0f}원"),
                ("매매 주기",    f"{interval_minutes}분마다 자동 실행"),
                ("3대 에이전트", "밸류파인더 · 트렌드라이더 · 스윙마스터"),
                ("리스크 관리",  "VIX 서킷브레이커 + MDD -5% + 킬스위치"),
                ("시스템 상태",  "🟢 정상 가동 중"),
            ],
            color="#2b6cb0",
        )
        return self.email.send(subject, body, html)

    def send_cycle_error_alert(
        self, cycle_count: int, max_retries: int, error_msg: str
    ) -> bool:
        """사이클 반복 실패 경보"""
        subject = f"⚠️ 자동매매 사이클 #{cycle_count} 실패 — {max_retries}회 재시도 초과"
        body = (
            f"{subject}\n\n"
            f"실패 사이클: #{cycle_count}\n"
            f"재시도 횟수: {max_retries}회\n"
            f"오류 내용  : {error_msg[:300]}\n"
            f"발생 시각  : {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n"
            "시스템은 계속 가동 중이며 다음 사이클을 기다립니다."
        )
        html = self._html_card(
            f"⚠️ 사이클 #{cycle_count} 실패",
            [
                ("실패 사이클", f"#{cycle_count}"),
                ("재시도 횟수", f"{max_retries}회"),
                ("오류 내용",   error_msg[:200]),
                ("발생 시각",   datetime.now().strftime("%Y-%m-%d %H:%M:%S")),
                ("시스템 상태", "🟡 다음 사이클 대기 중"),
            ],
            color="#d69e2e",
        )
        return self.email.send(subject, body, html)

    def send_daily_report(
        self,
        db,
        mode: str = "paper",
        regime: str = "—",
        cycle_count: int = 0,
    ) -> bool:
        """
        📊 일일 수익률 리포트 이메일 발송
        장 마감 후 자동 호출됩니다.

        포함 내용:
          - 오늘 날짜 / 현재 레짐
          - 총 운용 자산 / 현금 / 투자 중
          - 초기 자본 대비 누적 수익률
          - 오늘 하루 수익 변동 (전일 대비)
          - 현재 보유 포지션 테이블
          - 오늘 사이클 횟수
        """
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        today   = datetime.now().strftime("%Y-%m-%d")

        try:
            portfolio = db.get_portfolio(mode)
            positions = db.get_positions(mode)
            history   = db.get_performance_history(mode, days=30)
        except Exception as e:
            logger.error(f"[일일리포트] DB 조회 실패: {e}")
            return False

        # ── 오늘 거래 내역 수집 (에이전트 활약 브리핑용) ──────────────
        trades_today: list[dict] = []
        try:
            all_trades = db.get_trades(mode, limit=500)
            trades_today = [
                t for t in all_trades
                if str(t.get("executed_at", "")).startswith(today)
            ]
        except Exception:
            pass

        # ── 에이전트 활약 요약 생성 ────────────────────────────────────
        _agent_summary: dict = {}
        try:
            from TradeTranslator import agent_daily_summary as _ads
            _STOCK_NAMES = {
                "005930": "삼성전자",  "000660": "SK하이닉스", "035420": "NAVER",
                "035720": "카카오",    "051910": "LG화학",     "006400": "삼성SDI",
                "005380": "현대차",    "000270": "기아",       "105560": "KB금융",
                "055550": "신한지주",  "086790": "하나금융",   "032830": "삼성생명",
                "012450": "한화에어로스페이스", "017670": "SK텔레콤",
                "373220": "LG에너지솔루션",
            }
            _agent_summary = _ads(trades_today, _STOCK_NAMES)
        except Exception as _e:
            logger.warning(f"[일일리포트] 에이전트 활약 요약 실패: {_e}")

        total_capital  = portfolio.get("total_capital", 0)
        cash           = portfolio.get("cash", 0)
        invested       = portfolio.get("invested", 0)
        initial_capital = portfolio.get("initial_capital", 100_000_000)

        cumulative_return = (
            (total_capital - initial_capital) / initial_capital * 100
            if initial_capital > 0 else 0.0
        )

        daily_return = 0.0
        if len(history) >= 2:
            try:
                prev_val = history[-2].get("total_capital", total_capital)
                if prev_val > 0:
                    daily_return = (total_capital - prev_val) / prev_val * 100
            except Exception:
                pass

        vix_val = None
        try:
            vix_val = self.fred.get_vix()
        except Exception:
            pass
        vix_str = f"{vix_val:.2f}" if vix_val else "조회 불가"

        daily_sign   = "▲" if daily_return >= 0 else "▼"
        cum_sign     = "▲" if cumulative_return >= 0 else "▼"
        daily_color  = "#2f855a" if daily_return >= 0 else "#c53030"
        cum_color    = "#2f855a" if cumulative_return >= 0 else "#c53030"

        subject = (
            f"📊 [{today}] 일일 리포트 | "
            f"{daily_sign}{abs(daily_return):.2f}% 오늘 | "
            f"{cum_sign}{abs(cumulative_return):.2f}% 누적"
        )

        body = (
            f"AI 퀀트 운용 시스템 — 일일 수익률 리포트\n"
            f"{'='*50}\n"
            f"리포트 기준일  : {today}\n"
            f"발송 시각      : {now_str}\n"
            f"{'='*50}\n"
            f"[운용 현황]\n"
            f"  총 운용 자산 : {total_capital:>15,.0f}원\n"
            f"  현금         : {cash:>15,.0f}원\n"
            f"  투자 중      : {invested:>15,.0f}원\n"
            f"  오늘 수익률  : {daily_sign}{abs(daily_return):.2f}%\n"
            f"  누적 수익률  : {cum_sign}{abs(cumulative_return):.2f}%\n"
            f"  현재 레짐    : {regime}\n"
            f"  VIX          : {vix_str}\n"
            f"  오늘 사이클  : {cycle_count}회\n"
            f"{'='*50}\n"
            f"[보유 포지션 ({len(positions)}개)]\n"
        )
        for pos in positions:
            ticker = pos.get("ticker", "")
            qty    = pos.get("quantity", 0)
            avg    = pos.get("avg_cost", 0)
            agent  = pos.get("agent_name", "")
            body  += f"  • {ticker:<8} {qty:.2f}주 @ {avg:,.2f}원  [{agent}]\n"

        if not positions:
            body += "  현재 보유 포지션 없음 (전량 현금)\n"

        # ── 에이전트 활약 섹션 (plain text) ───────────────────────────
        body += f"\n{'='*50}\n[🤖 에이전트별 오늘 활약상]\n"
        if _agent_summary:
            for agent_key, info in _agent_summary.items():
                pnl = info.get("realized_pnl", 0)
                pnl_str = f" (+{pnl:,.0f}원)" if pnl > 0 else (f" ({pnl:,.0f}원)" if pnl < 0 else "")
                body += f"  {info['label']}({info['strategy']}): {info['headline']}{pnl_str}\n"
                body += f"    → {info['detail']}\n"
        else:
            body += "  오늘 거래 없음 (전 에이전트 관망)\n"

        body += f"{'='*50}\nAI 퀀트 운용 시스템"

        pos_rows_html = ""
        for pos in positions:
            ticker = pos.get("ticker", "")
            qty    = pos.get("quantity", 0)
            avg    = pos.get("avg_cost", 0)
            agent  = pos.get("agent_name", "")
            pos_rows_html += (
                f"<tr style='border-top:1px solid #e2e8f0'>"
                f"<td style='padding:5px 12px'><b>{ticker}</b></td>"
                f"<td style='padding:5px 12px'>{qty:.2f}주</td>"
                f"<td style='padding:5px 12px'>{avg:,.0f}원</td>"
                f"<td style='padding:5px 12px;color:#718096'>{agent}</td>"
                f"</tr>"
            )

        # ── 에이전트 활약 HTML 블록 생성 ─────────────────────────────
        _agent_rows_html = ""
        _agent_icons = {
            "value_finder": "💎", "trend_rider": "🏄", "swing_master": "🏓",
        }
        if _agent_summary:
            for _ak, _ai in _agent_summary.items():
                _icon = _agent_icons.get(_ak, "🤖")
                _pnl  = _ai.get("realized_pnl", 0)
                _pnl_color = "#2f855a" if _pnl >= 0 else "#c53030"
                _pnl_html = (
                    f"<span style='color:{_pnl_color};font-weight:bold'>"
                    f"{'▲' if _pnl >= 0 else '▼'}{abs(_pnl):,.0f}원</span>"
                ) if (_pnl and _pnl != 0) else "<span style='color:#a0aec0'>—</span>"
                _agent_rows_html += (
                    f"<tr style='border-top:1px solid #e2e8f0'>"
                    f"<td style='padding:8px 12px'><b>{_icon} {_ai['label']}</b>"
                    f"<div style='font-size:11px;color:#718096'>{_ai['strategy']}</div></td>"
                    f"<td style='padding:8px 12px;font-size:13px'>{_ai['headline']}</td>"
                    f"<td style='padding:8px 12px;text-align:right'>{_pnl_html}</td>"
                    f"</tr>"
                )
        else:
            _agent_rows_html = (
                "<tr><td colspan='3' style='padding:10px 12px;color:#a0aec0;text-align:center'>"
                "오늘 거래 없음 — 전 에이전트 관망</td></tr>"
            )

        _agent_html_block = f"""
          <div style='background:#2d3748;color:white;padding:10px 16px;font-size:13px;font-weight:bold;margin-top:12px'>
            🤖 에이전트별 오늘 활약상
          </div>
          <table style='width:100%;border-collapse:collapse;border:1px solid #e2e8f0'>
            <tr style='background:#edf2f7'>
              <th style='padding:6px 12px;text-align:left;width:30%'>에이전트</th>
              <th style='padding:6px 12px;text-align:left'>오늘 활약</th>
              <th style='padding:6px 12px;text-align:right;width:20%'>실현 손익</th>
            </tr>
            {_agent_rows_html}
          </table>"""

        html = f"""
        <div style='font-family:sans-serif;max-width:600px;margin:auto'>

          <div style='background:#1a365d;padding:20px;color:white;border-radius:8px 8px 0 0'>
            <div style='font-size:22px;font-weight:bold'>📊 일일 수익률 리포트</div>
            <div style='font-size:14px;opacity:0.8;margin-top:4px'>{today} · AI 퀀트 운용 시스템</div>
          </div>

          <div style='display:flex;gap:0'>
            <div style='flex:1;background:#f0fff4;padding:16px 20px;text-align:center;border-bottom:3px solid {daily_color}'>
              <div style='font-size:13px;color:#718096'>오늘 수익률</div>
              <div style='font-size:28px;font-weight:bold;color:{daily_color}'>{daily_sign}{abs(daily_return):.2f}%</div>
            </div>
            <div style='flex:1;background:#ebf8ff;padding:16px 20px;text-align:center;border-bottom:3px solid {cum_color}'>
              <div style='font-size:13px;color:#718096'>누적 수익률</div>
              <div style='font-size:28px;font-weight:bold;color:{cum_color}'>{cum_sign}{abs(cumulative_return):.2f}%</div>
            </div>
          </div>

          <table style='width:100%;border-collapse:collapse;border:1px solid #e2e8f0'>
            <tr><td style='padding:8px 12px;color:#718096;width:40%'>총 운용 자산</td>
                <td style='padding:8px 12px;font-weight:bold'>{total_capital:,.0f}원</td></tr>
            <tr style='background:#f7fafc'><td style='padding:8px 12px;color:#718096'>현금</td>
                <td style='padding:8px 12px'>{cash:,.0f}원</td></tr>
            <tr><td style='padding:8px 12px;color:#718096'>투자 중</td>
                <td style='padding:8px 12px'>{invested:,.0f}원</td></tr>
            <tr style='background:#f7fafc'><td style='padding:8px 12px;color:#718096'>현재 레짐</td>
                <td style='padding:8px 12px'><b>{regime}</b></td></tr>
            <tr><td style='padding:8px 12px;color:#718096'>VIX</td>
                <td style='padding:8px 12px'>{vix_str}</td></tr>
            <tr style='background:#f7fafc'><td style='padding:8px 12px;color:#718096'>오늘 사이클</td>
                <td style='padding:8px 12px'>{cycle_count}회</td></tr>
          </table>

          <div style='background:#2d3748;color:white;padding:10px 16px;font-size:13px;font-weight:bold'>
            보유 포지션 ({len(positions)}개)
          </div>
          <table style='width:100%;border-collapse:collapse;border:1px solid #e2e8f0'>
            <tr style='background:#edf2f7'>
              <th style='padding:6px 12px;text-align:left'>종목</th>
              <th style='padding:6px 12px;text-align:left'>수량</th>
              <th style='padding:6px 12px;text-align:left'>평균단가</th>
              <th style='padding:6px 12px;text-align:left'>에이전트</th>
            </tr>
            {pos_rows_html if pos_rows_html else
             "<tr><td colspan='4' style='padding:10px 12px;color:#a0aec0;text-align:center'>보유 포지션 없음</td></tr>"}
          </table>

          {_agent_html_block}

          <div style='background:#f7fafc;padding:10px 16px;font-size:12px;color:#a0aec0;border-radius:0 0 8px 8px;border:1px solid #e2e8f0;border-top:none'>
            AI 퀀트 운용 시스템 · {now_str} · 자동 발송
          </div>
        </div>"""

        return self.email.send(subject, body, html)
