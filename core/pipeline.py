"""
core.pipeline

L0 파이프라인: content_agent를 통해 다중 시도로 퍼블리시/폐기 결정.
"""

from __future__ import annotations

import logging
from typing import Dict, Any

from core import content_agent


def run_case(case_id: str) -> Dict[str, Any]:
    """Content Agent를 사용해 케이스를 처리한다."""
    return content_agent.run_production_loop(case_id, max_retries=3)


if __name__ == "__main__":
    from core.db import init_db, insert_dummy_case, debug_print_all_cases

    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    init_db()
    insert_dummy_case()
    debug_print_all_cases()
    result = run_case("TEST-CASE-001")
    print(result)
    debug_print_all_cases()

