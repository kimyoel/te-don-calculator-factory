"""
run_daily.py

단일 프로젝트 배치를 실행하기 위한 진입점 스크립트.
현재는 generate_landing_batch.main()만 호출하지만,
향후 projects/ 구조 등을 도입해 여러 배치를 관리할 여지를 남깁니다.
"""

from __future__ import annotations

import logging

import generate_landing_batch


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    logging.info("오늘 배치 실행 시작")
    generate_landing_batch.main()
    logging.info("실행 완료")


if __name__ == "__main__":
    main()

