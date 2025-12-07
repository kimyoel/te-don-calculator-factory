"""
core.db

SQLite 기반 케이스 라이프사이클 관리.
TODO/DRAFT/SAFETY_CHECK/PUBLISHED/DISCARDED 등의 상태를 저장합니다.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import List, Dict, Any, Optional

DB_PATH = Path("data") / "cases.db"


def get_conn() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    with get_conn() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS cases (
                case_id TEXT PRIMARY KEY,
                slug TEXT UNIQUE,
                category TEXT,
                title TEXT,
                h1 TEXT,
                target_user TEXT,
                pain_summary TEXT,
                intro_copy TEXT,
                keywords TEXT,
                faq1_q TEXT,
                faq1_a TEXT,
                faq2_q TEXT,
                faq2_a TEXT,
                faq3_q TEXT,
                faq3_a TEXT,
                status TEXT DEFAULT 'todo',
                batch_date TEXT,
                user_intent TEXT,
                relationship TEXT,
                legal_strategy TEXT,
                amount_band TEXT,
                structure_type TEXT,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        conn.commit()


def list_todo(limit: int = 10) -> List[Dict[str, Any]]:
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM cases WHERE status = 'todo' LIMIT ?", (limit,)
        ).fetchall()
        return [dict(r) for r in rows]


def cleanup_null_cases() -> int:
    """case_id 또는 slug가 NULL인 행을 제거하고 삭제 건수를 반환."""
    with get_conn() as conn:
        cur = conn.execute(
            "DELETE FROM cases WHERE case_id IS NULL OR slug IS NULL"
        )
        deleted = cur.rowcount
        conn.commit()
        return deleted


def upsert_case(row: Dict[str, Any]) -> None:
    keys = [
        "case_id",
        "slug",
        "category",
        "title",
        "h1",
        "target_user",
        "pain_summary",
        "intro_copy",
        "keywords",
        "faq1_q",
        "faq1_a",
        "faq2_q",
        "faq2_a",
        "faq3_q",
        "faq3_a",
        "status",
        "batch_date",
        "user_intent",
        "relationship",
        "legal_strategy",
        "amount_band",
        "structure_type",
    ]
    data = {k: row.get(k) for k in keys}
    # 안전하게 기본값 채우기
    data["status"] = data.get("status") or "todo"
    data["batch_date"] = data.get("batch_date") or ""
    placeholders = ", ".join([":" + k for k in keys])
    columns = ", ".join(keys)
    updates = ", ".join([f"{k}=excluded.{k}" for k in keys if k != "case_id"])
    with get_conn() as conn:
        conn.execute(
            f"""
            INSERT INTO cases ({columns})
            VALUES ({placeholders})
            ON CONFLICT(case_id) DO UPDATE SET {updates}
            """,
            data,
        )
        conn.commit()


def update_status(case_id: str, status: str, batch_date: Optional[str] = None) -> None:
    with get_conn() as conn:
        conn.execute(
            "UPDATE cases SET status=?, batch_date=? WHERE case_id=?",
            (status, batch_date, case_id),
        )
        conn.commit()


def insert_dummy_case() -> None:
    """테스트용 케이스 하나 삽입 (case_id=TEST-CASE-001, slug=test-freelancer-unpaid, status=todo)."""
    dummy = {
        "case_id": "TEST-CASE-001",
        "slug": "test-freelancer-unpaid",
        "category": "test",
        "title": "프리랜서 미수금 테스트 케이스",
        "h1": "테스트 프리랜서 미수금",
        "target_user": "테스트 사용자",
        "pain_summary": "테스트용 페인 포인트",
        "intro_copy": "이것은 테스트용 인트로 문구입니다.",
        "keywords": "테스트, 프리랜서, 미수금",
        "faq1_q": "테스트 FAQ1?",
        "faq1_a": "테스트 FAQ1 답변",
        "faq2_q": "테스트 FAQ2?",
        "faq2_a": "테스트 FAQ2 답변",
        "faq3_q": "테스트 FAQ3?",
        "faq3_a": "테스트 FAQ3 답변",
        "status": "todo",
        "batch_date": "",
    }
    upsert_case(dummy)


def debug_print_all_cases() -> None:
    """cases 테이블의 모든 row를 콘솔에 출력한다."""
    with get_conn() as conn:
        rows = conn.execute("SELECT * FROM cases").fetchall()
        print("=== cases 테이블 ===")
        for r in rows:
            print(
                f"case_id={r['case_id']}, slug={r['slug']}, status={r['status']}, "
                f"category={r['category']}, keywords={r['keywords']}"
            )
        print(f"총 {len(rows)}건")


def get_all_slugs() -> List[str]:
    """cases 테이블의 모든 slug를 리스트로 반환."""
    with get_conn() as conn:
        rows = conn.execute("SELECT slug FROM cases").fetchall()
        return [r["slug"] for r in rows if r["slug"]]


def list_published_slugs(limit: int = 100) -> List[str]:
    """status='published'인 케이스 slug를 최신순으로 최대 limit개 반환."""
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT slug FROM cases WHERE status='published' ORDER BY created_at DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return [r["slug"] for r in rows if r["slug"]]


def count_cases_by_strategy_and_amount() -> Dict[Tuple[str, str], int]:
    """
    (legal_strategy, amount_band) 조합별 전체 건수를 반환.
    amount_band 필드가 없을 수 있으므로 없으면 빈 문자열 처리.
    """
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT legal_strategy, amount_band, status, COUNT(*) as cnt FROM cases GROUP BY legal_strategy, amount_band, status"
        ).fetchall()
        result: Dict[Tuple[str, str, str], int] = {}
        for r in rows:
            key = (r["legal_strategy"] or "", r["amount_band"] or "", r["status"] or "")
            result[key] = r["cnt"]
        return result


def count_published_total() -> int:
    with get_conn() as conn:
        row = conn.execute("SELECT COUNT(*) as cnt FROM cases WHERE status='published'").fetchone()
        return row["cnt"] if row else 0


def get_case_by_id(case_id: str) -> Optional[Dict[str, Any]]:
    """case_id로 케이스 한 건을 조회한다."""
    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM cases WHERE case_id = ?", (case_id,)
        ).fetchone()
        return dict(row) if row else None


