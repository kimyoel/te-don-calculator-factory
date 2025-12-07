"""
core.metrics

케이스 처리 결과를 CSV로 기록.
"""

from __future__ import annotations

import csv
from datetime import datetime
from pathlib import Path
from typing import Optional

LOG_PATH = Path("logs") / "content_metrics.csv"


def _ensure_header() -> None:
    LOG_PATH.parent.mkdir(exist_ok=True)
    if not LOG_PATH.exists():
        with LOG_PATH.open("w", encoding="utf-8", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(
                [
                    "timestamp",
                    "case_id",
                    "slug",
                    "status",
                    "reason",
                    "safety_status",
                    "similarity_score",
                    "uniqueness_score",
                    "unique_block_count",
                    "word_count",
                    "pui_total",
                    "pui_structure",
                    "pui_data",
                    "pui_eeat",
                    "user_intent",
                    "structure_type",
                    "domain_type",
                ]
            )


def log_case_result(
    case_id: str,
    slug: str,
    status: str,
    reason: Optional[str],
    safety_status: Optional[str],
    similarity_score: Optional[float],
    uniqueness_score: Optional[float],
    unique_block_count: Optional[int],
    word_count: Optional[int],
    pui_total: Optional[int],
    pui_structure: Optional[int],
    pui_data: Optional[int],
    pui_eeat: Optional[int],
    user_intent: Optional[str],
    structure_type: Optional[str],
    domain_type: str = "debt",
) -> None:
    _ensure_header()
    with LOG_PATH.open("a", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(
            [
                datetime.utcnow().isoformat(),
                case_id,
                slug,
                status,
                reason or "",
                safety_status or "",
                f"{similarity_score:.4f}" if similarity_score is not None else "",
                f"{uniqueness_score:.4f}" if uniqueness_score is not None else "",
                unique_block_count if unique_block_count is not None else "",
                word_count or "",
                pui_total if pui_total is not None else "",
                pui_structure if pui_structure is not None else "",
                pui_data if pui_data is not None else "",
                pui_eeat if pui_eeat is not None else "",
                user_intent or "",
                structure_type or "",
                domain_type,
            ]
        )

