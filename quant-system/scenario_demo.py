"""
scenario_demo.py — 주요 시나리오 시뮬레이션 로그 출력기
─────────────────────────────────────────────────────────
실행:  python scenario_demo.py

시나리오 1: KIS API 주도주 탐색 → WebSocket 등록 → MicroSniper 파이프라인
시나리오 2: 비서실장 1차 서킷브레이커 발동 (이평선 역배열) → 전량 청산
"""

import time
from datetime import datetime


# ── ANSI 색상 헬퍼 ─────────────────────────────────────────────
R = "\033[91m";  G = "\033[92m";  Y = "\033[93m"
B = "\033[94m";  M = "\033[95m";  C = "\033[96m"
W = "\033[97m";  DIM = "\033[2m"; BOLD = "\033[1m"; RST = "\033[0m"

def hdr(title: str, color: str = B):
    bar = "═" * 62
    print(f"\n{color}{BOLD}{bar}{RST}")
    print(f"{color}{BOLD}  {title}{RST}")
    print(f"{color}{BOLD}{bar}{RST}")

def log(level: str, module: str, msg: str, delay: float = 0.06):
    ts  = datetime.now().strftime("%H:%M:%S.%f")[:-3]
    lc  = {
        "INFO":     G + "INFO    " + RST,
        "WARNING":  Y + "WARNING " + RST,
        "ERROR":    R + "ERROR   " + RST,
        "CRITICAL": R + BOLD + "CRITICAL" + RST,
        "DEBUG":    DIM + "DEBUG   " + RST,
        "STEP":     C + BOLD + "STEP    " + RST,
        "OK":       G + BOLD + "  ✅    " + RST,
        "BLOCK":    R + BOLD + "  🚨    " + RST,
    }.get(level, "        ")
    print(f"{DIM}{ts}{RST}  {lc}  [{B}{module}{RST}]  {msg}")
    time.sleep(delay)


# ══════════════════════════════════════════════════════════════════
# 시나리오 1: KIS 주도주 탐색 → WebSocket → MicroSniper 파이프라인
# ══════════════════════════════════════════════════════════════════

