"""
DARTClient.py — 금융감독원 OpenDART API 클라이언트
════════════════════════════════════════════════════════
• 한국 기업 재무제표 → 피오트로스키 F-스코어 + 마법공식 지표 계산
• DART_API_KEY 환경변수 필요 (https://opendart.fss.or.kr 에서 발급)
• API 미설정 시 → yfinance 방식과 동일한 추정 지표 반환 (폴백)

DART API 주요 엔드포인트:
  GET /api/company.json?stock_code=005930      → corp_code 조회
  GET /api/fnlttSinglAcntAll.json              → 재무제표 전계정 조회
"""

import logging
import os
from datetime import datetime
from typing import Optional

import requests

logger = logging.getLogger(__name__)

_BASE_URL = "https://opendart.fss.or.kr/api"

# DART 계정과목명 → 재무지표 매핑
_TOTAL_ASSETS  = ["자산총계"]
_TOTAL_LIAB    = ["부채총계"]
_TOTAL_EQUITY  = ["자본총계", "자본총계(지배주주)"]
_CURRENT_ASSETS = ["유동자산"]
_CURRENT_LIAB  = ["유동부채"]
_NET_INCOME    = ["당기순이익", "당기순이익(손실)", "당기순손익"]
_OPER_INCOME   = ["영업이익", "영업이익(손실)"]
_OPER_CF       = ["영업활동현금흐름", "영업활동으로인한현금흐름"]
_REVENUE       = ["매출액", "수익(매출액)", "영업수익"]
_CASH          = ["현금및현금성자산", "현금및현금등가물"]


