"""
live_trader.py — 장 시간 인식형 자동매매 스케줄러
─────────────────────────────────────────────────
타임라인 (KST 기준):
  • 장 외 / 주말  → 다음 개장(09:00)까지 효율적 슬립 (30분 단위 킬스위치 확인)
  • 09:05 (하루 1회) → 전체 사이클: 비서실장 + 3대 에이전트 신호 생성 + 포지션 관리
  • 장 중 매시간  → 모니터링 사이클: 비서실장 레짐 감시 + 스탑로스/익절 체크
  • 15:30 직후   → 일일 리포트 이메일 발송 → 익일 개장까지 슬립
"""

import json
import logging
import os
import sys
import time
from datetime import datetime, date, timedelta, time as dtime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from config_loader import load_config
from database import QuantDatabase
from NotificationEngine import NotificationManager
from TradingEngine import TradingEngine

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("LiveTrader")

STATUS_FILE = Path(__file__).parent / ".trader_status.json"

KST_OFFSET   = timedelta(hours=9)
MARKET_OPEN  = dtime(9,  0)    # KST 개장
FULL_CYCLE_T = dtime(9,  5)    # 전체 사이클 실행 시각 (에이전트 신호 생성)
MARKET_CLOSE = dtime(15, 30)   # KST 장 마감
REPORT_START = dtime(15, 32)   # 일일 리포트 발송 시작
REPORT_END   = dtime(16,  0)   # 일일 리포트 발송 마감


# ── KST 시간 유틸 ──────────────────────────────────────────

def kst_now() -> datetime:
    return datetime.utcnow() + KST_OFFSET


def is_weekday(dt: datetime) -> bool:
    return dt.weekday() < 5  # 0=월 … 4=금


def is_market_hours(dt: datetime) -> bool:
    return is_weekday(dt) and MARKET_OPEN <= dt.time() <= MARKET_CLOSE


def next_market_open(from_dt: datetime) -> datetime:
    """from_dt 이후 첫 번째 평일 KST 09:00 반환"""
    candidate = from_dt.replace(hour=9, minute=0, second=0, microsecond=0)
    if from_dt.time() >= MARKET_OPEN:
        candidate += timedelta(days=1)
    while not is_weekday(candidate):
        candidate += timedelta(days=1)
    return candidate


def secs_until(target: datetime) -> float:
    return max(0.0, (target - kst_now()).total_seconds())


# ── 상태 파일 ───────────────────────────────────────────────