def scenario_1_market_leader_pipeline():
    hdr("시나리오 1 | KIS API 주도주 탐색 → WebSocket → MicroSniper 파이프라인", C)
    print(f"\n  {DIM}날짜: 2026-06-08(월)  |  시각: 장 시작 직후 09:00{RST}\n")

    # ── STEP 1: 장 시작, 주도주 탐색 ─────────────────────────────
    log("STEP", "live_trader",   "장 시작 감지 (09:00:00) — 주도주 탐색 파이프라인 시작")
    log("INFO", "KISBroker",    "KIS OAuth2 토큰 발급 요청...")
    log("INFO", "KISBroker",    "토큰 발급 완료 | 만료: 09:00:03 +24h")

    log("INFO", "KISBroker",    "주도주 탐색 시작 | 시장=J(코스피) | 목표=40개")
    log("INFO", "KISBroker",    "KIS REST API 호출 → FHPST01710000 (거래량 순위)")
    time.sleep(0.2)

    leaders = [
        ("005930", "삼성전자",     "1,847,523주", "+2.31%"),
        ("000660", "SK하이닉스",   "1,203,847주", "+3.15%"),
        ("373220", "LG에너지솔루션","  923,401주", "+1.87%"),
        ("207940", "삼성바이오로직스","  712,338주", "+4.02%"),
        ("005380", "현대차",       "  634,921주", "+1.44%"),
        ("066570", "LG전자",       "  598,234주", "+2.76%"),
        ("035720", "카카오",        "  554,123주", "+5.12%"),
        ("035420", "NAVER",        "  523,891주", "+3.67%"),
        ("068270", "셀트리온",      "  487,654주", "+2.93%"),
        ("051910", "LG화학",       "  456,231주", "+1.65%"),
    ]

    print(f"\n  {G}{'종목코드':<10} {'종목명':<18} {'거래량':>14} {'등락률':>8}{RST}")
    print(f"  {'─'*54}")
    for code, name, vol, chg in leaders:
        color = G if "+" in chg else R
        print(f"  {W}{code:<10}{RST} {name:<18} {DIM}{vol:>14}{RST}  {color}{chg:>8}{RST}")
        time.sleep(0.05)

    print(f"\n  ... (총 40개 종목 추출)")
    time.sleep(0.1)

    log("OK",   "KISBroker",    "주도주 탐색 완료 | 40개 추출 | 상위5: 005930 000660 373220 207940 005380")

    # ── STEP 2: WebSocket 등록 ────────────────────────────────────
    print()
    log("STEP", "KISBroker",    "WebSocket 구독 등록 시작 | 40개 종목")
    log("INFO", "KISBroker",    "WebSocket 허가 키 발급 → /oauth2/Approval")
    log("INFO", "KISBroker",    "WebSocket 연결 중... ws://ops.koreainvestment.com:31000")
    time.sleep(0.15)
    log("INFO", "KISBroker",    "TR H0STCNT0 구독 등록: 005930 (삼성전자)")
    log("INFO", "KISBroker",    "TR H0STCNT0 구독 등록: 000660 (SK하이닉스)")
    log("INFO", "KISBroker",    "TR H0STCNT0 구독 등록: 373220 (LG에너지솔루션)")
    log("DEBUG","KISBroker",    "... (37개 추가 종목 구독 등록)")
    log("OK",   "KISBroker",    "WebSocket 구독 완료 | 40개 종목 실시간 스트리밍 활성화", 0.1)

    # ── STEP 3: 실시간 데이터 수신 ───────────────────────────────
    print()
    log("STEP", "KIS-WebSocket", "실시간 체결 데이터 수신 시작 (1분봉 집계)")
    time.sleep(0.1)

    realtime_data = [
        ("09:01:23", "005930", "78,400원", "   +1,200주", "1분봉 집계 중"),
        ("09:01:47", "000660", "198,500원","     +890주", "1분봉 집계 중"),
        ("09:02:11", "373220", "412,000원","   +2,140주", "MA5 돌파 감지"),
        ("09:02:34", "207940", "891,000원","     +670주", "RSI 과열 접근"),
        ("09:03:01", "005930", "78,900원", "   +3,450주", "거래량 급증 감지 ⚡"),
    ]
    print(f"\n  {DIM}{'시각':<10} {'종목':<8} {'현재가':>10} {'1분거래량':>12}  {'상태'}{RST}")
    print(f"  {'─'*56}")
    for ts, code, price, vol, status in realtime_data:
        highlight = Y if "급증" in status or "돌파" in status else DIM
        print(f"  {DIM}{ts}{RST}  {W}{code}{RST}  {price:>10}  {vol:>12}  {highlight}{status}{RST}")
        time.sleep(0.08)

    # ── STEP 4: MicroSniper 신호 생성 ────────────────────────────
    print()
    log("STEP", "MicroSniper",  "WebSocket 데이터 폴링 → 4중 지표 계산")
    log("INFO", "MicroSniper",  "005930 분석 | ADX=28.4(>20✅) | BB%B=0.03(<0.05✅) | RSI=19.8(<21✅)")
    log("INFO", "MicroSniper",  "005930 | Stochastic %K=12 < %D=18 → Golden Cross 대기...")
    time.sleep(0.15)
    log("INFO", "MicroSniper",  "005930 | Stochastic Golden Cross 확인! → 4중 조건 ALL 충족")
    log("OK",   "MicroSniper",  (
        "매수 신호 생성 | 005930(삼성전자) | "
        "진입=78,900 | 손절=77,322(-2%) | 목표=80,085(+1.5%) | 점수=0.94"
    ))

    log("INFO", "TradingEngine","KISBroker.buy_market(005930, '마이크로스나이퍼', 5,000,000)")
    log("INFO", "KISBroker",    "매수 주문 → 005930 | 63주 × 78,900원 = 4,970,700원")
    log("INFO", "KISBroker",    "KIS REST API 호출 → TTTC0802U (시장가 매수)")
    log("OK",   "KISBroker",    "매수 체결 접수 | 005930 63주 | 주문번호=20260608-00123456")
    log("INFO", "TradingEngine","Rate: 1건/초 (한도: 18건/초, 여유 17건)")

    print(f"\n  {G}{BOLD}파이프라인 완료{RST}")
    print(f"  {DIM}09:00 주도주탐색(KIS v1-047) → 09:01 WebSocket등록(40종목){RST}")
    print(f"  {DIM}→ 09:02~ 실시간수신(H0STCNT0) → 09:03 MicroSniper매수체결{RST}\n")


