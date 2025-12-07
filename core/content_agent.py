"""
core.content_agent

Writer + Safety를 반복 적용하며 콘텐츠를 보정하는 에이전트 계층.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

from core import db
from core import safety
from core import writer_client
from core import renderer_client
from core import quality
from core import metrics


def _flatten_content(content: Dict[str, Any]) -> str:
    def walk(val):
        if isinstance(val, dict):
            return " ".join(walk(v) for v in val.values())
        if isinstance(val, list):
            return " ".join(walk(v) for v in val)
        return str(val)

    return walk(content)


def _inject_slug(content: Dict[str, Any], slug: Optional[str]) -> None:
    if not slug:
        return
    pm = content.get("page_meta")
    if not isinstance(pm, dict):
        pm = {}
        content["page_meta"] = pm
    if not pm.get("slug"):
        pm["slug"] = slug


DEFAULT_SIMILARITY_THRESHOLD = 0.4
DEFAULT_MIN_PUI = 80


def _load_similarity_threshold() -> float:
    path = Path("config.json")
    if not path.exists():
        return DEFAULT_SIMILARITY_THRESHOLD
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return float(data.get("similarity_threshold", DEFAULT_SIMILARITY_THRESHOLD))
    except Exception:
        return DEFAULT_SIMILARITY_THRESHOLD

def _load_min_pui() -> int:
    path = Path("config.json")
    if not path.exists():
        return DEFAULT_MIN_PUI
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return int(data.get("min_pui_score", DEFAULT_MIN_PUI))
    except Exception:
        return DEFAULT_MIN_PUI


def run_production_loop(case_id: str, max_retries: int = 3, include_content: bool = False) -> Dict[str, Any]:
    """
    1) DB에서 케이스 조회
    2) writer_client.generate로 초안 작성
    3) safety.check_text (하드 필터)
    4) safety.audit_content (소프트 검수) → feedback 있으면 refine 재시도
    5) max_retries 내에서 성공 시 렌더링 후 published, 실패 시 discarded
    """
    case_row = db.get_case_by_id(case_id)
    if not case_row:
        return {"status": "error", "reason": "case_not_found"}

    safe_mode = case_id == "TEST-CASE-001" or case_row.get("category") == "test"
    planning_info = {
        "user_intent": case_row.get("user_intent"),
        "structure_type": case_row.get("structure_type"),
        "relationship": case_row.get("relationship"),
        "legal_strategy": case_row.get("legal_strategy"),
        "unique_data_point": case_row.get("unique_data_point"),
        "main_keyword": case_row.get("main_keyword"),
    }
    last_feedback = ""
    last_content: Optional[Dict[str, Any]] = None
    similarity_threshold = _load_similarity_threshold()
    min_pui = _load_min_pui()
    similarity_score: Optional[float] = None
    uniqueness_score: Optional[float] = None
    unique_block_count: Optional[int] = None
    pui_scores: Optional[Dict[str, int]] = None
    safety_status: Optional[str] = None

    for attempt in range(1, max_retries + 1):
        if attempt == 1:
            content = writer_client.generate(case_row, safe_test_mode=safe_mode, planning_info=planning_info)
        else:
            # refine with feedback
            content = writer_client.refine_draft(
                {**case_row, "draft_summary": last_content},
                feedback=last_feedback,
                safe_test_mode=safe_mode,
                planning_info=planning_info,
            )

        if not content:
            last_feedback = "writer_failed"
            continue

        # slug 주입
        _inject_slug(content, case_row.get("slug"))
        # 구조 타입 유지
        if planning_info.get("structure_type") and "structure_type" not in content:
            content["structure_type"] = planning_info["structure_type"]

        joined = _flatten_content(content)
        safety_result = safety.review_content(joined)
        safety_status = safety_result.get("status")

        if safety_status in ("EDIT", "DISCARD"):
            # safety 피드백을 활용해 자가 리라이트 1회 시도
            if attempt >= max_retries:
                db.update_status(case_id, "discarded")
                metrics.log_case_result(
                    case_id,
                    content.get("page_meta", {}).get("slug") or case_row.get("slug") or "",
                    "discarded",
                    safety_result.get("reason", "safety_discard"),
                    safety_status,
                    similarity_score,
                    uniqueness_score,
                    unique_block_count,
                    len(joined.split()),
                    pui_scores.get("total") if pui_scores else None,
                    pui_scores.get("structure_score") if pui_scores else None,
                    pui_scores.get("data_score") if pui_scores else None,
                    pui_scores.get("eeat_score") if pui_scores else None,
                    planning_info.get("user_intent"),
                    planning_info.get("structure_type"),
                    case_row.get("category") or "debt",
                )
                return {"status": "discarded", "reason": safety_result.get("reason", "safety_discard")}
            safety_fb = safety_result.get("reason", "")
            last_feedback = safety_fb
            last_content = safety_result.get("refined_content") or content
            # 다음 루프에서 refine_draft 호출
            logging.info("Safety %s on %s (attempt %s), try self-rewrite: %s", safety_status, case_id, attempt, safety_fb)
            continue

        # PASS 시 유사도/유니크 검사
        similarity_score = quality.compute_similarity_to_existing(joined, limit=100)
        uniqueness_score = quality.compute_uniqueness_score(similarity_score)
        unique_block_count = quality.count_unique_blocks(joined, planning_info)

        needs_refine_similarity = similarity_score > similarity_threshold
        needs_refine_uniqueness = uniqueness_score < 0.6 or (unique_block_count or 0) < 3

        if needs_refine_similarity or needs_refine_uniqueness:
            if attempt >= max_retries:
                db.update_status(case_id, "discarded")
                metrics.log_case_result(
                    case_id,
                    content.get("page_meta", {}).get("slug") or case_row.get("slug") or "",
                    "discarded",
                    "similarity_or_uniqueness_fail",
                    safety_status,
                    similarity_score,
                    uniqueness_score,
                    unique_block_count,
                    len(joined.split()),
                    planning_info.get("user_intent"),
                    planning_info.get("structure_type"),
                    case_row.get("category") or "debt",
                )
                return {"status": "discarded", "reason": "similarity_or_uniqueness_fail"}
            reason_parts = []
            if needs_refine_similarity:
                reason_parts.append(f"유사도 {similarity_score:.2f} > {similarity_threshold:.2f}")
            if needs_refine_uniqueness:
                reason_parts.append(
                    f"유니크도 {uniqueness_score:.2f} / 고유블록 {unique_block_count or 0} (기준: 0.6+, 3+)"
                )
            last_feedback = " / ".join(reason_parts) + " -> 더 독창적인 구조/표현/예시를 추가하세요."
            last_content = content
            logging.info("Similarity high on %s (attempt %s): %s", case_id, attempt, last_feedback)
            continue

        # PUI 점수 계산
        pui_scores = quality.compute_pui_score(joined, planning_info, safety_result)
        logging.info(
            "PUI on %s: total=%s, structure=%s, data=%s, eeat=%s",
            case_id,
            pui_scores.get("total"),
            pui_scores.get("structure_score"),
            pui_scores.get("data_score"),
            pui_scores.get("eeat_score"),
        )
        if pui_scores.get("total", 0) < min_pui:
            if attempt >= max_retries:
                db.update_status(case_id, "discarded")
                metrics.log_case_result(
                    case_id,
                    content.get("page_meta", {}).get("slug") or case_row.get("slug") or "",
                    "discarded",
                    "pui_too_low",
                    safety_status,
                    similarity_score,
                    uniqueness_score,
                    unique_block_count,
                    len(joined.split()),
                    pui_scores.get("total"),
                    pui_scores.get("structure_score"),
                    pui_scores.get("data_score"),
                    pui_scores.get("eeat_score"),
                    planning_info.get("user_intent"),
                    planning_info.get("structure_type"),
                    case_row.get("category") or "debt",
                )
                return {"status": "discarded", "reason": "pui_too_low"}
            last_feedback = (
                f"PUI {pui_scores.get('total')} < 기준 {min_pui}. 구조/데이터/EEAT를 강화해 다시 작성하세요."
            )
            last_content = content
            logging.info("PUI low on %s (attempt %s): %s", case_id, attempt, last_feedback)
            continue

        # publish
        try:
            renderer_client.render_and_save(content)
            db.update_status(case_id, "published")
            slug = content.get("page_meta", {}).get("slug") or case_row.get("slug")
            html_path = f"public/{slug}.html" if slug else ""
            metrics.log_case_result(
                case_id,
                slug or "",
                "published",
                None,
                safety_status,
                similarity_score,
                uniqueness_score,
                unique_block_count,
                len(joined.split()),
                pui_scores.get("total") if pui_scores else None,
                pui_scores.get("structure_score") if pui_scores else None,
                pui_scores.get("data_score") if pui_scores else None,
                pui_scores.get("eeat_score") if pui_scores else None,
                planning_info.get("user_intent"),
                planning_info.get("structure_type"),
                case_row.get("category") or "debt",
            )
            result = {"status": "published", "html_path": html_path, "attempts": attempt}
            if include_content:
                result["content"] = content
            return result
        except Exception as exc:  # noqa: BLE001
            logging.exception("렌더링/저장 중 오류: %s", exc)
            last_feedback = f"render_error: {exc}"
            continue

    # 실패
    db.update_status(case_id, "discarded")
    metrics.log_case_result(
        case_id,
        case_row.get("slug") or "",
        "discarded",
        last_feedback or "max_retries_exceeded",
        safety_status,
        similarity_score,
        uniqueness_score,
        unique_block_count,
        None,
        pui_scores.get("total") if pui_scores else None,
        pui_scores.get("structure_score") if pui_scores else None,
        pui_scores.get("data_score") if pui_scores else None,
        pui_scores.get("eeat_score") if pui_scores else None,
        planning_info.get("user_intent"),
        planning_info.get("structure_type"),
        case_row.get("category") or "debt",
    )
    return {"status": "discarded", "reason": last_feedback or "max_retries_exceeded"}


if __name__ == "__main__":
    from core.db import init_db, insert_dummy_case, debug_print_all_cases

    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    init_db()
    insert_dummy_case()
    debug_print_all_cases()
    result = run_production_loop("TEST-CASE-001", max_retries=3, include_content=True)
    print("RESULT:", result)
    if result.get("content"):
        hero = result["content"].get("hero_section", {})
        print("샘플 헤드라인:", hero.get("headline"))
        print("샘플 인트로:", hero.get("intro_copy"))
    debug_print_all_cases()

