"""
mcp_server.py

FastMCP 기반 MCP 서버.
L0(core) 기능을 MCP 툴로 노출합니다.
"""

from __future__ import annotations

import logging
import uuid
from typing import Any, Dict, List

from fastmcp import FastMCP

from core import db
from core import pipeline
from core import planner


HOST = "127.0.0.1"
PORT = 8765
HTTP_PATH = "/mcp"


mcp = FastMCP("te-don-calculator-factory")


@mcp.tool()
def list_todo_cases(limit: int = 10) -> List[Dict[str, Any]]:
    """status == 'todo'인 케이스를 최대 limit개 반환."""
    try:
        # 잘못 들어간 NULL row 정리
        db.cleanup_null_cases()
        rows = db.list_todo(limit=limit)
        normalized: List[Dict[str, Any]] = []
        for r in rows:
            case_id = r.get("case_id")
            slug = r.get("slug")
            if not case_id:
                # case_id가 없으면 스킵
                continue
            normalized.append(
                {
                    "case_id": case_id,
                    "slug": slug,
                    "status": r.get("status"),
                    "category": r.get("category"),
                    "keywords": r.get("keywords"),
                }
            )
        logging.info("🗂 list_todo_cases 응답: %s", normalized)
        return normalized
    except Exception as exc:  # noqa: BLE001
        logging.exception("list_todo_cases 실패: %s", exc)
        return []


@mcp.tool()
def run_case_pipeline(case_id: str, max_attempts: int = 2) -> Dict[str, Any]:
    """단일 케이스를 처리. 오류(status='error')일 때만 재시도."""
    last_result: Dict[str, Any] = {}
    for _ in range(max_attempts):
        last_result = pipeline.run_case(case_id)
        if last_result.get("status") != "error":
            break
    return last_result


@mcp.tool()
def planner_suggest_cases(product_type: str = "미수금", max_n: int = 5) -> List[Dict[str, Any]]:
    """Seed 기반 planner를 호출하여 새로운 케이스를 제안."""
    try:
        return planner.suggest_new_cases(domain=product_type, limit=max_n)
    except Exception as exc:  # noqa: BLE001
        logging.exception("planner_suggest_cases 실패: %s", exc)
        return []


@mcp.tool()
def append_cases(cases: List[Dict[str, Any]]) -> Dict[str, Any]:
    """새 케이스 리스트를 DB에 status='todo'로 삽입."""
    added = 0
    for c in cases:
        c = dict(c)
        c["status"] = "todo"
        db.upsert_case(c)
        added += 1
    return {"added_count": added}


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    db.init_db()
    # HTTP(SSE) 서버로 실행하여 외부 Client가 접속할 수 있게 함.
    mcp.run(transport="http", host=HOST, port=PORT, path=HTTP_PATH)


if __name__ == "__main__":
    main()