# ══════════════════════════════════════════════════════════════════
# 시나리오 2: 비서실장 1차 서킷브레이커 (이평선 역배열) → 전량 청산
# ══════════════════════════════════════════════════════════════════

def scenario_2_supreme_circuit_breaker():
    hdr("시나리오 2 | 비서실장 1차 서킷브레이커 발동 → 전량 청산 시나리오", R)
    print(f"\n  {DIM}가상 시나리오: 2026-07-15(수) | 코스피 6주 연속 하락 국면{RST}")
    print(f"  {DIM}VIX=23.4 (임계치 미달) — 이평선 역배열 조건으로 발동{RST}\n")

    # ── STEP 0: 레짐 분석 ─────────────────────────────────────────
    log("STEP", "비서실장",     "분석 사이클 시작 (14:00:00 정기 분석)")
    log("INFO", "비서실장",     "STEP 0: 레짐 분석 시작 (VIX + MA배열 + MACD)")
    log("INFO", "KoreaData",   "KOSPI 지수 데이터 수집 (1년치)")
    time.sleep(0.15)
    log("INFO", "MarketAnalyzer","VIX=23.4 → DEFENSIVE 신호 (30 미만)")
    log("INFO", "MarketAnalyzer","MACD=-847.3 → BEARISH_MOMENTUM")
    log("WARNING","MarketAnalyzer","MA배열: MA5=2,523 | MA20=2,641 | MA60=2,784")
    log("WARNING","MarketAnalyzer","⚠️  60일선(2,784) > 20일선(2,641) > 5일선(2,523) — 완전 역배열 감지!")

    # ── STEP 1: 1차 서킷브레이커 체크 ────────────────────────────
    print()
    log("STEP", "비서실장",     "STEP 1: 1차 하드코딩 서킷브레이커 체크 (최우선)")
    log("INFO", "비서실장",     "조건A: VIX=23.4 < 30 → 미발동")
    time.sleep(0.1)
    log("INFO", "비서실장",     "조건B: MA60=2,784 > MA20=2,641 > MA5=2,523 → 완전 역배열 확인")
    time.sleep(0.12)

    print(f"\n  {'═'*60}")
    print(f"  {R}{BOLD}  🚨 [1차 서킷브레이커 — 조건B] MA역배열 OVERRIDE{RST}")
    print(f"  {R}  MA60=2,784 > MA20=2,641 > MA5=2,523{RST}")
    print(f"  {R}  (이평선 완전 역배열 — 구조적 하락 추세 확인){RST}")
    print(f"  {'═'*60}\n")
    time.sleep(0.2)

    log("CRITICAL","비서실장",  "1차 서킷브레이커 발동! → 이하 모든 분석/AI 판단 차단")
    log("CRITICAL","비서실장",  "최종 지시: 가동률=0% | 현금=100% | 전량청산대기=True")
    log("CRITICAL","비서실장",  "※ 이 지시는 DQN AI 예측, 레짐 분석, 수동 설정 모두를 Override")

    # ── DQN이 긍정 신호를 냈을 경우 차단 시뮬레이션 ──────────────
    print()
    log("INFO",  "DQNChief",   "DQN 예측 실행 중... (Q-value 계산)")
    log("INFO",  "DQNChief",   "DQN 출력: 밸류파인더=35% | 트렌드=40% | 스윙=15% (기대수익 +2.3%)")
    log("BLOCK", "비서실장",   "DQN 판단 차단! → 1차 서킷브레이커가 발동 중 (Override 적용)")
    log("BLOCK", "비서실장",   "DQN 배분(밸류35%·트렌드40%·스윙15%) → 강제 0%로 덮어쓰기")

    # ── 배분 결과 ─────────────────────────────────────────────────
    print()
    print(f"  {BOLD}최종 에이전트 배분 (1차 서킷브레이커 강제 적용){RST}")
    print(f"  {'─'*44}")
    allocs = [
        ("밸류파인더",    "35.0%", " 0.0%", R),
        ("트렌드라이더",  "40.0%", " 0.0%", R),
        ("스윙마스터",   "15.0%", " 0.0%", R),
        ("마이크로스나이퍼","10.0%", " 0.0%", R),
        ("현금",          " 0.0%", "100.0%", G),
    ]
    print(f"  {DIM}{'에이전트':<16} {'DQN 예측':>10}  →  {'실제 배분':>10}{RST}")
    for name, dqn, real, color in allocs:
        print(f"  {name:<16} {Y}{dqn:>10}{RST}  →  {color}{BOLD}{real:>10}{RST}")
    print()

    # ── 보유 포지션 전량 청산 ─────────────────────────────────────
    log("STEP", "TradingEngine","1차 서킷브레이커 → is_liquidation_pending=True 감지")
    log("CRITICAL","TradingEngine","보유 포지션 전량 청산 명령 하달")
    time.sleep(0.1)

    positions = [
        ("005930", "삼성전자",      63,  78_900, 76_500, -151_200),
        ("000660", "SK하이닉스",    12, 198_500, 189_200, -111_600),
        ("373220", "LG에너지솔루션",  5, 412_000, 395_000,  -85_000),
        ("207940", "삼성바이오로직스", 2, 891_000, 923_000,  +64_000),
    ]

    print(f"\n  {BOLD}청산 실행 현황{RST}")
    print(f"  {DIM}{'종목':>8} {'종목명':<18} {'수량':>5} {'평단가':>10} {'현재가':>10} {'손익':>12}{RST}")
    print(f"  {'─'*68}")
    total_pnl = 0
    for code, name, qty, avg, cur, pnl in positions:
        color = G if pnl > 0 else R
        log("INFO", "KISBroker",
            f"sell_market({code}) → {qty}주 × {cur:,}원 | PnL={pnl:+,}원 | 사유=서킷브레이커청산")
        print(f"  {W}{code:>8}{RST} {name:<18} {qty:>5}주  {avg:>10,}  {cur:>10,}  {color}{pnl:>+12,}원{RST}")
        total_pnl += pnl
        time.sleep(0.1)

    total_color = G if total_pnl > 0 else R
    print(f"  {'─'*68}")
    print(f"  {'합계':>42}  {total_color}{BOLD}{total_pnl:>+12,}원{RST}")
    print()

    log("OK",   "TradingEngine","전량 청산 완료 | 4개 포지션 매도 접수 | 총손익={:+,}원".format(total_pnl))
    log("INFO", "TradingEngine","포트폴리오 상태: 현금=100% | 투자=0% | 신규매수=금지")
    log("INFO", "비서실장",     "1차 서킷브레이커 유지 중... (해제 조건: MA정배열 복귀)")

    print(f"\n  {DIM}  ─ 핵심 교훈 ─────────────────────────────────────────{RST}")
    print(f"  {DIM}  VIX가 30 미만이어도 이평선 완전 역배열(60>20>5)이 감지되면{RST}")
    print(f"  {DIM}  DQN이 +2.3% 수익을 예측하더라도 1차 서킷브레이커가{RST}")
    print(f"  {DIM}  모든 매수를 차단하고 전량 청산을 집행합니다.{RST}\n")