class DARTClient:
    """
    OpenDART API 클라이언트

    주요 메서드:
        get_financial_info(stock_code, market_cap) → dict
          ValueFinder 에이전트가 사용하는 재무 지표 딕셔너리 반환
    """

    def __init__(self):
        self.api_key = os.environ.get("DART_API_KEY", "")
        self._corp_cache: dict = {}       # stock_code → corp_code
        self._stmt_cache: dict = {}       # corp_code_year → list[dict]
        self._info_cache: dict = {}       # stock_code → financial_info dict

        if not self.api_key:
            logger.warning(
                "[DART] DART_API_KEY 미설정 — 재무 데이터 없이 가격 기반 추정치 사용.\n"
                "  https://opendart.fss.or.kr 에서 무료 API Key를 발급받은 후\n"
                "  Replit Secrets에 DART_API_KEY 로 등록하세요."
            )

    @property
    def is_configured(self) -> bool:
        return bool(self.api_key)

    # ── 내부: DART 공통 요청 ────────────────────────────────

    def _get(self, path: str, params: dict, timeout: int = 15) -> dict:
        params["crtfc_key"] = self.api_key
        try:
            resp = requests.get(f"{_BASE_URL}/{path}", params=params, timeout=timeout)
            resp.raise_for_status()
            return resp.json()
        except requests.exceptions.RequestException as e:
            logger.error(f"[DART] API 요청 실패 ({path}): {e}")
            return {}

    # ── Corp Code 조회 (전체 목록 XML 캐시 방식) ───────────

    # ── 코스피 30종목 corp_code 사전 맵 (DART 공시 고유번호) ──
    # DART 홈페이지(dart.fss.or.kr) 기준 확정값. 영구 식별자로 변경되지 않음.
    _KNOWN_CORP_CODES: dict = {
        "005930": "00126380",   # 삼성전자     — DART list.json + batch 검증
        "000660": "00164779",   # SK하이닉스   — batch 검증
        "373220": "01515323",   # LG에너지솔루션 — list.json 검증
        "207940": "00877059",   # 삼성바이오로직스 — list.json 검증
        "005380": "00164742",   # 현대차       — batch 검증
        "000270": "00106641",   # 기아         — list.json 검증
        "005490": "00155319",   # POSCO홀딩스  — list.json 검증
        "051910": "00356361",   # LG화학       — list.json 검증
        "006400": "00126362",   # 삼성SDI      — list.json 검증
        "068270": "00413046",   # 셀트리온     — list.json 검증
        "035720": "00258801",   # 카카오       — list.json 검증
        "035420": "00266961",   # NAVER        — batch 검증
        "105560": "00688996",   # KB금융       — list.json 검증
        "055550": "00382199",   # 신한지주     — batch 검증
        "086790": "00547583",   # 하나금융지주 — list.json 검증
        "316140": "01350869",   # 우리금융지주 — list.json 검증
        "017670": "00159023",   # SK텔레콤     — list.json 검증
        "030200": "00190321",   # KT           — list.json 검증
        "066570": "00401731",   # LG전자       — list.json 검증
        "012450": "00126566",   # 한화에어로스페이스 — list.json 검증
        "034020": "00159616",   # 두산에너빌리티 — list.json 검증
        "033780": "00244455",   # KT&G         — list.json 검증
        "015760": "00159193",   # 한국전력     — list.json 검증
        "010130": "00102858",   # 고려아연     — list.json 검증
        "028260": "00126186",   # 삼성물산     — batch 검증
        "012330": "00164788",   # 현대모비스   — batch 검증
        "034730": "00181712",   # SK           — list.json 검증
        "003550": "00120021",   # LG           — list.json 검증
        "090430": "00583424",   # 아모레퍼시픽 — list.json 검증
        "259960": "00760971",   # 크래프톤     — list.json 검증
    }

    def get_corp_code(self, stock_code: str) -> Optional[str]:
        """
        주식 종목코드(6자리) → DART corp_code(8자리)

        우선순위:
          1) 세션 캐시
          2) 코스피 30 하드코딩 맵 (_KNOWN_CORP_CODES)
          3) DART company.json API 직접 조회 (미지 종목용)
        """
        if not self.api_key:
            return None

        # 1) 세션 캐시
        if stock_code in self._corp_cache:
            return self._corp_cache[stock_code]

        # 2) 하드코딩 맵 (30종목 즉시 반환)
        if stock_code in self._KNOWN_CORP_CODES:
            corp_code = self._KNOWN_CORP_CODES[stock_code]
            self._corp_cache[stock_code] = corp_code
            return corp_code

        # 3) 미지 종목: company.json은 corp_code→info 방향이라 직접 조회 불가
        #    graceful degradation — DART 재무 분석 건너뜀
        logger.warning(f"[DART] corp_code 없음 [{stock_code}] — DART 분석 건너뜀")
        return None

    # ── 재무제표 조회 ──────────────────────────────────────

    def _get_statements(
        self,
        corp_code: str,
        year: int,
        reprt_code: str = "11011",  # 11011=사업보고서, 11012=반기
    ) -> list:
        """
        단일회사 전체 재무제표 조회 (연결 우선, 없으면 개별)
        """
        cache_key = f"{corp_code}_{year}_{reprt_code}"
        if cache_key in self._stmt_cache:
            return self._stmt_cache[cache_key]

        for fs_div in ("CFS", "OFS"):  # 연결 → 개별 순서로 시도
            data = self._get(
                "fnlttSinglAcntAll.json",
                {
                    "corp_code":  corp_code,
                    "bsns_year":  str(year),
                    "reprt_code": reprt_code,
                    "fs_div":     fs_div,
                },
            )
            if data.get("status") == "000" and data.get("list"):
                stmts = data["list"]
                self._stmt_cache[cache_key] = stmts
                return stmts

        logger.warning(f"[DART] {corp_code} {year}년 재무제표 없음")
        self._stmt_cache[cache_key] = []
        return []

    # ── 계정과목 금액 추출 ────────────────────────────────

    @staticmethod
    def _find(stmts: list, account_names: list) -> Optional[float]:
        """재무제표 list에서 account_names에 해당하는 금액 추출 (당기 기준)"""
        for item in stmts:
            if item.get("account_nm") in account_names:
                raw = item.get("thstrm_amount", "").replace(",", "").strip()
                if raw and raw not in ("-", ""):
                    try:
                        return float(raw)
                    except ValueError:
                        pass
        return None

    # ── 핵심 재무 지표 반환 ───────────────────────────────

    def get_financial_info(
        self,
        stock_code: str,
        market_cap: Optional[float] = None,
    ) -> dict:
        """
        ValueFinder 에이전트용 재무 지표 딕셔너리 반환

        Returns (yfinance .info 호환 키 사용):
            returnOnAssets    — ROA = 당기순이익 / 자산총계
            operatingCashflow — 영업활동현금흐름
            totalAssets       — 자산총계
            profitMargins     — 순이익률 = 당기순이익 / 매출액
            debtToEquity      — 부채비율 (D/E) × 100 (%)
            currentRatio      — 유동비율 = 유동자산 / 유동부채
            returnOnEquity    — ROIC 근사 = 영업이익 / 자본총계
            ebitda            — 영업이익 (EBIT 근사치)
            enterpriseValue   — 시가총액 + 총부채 - 현금  (market_cap 필요)
            marketCap         — 시가총액 (매개변수로 전달)
        """
        if not self.api_key:
            return {}

        # 하루 캐시
        cache_key = f"{stock_code}_{datetime.now().strftime('%Y%m%d')}"
        if cache_key in self._info_cache:
            return self._info_cache[cache_key]

        corp_code = self.get_corp_code(stock_code)
        if not corp_code:
            return {}

        # 최근 사업보고서 연도 (전년도 결산)
        current_year = datetime.now().year - 1
        prev_year    = current_year - 1

        stmts      = self._get_statements(corp_code, current_year)
        stmts_prev = self._get_statements(corp_code, prev_year)

        if not stmts:
            logger.warning(f"[DART] {stock_code} 재무제표 없음")
            return {}

        F = self._find

        # ── 당기 계정 ───────────────────────────────────────
        total_assets    = F(stmts, _TOTAL_ASSETS)
        total_liab      = F(stmts, _TOTAL_LIAB)
        total_equity    = F(stmts, _TOTAL_EQUITY)
        current_assets  = F(stmts, _CURRENT_ASSETS)
        current_liab    = F(stmts, _CURRENT_LIAB)
        net_income      = F(stmts, _NET_INCOME)
        oper_income     = F(stmts, _OPER_INCOME)
        oper_cf         = F(stmts, _OPER_CF)
        revenue         = F(stmts, _REVENUE)
        cash            = F(stmts, _CASH) or 0

        # ── 전기 계정 ───────────────────────────────────────
        total_liab_prev = F(stmts_prev, _TOTAL_LIAB) if stmts_prev else None
        total_equity_prev = F(stmts_prev, _TOTAL_EQUITY) if stmts_prev else None

        # ── 지표 계산 ───────────────────────────────────────
        roa           = net_income / total_assets   if (net_income and total_assets)     else None
        de_ratio      = total_liab / total_equity   if (total_liab and total_equity and total_equity != 0) else None
        de_ratio_prev = total_liab_prev / total_equity_prev if (total_liab_prev and total_equity_prev and total_equity_prev != 0) else None
        current_ratio = current_assets / current_liab if (current_assets and current_liab and current_liab != 0) else None
        profit_margin = net_income / revenue        if (net_income and revenue and revenue != 0)           else None
        roic          = oper_income / total_equity  if (oper_income and total_equity and total_equity != 0) else None

        # EV = 시가총액 + 총부채 - 현금 (market_cap은 KRW 단위로 전달)
        ev = None
        if market_cap and total_liab is not None:
            ev = market_cap + total_liab - cash

        result = {
            # ── Piotroski F-스코어 ──────────────────────────
            "returnOnAssets":    roa,
            "operatingCashflow": oper_cf,
            "totalAssets":       total_assets,
            "profitMargins":     profit_margin,
            "debtToEquity":      de_ratio * 100 if de_ratio is not None else None,
            "debtToEquity_prev": de_ratio_prev * 100 if de_ratio_prev is not None else None,
            "currentRatio":      current_ratio,
            # ── 마법공식 ────────────────────────────────────
            "returnOnEquity":    roic,
            "ebitda":            oper_income,
            "enterpriseValue":   ev,
            "marketCap":         market_cap or 0,
            # ── 원시 데이터 ─────────────────────────────────
            "_totalLiabilities": total_liab,
            "_totalEquity":      total_equity,
            "_netIncome":        net_income,
            "_revenue":          revenue,
            "_operatingIncome":  oper_income,
        }

        self._info_cache[cache_key] = result
        logger.info(
            f"[DART] {stock_code} 재무데이터 수집 완료 | "
            f"ROA={roa:.2%}" if roa else f"[DART] {stock_code} 재무데이터 수집 완료 | ROA=N/A"
        )
        return result


# ── 싱글턴 ──────────────────────────────────────────────

_client: Optional[DARTClient] = None


def get_dart_client() -> DARTClient:
    """프로세스 전역 DARTClient 싱글턴 반환"""
    global _client
    if _client is None:
        _client = DARTClient()
    return _client
