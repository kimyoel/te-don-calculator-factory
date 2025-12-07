"""
generate_landing_batch.py

data/cases.csv에서 status == "todo"인 케이스를 최대 10개까지 처리하여
writer.generate_content -> renderer.generate_and_save_landing 순으로 실행하고,
성공 시 status를 "done"으로, batch_date를 오늘 날짜(YYYY-MM-DD)로 갱신합니다.
"""

from __future__ import annotations

import csv
import datetime as dt
import logging
from pathlib import Path
from typing import List, Dict

import renderer
import writer

CASES_PATH = Path("data") / "cases.csv"
MAX_BATCH = 10


def load_cases() -> List[Dict[str, str]]:
    rows: List[Dict[str, str]] = []
    with CASES_PATH.open("r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            rows.append(row)
    return rows


def save_cases(rows: List[Dict[str, str]]) -> None:
    if not rows:
        return
    fieldnames = list(rows[0].keys())
    with CASES_PATH.open("w", encoding="utf-8", newline="") as f:
        writer_csv = csv.DictWriter(f, fieldnames=fieldnames)
        writer_csv.writeheader()
        writer_csv.writerows(rows)


def to_case_dict(row: Dict[str, str]) -> Dict[str, str]:
    return {
        "case_id": row.get("case_id", ""),
        "summary": row.get("summary", ""),
        "target_user": row.get("target_user", ""),
        "pain_points": row.get("pain_points", ""),
        "keywords": row.get("keywords", ""),
        "category": row.get("category", ""),
        "slug": row.get("slug", ""),
    }


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    today = dt.date.today().isoformat()

    rows = load_cases()
    todo_rows = [r for r in rows if r.get("status") == "todo"][:MAX_BATCH]

    if not todo_rows:
        logging.info("처리할 todo 케이스가 없습니다.")
        return

    for row in todo_rows:
        case = to_case_dict(row)
        slug = case.get("slug") or case.get("case_id") or "landing"
        try:
            content = writer.generate_content(case)
            if content is None:
                logging.error("콘텐츠 생성 실패: %s", slug)
                continue

            renderer.generate_and_save_landing(content)
            row["status"] = "done"
            row["batch_date"] = today
            logging.info("완료: %s", slug)
        except Exception as exc:  # noqa: BLE001
            logging.exception("케이스 처리 중 오류: %s (%s)", slug, exc)
            continue

    save_cases(rows)


if __name__ == "__main__":
    main()