# ══════════════════════════════════════════════════════════════════
# 시나리오 3: TrendRider 3중 AND — Whipsaw 필터링 예시
# ══════════════════════════════════════════════════════════════════

def scenario_3_trendrider_triple_and():
    hdr("시나리오 3 | TrendRider 3중 AND 조건 — Whipsaw 필터링 결과", G)
    print(f"\n  {DIM}일반 공격 레짐(VIX=15.2, MA정배열) — 종목 30개 스캔{RST}\n")

    log("STEP", "트렌드라이더", "30개 종목 추세 분석 | 조건: 골든크로스(5/20) AND MACD≥0 AND 거래량≥1.5x")
    time.sleep(0.1)

    results = [
        # (종목, 골든크로스, MACD값,  거래량배수, 통과여부, 제외사유)
        ("005930", "✅골든크로스",  "+1,247",  "2.3x", True,  ""),
        ("000660", "✅골든크로스",  "-0,382",  "1.8x", False, "MACD < 0 (음의 모멘텀)"),
        ("373220", "⬆️ ABOVE",     "+0,891",  "1.2x", False, "골든크로스 아님 (단순상회)"),
        ("207940", "✅골든크로스",  "+2,134",  "1.1x", False, "거래량 1.1x < 1.5x (가짜돌파)"),
        ("035720", "✅골든크로스",  "+0,445",  "1.7x", True,  ""),
        ("066570", "📉데드크로스",  "-1,203",  "2.1x", False, "데드크로스 (하락추세)"),
        ("035420", "✅골든크로스",  "+1,876",  "2.9x", True,  ""),
        ("068270", "⬆️ ABOVE",     "+0,234",  "3.1x", False, "골든크로스 아님 (단순상회)"),
    ]

    print(f"  {DIM}{'종목':>8}  {'교차신호':<14} {'MACD':>8}  {'거래량배수':>10}  {'결과'}{RST}")
    print(f"  {'─'*64}")
    for code, cross, macd, vol, passed, reason in results:
        if passed:
            r_str = f"{G}✅ 통과{RST}"
        else:
            r_str = f"{R}❌ 제외 — {reason}{RST}"
        print(f"  {W}{code:>8}{RST}  {cross:<14} {macd:>8}  {vol:>10}  {r_str}")
        time.sleep(0.07)

    print(f"\n  {DIM}... (30개 중 22개 추가 스캔){RST}")
    time.sleep(0.1)
    print()

    log("INFO", "트렌드라이더", "필터링 결과 | 골든크로스미충족=11 | MACD미충족=8 | 거래량미충족=6 | 최종통과=5개")
    log("OK",   "트렌드라이더", "매수 신호 5개 생성 (30개 → 5개, 83% 필터링)")
    log("INFO", "트렌드라이더", "통과종목: 005930 035720 035420 (+ 2개) → 예산 균등 배분")
    print(f"\n  {DIM}  Whipsaw 방지 효과: 30개 후보 중 25개(83%) 가짜 신호 제거{RST}")
    print(f"  {DIM}  기존(골든크로스만): 약 15개 진입 → Whipsaw 강화판: 5개만 진입{RST}\n")


