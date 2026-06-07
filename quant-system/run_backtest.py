"""
백테스트 독립 실행 스크립트
코로나 폭락(2019-2023 IS) + OOS(2024) 5년치 검증
결과는 SQLite DB에 영구 저장 → 대시보드 '백테스트' 탭에서 자동 확인
"""

import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)

from config_loader import load_config
from database import QuantDatabase
from SimulationEngine import BacktestEngine


def main():
    print("\n" + "=" * 65)
    print("  🔬 AI 퀀트 시스템 — 백테스트 엔진 구동")
    print("  기간: 2019-01-01 ~ 2023-12-31 (IS, 코로나 폭락 포함)")
    print("        2024-01-01 ~ 2024-12-31 (OOS, 미지 데이터 검증)")
    print("  전략: 트렌드라이더 | 스윙마스터 | Buy&Hold 벤치마크")
    print("=" * 65 + "\n")

    config = load_config()
    db = QuantDatabase(config["system"]["db_path"])
    engine = BacktestEngine(config, db=db)

    print("⏳ yfinance에서 과거 데이터를 수집 중입니다 (수 분 소요)...\n")
    results = engine.run_all_strategies(save_to_db=True)

    print("\n" + "=" * 65)
    print("  📊 백테스트 결과 요약")
    print("=" * 65)

    for key, report in results.items():
        report.print_summary()

    print("\n✅ 모든 결과가 DB에 저장되었습니다.")
    print(f"   DB 경로: {config['system']['db_path']}")
    print("   대시보드 '🔬 백테스트' 탭을 새로고침하면 결과를 확인할 수 있습니다.\n")


if __name__ == "__main__":
    main()