def write_status(
    running: bool,
    started_at: str = "",
    last_cycle_at: str = "",
    next_cycle_at: str = "",
    cycle_count: int = 0,
    monitor_count: int = 0,
    last_regime: str = "—",
    last_error: str = "",
):
    STATUS_FILE.write_text(
        json.dumps(
            {
                "running":        running,
                "pid":            os.getpid(),
                "started_at":     started_at,
                "last_cycle_at":  last_cycle_at,
                "next_cycle_at":  next_cycle_at,
                "cycle_count":    cycle_count,
                "monitor_count":  monitor_count,
                "last_regime":    last_regime,
                "last_error":     last_error,
                "updated_at":     kst_now().isoformat(),
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )


def read_status() -> dict:
    try:
        return json.loads(STATUS_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {"running": False}


# ── 청크 슬립 (킬스위치 감시) ──────────────────────────────

def sleep_chunked(seconds: float, db: QuantDatabase, chunk: int = 1800) -> bool:
    """seconds 동안 슬립. chunk 초마다 킬스위치 확인. 활성 시 False 반환."""
    end = time.time() + seconds
    while time.time() < end:
        remaining = end - time.time()
        time.sleep(min(remaining, chunk))
        if db.get_kill_switch().get("emergency_stop"):
            logger.critical("[LiveTrader] 슬립 중 킬스위치 감지")
            return False
    return True


# ── 일일 리포트 발송 판단 ─────────────────────────────────

def should_send_report(config: dict, last_report_date: date) -> bool:
    notif_cfg = config.get("notifications", {}).get("daily_report", {})
    if not notif_cfg.get("enabled", True):
        return False
    if last_report_date == date.today():
        return False
    t = kst_now().time()
    return REPORT_START <= t <= REPORT_END


# ── 메인 루프 ──────────────────────────────────────────────

def run():
    logger.info("=" * 62)
    logger.info("🚀 AI 퀀트 자동매매 — 장 시간 인식 모드 가동 (KST)")
    logger.info(f"   장 시간   : {MARKET_OPEN.strftime('%H:%M')} ~ {MARKET_CLOSE.strftime('%H:%M')} KST (평일)")
    logger.info(f"   전체 사이클: 매일 {FULL_CYCLE_T.strftime('%H:%M')} KST — 에이전트 신호 생성")
    logger.info(f"   모니터링   : 장 중 매시간 — 비서실장 레짐 감시 + 스탑로스 체크")
    logger.info("=" * 62)

    config       = load_config()
    lt_cfg       = config.get("live_trading", {})
    monitor_intv = lt_cfg.get("interval_minutes", 60)   # 모니터링 간격(분)
    max_retry    = lt_cfg.get("max_retries", 3)

    db       = QuantDatabase(config["system"]["db_path"])
    engine   = TradingEngine(config)
    notifier = NotificationManager()

    started_at       = kst_now().isoformat()
    cycle_count      = 0        # 전체 사이클 횟수
    monitor_count    = 0        # 모니터링 횟수
    last_regime      = "—"
    last_report_date = date.min
    last_full_date   = date.min  # 오늘 전체 사이클 완료 여부

    write_status(
        running=True, started_at=started_at,
        last_regime="가동 직후 — 개장 대기 중",
        cycle_count=0, monitor_count=0,
    )

    logger.info("📧 가동 알림 이메일 발송 중...")
    notifier.send_launch_notification(
        interval_minutes=monitor_intv,
        initial_capital=config["paper_trading"]["initial_capital"],
    )
    db.log_system_event(
        "INFO", "LiveTrader",
        f"자동매매 가동 | 모니터링={monitor_intv}분 | 전체사이클=09:05 KST"
    )

    try:
        while True:
            now_kst = kst_now()

            # ── 킬스위치 확인 ──────────────────────────────
            if db.get_kill_switch().get("emergency_stop"):
                logger.critical("[LiveTrader] 킬스위치 활성 — 루프 중단")
                db.log_system_event("CRITICAL", "LiveTrader", "킬스위치 감지 — 루프 중단")
                break

            # ── 장 외 시간 · 주말: 다음 개장까지 슬립 ──────
            if not is_market_hours(now_kst):
                nxt = next_market_open(now_kst)
                wait_h = secs_until(nxt) / 3600
                day_name = ["월", "화", "수", "목", "금", "토", "일"][now_kst.weekday()]
                logger.info(
                    f"[LiveTrader] 장 외 ({day_name} {now_kst.strftime('%H:%M')} KST) "
                    f"— 다음 개장({nxt.strftime('%m/%d %H:%M')})까지 {wait_h:.1f}h 슬립"
                )
                write_status(
                    running=True, started_at=started_at,
                    next_cycle_at=nxt.isoformat(),
                    cycle_count=cycle_count, monitor_count=monitor_count,
                    last_regime=last_regime,
                )
                ok = sleep_chunked(secs_until(nxt), db)
                if not ok:
                    break
                continue

            # ── 장 중 ────────────────────────────────────────

            # ① 전체 사이클: 하루 1회, 09:05 이후 첫 번째 루프
            if last_full_date < now_kst.date() and now_kst.time() >= FULL_CYCLE_T:
                cycle_count += 1
                logger.info(f"\n{'='*56}")
                logger.info(
                    f"[LiveTrader] ▶ 전체 사이클 #{cycle_count} "
                    f"| {now_kst.strftime('%Y-%m-%d %H:%M')} KST"
                )

                success    = False
                last_error = ""
                for attempt in range(1, max_retry + 1):
                    try:
                        result = engine.run_cycle()
                        last_error = result.get("error") or ""
                        if result.get("regime"):
                            last_regime = result["regime"]
                        logger.info(
                            f"[LiveTrader] ✅ 전체 사이클 #{cycle_count} 완료 "
                            f"| 레짐={last_regime} "
                            f"| 신호={result.get('signals_generated', 0)}개"
                        )
                        success = True
                        break
                    except Exception as e:
                        last_error = str(e)
                        logger.error(f"[LiveTrader] 전체 사이클 오류 ({attempt}/{max_retry}): {e}")
                        if attempt < max_retry:
                            time.sleep(60 * attempt)

                if not success:
                    logger.error(f"[LiveTrader] {max_retry}회 재시도 실패 — 경보 발송")
                    db.log_system_event(
                        "ERROR", "LiveTrader",
                        f"전체 사이클 #{cycle_count} 실패: {last_error[:200]}"
                    )
                    notifier.send_cycle_error_alert(cycle_count, max_retry, last_error)

                last_full_date = now_kst.date()
                write_status(
                    running=True, started_at=started_at,
                    last_cycle_at=kst_now().isoformat(),
                    cycle_count=cycle_count, monitor_count=monitor_count,
                    last_regime=last_regime, last_error=last_error,
                )

            # ② 모니터링 사이클 (전체 사이클이 아닌 모든 루프)
            else:
                monitor_count += 1
                logger.info(f"\n{'─'*56}")
                logger.info(
                    f"[LiveTrader] 🔍 모니터링 #{monitor_count} "
                    f"| {now_kst.strftime('%H:%M')} KST"
                )
                try:
                    mresult = engine.run_monitoring_cycle()
                    if mresult.get("regime"):
                        last_regime = mresult["regime"]
                    logger.info(
                        f"[LiveTrader] 모니터링 #{monitor_count} 완료 "
                        f"| 레짐={last_regime} "
                        f"| VIX={mresult.get('vix', 0):.1f} "
                        f"| 청산={mresult.get('closed', 0)}건"
                    )
                except Exception as e:
                    logger.error(f"[LiveTrader] 모니터링 오류: {e}")

                write_status(
                    running=True, started_at=started_at,
                    last_cycle_at=kst_now().isoformat(),
                    cycle_count=cycle_count, monitor_count=monitor_count,
                    last_regime=last_regime,
                )

            # ③ 일일 리포트 (장 마감 직후 15:32~16:00, 하루 1회)
            if should_send_report(config, last_report_date):
                logger.info("[LiveTrader] 📊 일일 수익률 리포트 발송...")
                try:
                    sent = notifier.send_daily_report(
                        db=db,
                        mode=config["system"]["mode"],
                        regime=last_regime,
                        cycle_count=cycle_count,
                    )
                    if sent:
                        last_report_date = date.today()
                        logger.info("[LiveTrader] 📧 일일 리포트 발송 완료")
                        db.log_system_event("INFO", "LiveTrader", "일일 리포트 발송 완료")
                    else:
                        logger.warning("[LiveTrader] 일일 리포트 발송 실패 (이메일 설정 확인)")
                except Exception as e:
                    logger.error(f"[LiveTrader] 일일 리포트 오류: {e}")

            # ④ 다음 모니터링 시각 계산
            now_kst  = kst_now()
            next_run = now_kst + timedelta(minutes=monitor_intv)

            if next_run.time() > MARKET_CLOSE or not is_weekday(next_run):
                # 장 마감 후 → 익일 개장까지 슬립
                next_run = next_market_open(now_kst)
                logger.info(
                    f"[LiveTrader] 장 마감 후 슬립 "
                    f"→ 다음 개장 {next_run.strftime('%m/%d %H:%M')} KST"
                )
            else:
                logger.info(
                    f"[LiveTrader] ⏱  다음 모니터링: "
                    f"{next_run.strftime('%H:%M')} KST ({monitor_intv}분 후)"
                )

            ok = sleep_chunked(secs_until(next_run), db)
            if not ok:
                break

    except KeyboardInterrupt:
        logger.info("[LiveTrader] 사용자 중단 (Ctrl+C)")

    finally:
        write_status(
            running=False, started_at=started_at,
            last_cycle_at=kst_now().isoformat(),
            cycle_count=cycle_count, monitor_count=monitor_count,
            last_regime=last_regime, last_error="프로세스 종료",
        )
        db.log_system_event(
            "WARNING", "LiveTrader",
            f"루프 종료 | 전체={cycle_count}회 | 모니터링={monitor_count}회"
        )
        logger.info("[LiveTrader] 자동매매 루프 종료")


if __name__ == "__main__":
    run()