# ══════════════════════════════════════════════════════════════════
# 메인
# ══════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    print(f"\n{BOLD}{M}{'▓'*64}{RST}")
    print(f"{BOLD}{M}  Alpha Quant — 업그레이드 시나리오 데모 로그{RST}")
    print(f"{BOLD}{M}{'▓'*64}{RST}")
    print(f"\n  {DIM}3가지 핵심 업그레이드 적용 결과를 시뮬레이션합니다.{RST}")
    print(f"  {DIM}1. KIS API 주도주 탐색 + WebSocket 파이프라인{RST}")
    print(f"  {DIM}2. 1차 하드코딩 서킷브레이커 (DQN Override){RST}")
    print(f"  {DIM}3. TrendRider 3중 AND 조건 (Whipsaw 방지){RST}\n")

    input(f"  {Y}Enter를 누르면 시작합니다...{RST}")

    scenario_1_market_leader_pipeline()
    input(f"\n  {Y}다음 시나리오로 진행하려면 Enter를 누르세요...{RST}")

    scenario_2_supreme_circuit_breaker()
    input(f"\n  {Y}다음 시나리오로 진행하려면 Enter를 누르세요...{RST}")

    scenario_3_trendrider_triple_and()

    print(f"\n{BOLD}{G}{'═'*64}{RST}")
    print(f"{BOLD}{G}  데모 완료 — 모든 시나리오 출력 종료{RST}")
    print(f"{BOLD}{G}{'═'*64}{RST}\n")
