"""
run_daily.py

단일 프로젝트 배치를 실행하기 위한 진입점 스크립트.
현재는 generate_landing_batch.main()만 호출하지만,
향후 projects/ 구조 등을 도입해 여러 배치를 관리할 여지를 남깁니다.
"""

from __future__ import annotations

import logging
import datetime as dt

import planner_generate_cases
import generate_landing_batch


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    today = dt.date.today().isoformat()

    logging.info("오늘 배치 실행 시작 (%s)", today)

    # 1) 신규 todo 케이스 기획 (중복 slug/case_id/keywords는 planner에서 건너뜀)
    try:
        planner_generate_cases.main()
    except Exception as exc:  # noqa: BLE001
        logging.exception("planner 실행 중 오류: %s", exc)

    # 2) todo 10개까지 랜딩 생성
    try:
        generate_landing_batch.main()
    except Exception as exc:  # noqa: BLE001
        logging.exception("landing 배치 실행 중 오류: %s", exc)

    logging.info("실행 완료 (%s)", today)


if __name__ == "__main__":
    main()

