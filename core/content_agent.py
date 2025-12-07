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
    similarity_threshold = _load_similarity_threshold()
    min_pui = _load_min_pui()

    def evaluate(content: Dict[str, Any], attempt: int) -> Tuple[Optional[Dict[str, Any]], Dict[str, Any]]:
        """safety→유사도/유니크→PUI까지 검사하고, publish 시 결과 리턴"""
        nonlocal planning_info
        # slug 주입
        _inject_slug(content, case_row.get("slug"))
        if planning_info.get("structure_type") and "structure_type" not in content:
            content["structure_type"] = planning_info["structure_type"]

        joined = _flatten_content(content)
        safety_result = safety.review_content(joined)
        safety_status = safety_result.get("status")
        logging.info("🛡 Safety 결과(시도 %s): status=%s, reason=%s", attempt, safety_status, safety_result.get("reason"))
        if safety_status in ("EDIT", "DISCARD"):
            return None, {"reason": safety_result.get("reason", "safety_discard"), "refined": safety_result.get("refined_content")}

        similarity_score = quality.compute_similarity_to_existing(joined, limit=100)
        uniqueness_score = quality.compute_uniqueness_score(similarity_score)
        unique_block_count = quality.count_unique_blocks(joined, planning_info)

        needs_refine_similarity = similarity_score > similarity_threshold
        needs_refine_uniqueness = uniqueness_score < 0.6 or (unique_block_count or 0) < 3
        if needs_refine_similarity or needs_refine_uniqueness:
            reason_parts = []
            if needs_refine_similarity:
                reason_parts.append(f"유사도 {similarity_score:.2f} > {similarity_threshold:.2f}")
            if needs_refine_uniqueness:
                reason_parts.append(
                    f"유니크도 {uniqueness_score:.2f} / 고유블록 {unique_block_count or 0} (기준: 0.6+, 3+)"
                )
            return None, {
                "reason": " / ".join(reason_parts) + " -> 더 독창적인 구조/표현/예시를 추가하세요.",
                "similarity": similarity_score,
                "uniqueness": uniqueness_score,
                "unique_blocks": unique_block_count,
            }

        pui_scores = quality.compute_pui_score(joined, planning_info, safety_result)
        logging.info(
            "📐 PUI 점수 %s: total=%s, structure=%s, data=%s, eeat=%s",
            case_id,
            pui_scores.get("total"),
            pui_scores.get("structure_score"),
            pui_scores.get("data_score"),
            pui_scores.get("eeat_score"),
        )
        if pui_scores.get("total", 0) < min_pui:
            return None, {
                "reason": f"PUI {pui_scores.get('total')} < 기준 {min_pui}. 구조/데이터/EEAT를 강화해 다시 작성하세요.",
                "pui": pui_scores,
            }

        # publish
        renderer_client.render_and_save(content)
        db.update_status(case_id, "published")
        slug = content.get("page_meta", {}).get("slug") or case_row.get("slug")
        html_path = f"public/{slug}.html" if slug else ""
        metrics.log_case_result(
            case_id,
            slug or "",
            "published",
            None,
            "PASS",
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
        result = {"status": "published", "html_path": html_path, "attempts": None}
        return result, {}

    attempts_allowed = max(1, min(max_retries, 2))

    # 1차: 초안 생성
    content = writer_client.generate(case_row, safe_test_mode=safe_mode, planning_info=planning_info)
    logging.info("✏️ 초안 생성 완료: case_id=%s", case_id)
    attempt = 1
    while attempt <= attempts_allowed:
        if not content:
            last_reason = "writer_failed"
            break
        # 평가
        publish_result, info = evaluate(content, attempt)
        if publish_result:
            logging.info("✅ 발행 성공: case_id=%s, attempts=%s", case_id, attempt)
            publish_result["attempts"] = attempt
            return publish_result

        reason = info.get("reason", "")
        sim = info.get("similarity")
        uniq = info.get("uniqueness")
        ublocks = info.get("unique_blocks")
        pui_scores = info.get("pui") if info.get("pui") else None
        safety_refined = info.get("refined")

        if attempt >= attempts_allowed:
            db.update_status(case_id, "discarded")
            metrics.log_case_result(
                case_id,
                content.get("page_meta", {}).get("slug") or case_row.get("slug") or "",
                "discarded",
                reason or "max_attempts_exceeded",
                "FAIL",
                sim,
                uniq,
                ublocks,
                len(_flatten_content(content).split()),
                pui_scores.get("total") if pui_scores else None,
                pui_scores.get("structure_score") if pui_scores else None,
                pui_scores.get("data_score") if pui_scores else None,
                pui_scores.get("eeat_score") if pui_scores else None,
                planning_info.get("user_intent"),
                planning_info.get("structure_type"),
                case_row.get("category") or "debt",
            )
            logging.info("🧹 최종 폐기: %s (%s)", case_id, reason or "max_attempts_exceeded")
            return {"status": "discarded", "reason": reason or "max_attempts_exceeded"}

        # 2차: safety reason 기반 리라이트
        safety_fb = reason or "법률 자문/보장 어투 제거 및 안전한 정보 톤으로 재작성"
        prev_text = _flatten_content(content)
        logging.info("🔁 Safety에 걸려서 자가 리라이트 시도 (시도 번호=%s/%s): %s", attempt + 1, attempts_allowed, safety_fb)
        content = writer_client.refine_draft(
            {**case_row, "draft_summary": prev_text, "previous_draft": prev_text},
            feedback=safety_fb,
            safe_test_mode=safe_mode,
            planning_info=planning_info,
            safety_feedback=safety_fb,
        )
        if content:
            logging.info("✏️ 자가 리라이트 완료: case_id=%s", case_id)
        attempt += 1

    # 실패 폴백
    db.update_status(case_id, "discarded")
    logging.info("🧹 최종 폐기: %s (%s)", case_id, last_reason if 'last_reason' in locals() else "max_attempts_exceeded")
    return {"status": "discarded", "reason": "max_attempts_exceeded"}


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

