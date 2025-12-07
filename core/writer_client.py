"""
core.writer_client

writer.generate_content 래퍼.
"""

from __future__ import annotations

from typing import Any, Dict, Optional

import writer
from config import Config


SAFE_TEST_TEXT = {
    "page_meta": {
        "title": "테스트 안전 케이스",
        "description": "테스트용 안전 문구",
        "keywords": "테스트, 안전",
        "slug": "",
    },
    "hero_section": {
        "headline": "테스트용 안전 헤드라인",
        "intro_copy": "이 문서는 테스트를 위한 안전한 샘플 문구입니다.",
    },
    "situation_analysis": {
        "pain_summary": "테스트용 페인 포인트 요약",
    },
    "action_guide": {
        "guidance": "테스트용 안내 문구입니다.",
    },
    "faq_section": [
        {"question": "테스트 FAQ1?", "answer": "테스트 FAQ1 답변"},
        {"question": "테스트 FAQ2?", "answer": "테스트 FAQ2 답변"},
        {"question": "테스트 FAQ3?", "answer": "테스트 FAQ3 답변"},
    ],
    "legal_safety": {
        "disclaimer": "이 콘텐츠는 테스트용이며 법률 자문이 아닙니다."
    },
}


def generate(case: Dict[str, Any], safe_test_mode: bool = False, planning_info: Optional[Dict[str, Any]] = None) -> Optional[Dict[str, Any]]:
    """
    기본적으로 writer.generate_content를 호출하지만,
    safe_test_mode=True일 때는 금지어 없는 안전한 테스트용 콘텐츠를 반환합니다.
    """
    enriched = dict(case)
    if planning_info:
        enriched.update(planning_info)
    if safe_test_mode:
        # deepcopy 없이도 상수 수정만 안 하면 괜찮지만 방어적으로 복사
        import copy
        content = copy.deepcopy(SAFE_TEST_TEXT)
        # slug를 DB 값과 동기화할 수 있도록 비워둠/혹은 덮어씀
        if case.get("slug"):
            content["page_meta"]["slug"] = case["slug"]
        return content

    # 모델 지정: config의 openai_model_writer를 케이스 dict에 힌트로 포함
    enriched["openai_model"] = getattr(Config, "WRITER_MODEL", None)
    return writer.generate_content(enriched)


def refine_draft(case: Dict[str, Any], feedback: str, safe_test_mode: bool = False, planning_info: Optional[Dict[str, Any]] = None) -> Optional[Dict[str, Any]]:
    """
    기존 draft와 feedback을 전달해 재작성.
    writer.generate_content가 feedback을 직접 쓰지 않더라도
    case dict에 feedback/previous_draft를 넣어 힌트를 제공한다.
    """
    enriched_case = dict(case)
    enriched_case["feedback"] = feedback
    # previous_draft는 호출 측에서 전달하는 텍스트 요약이라고 가정
    if "previous_draft" not in enriched_case and "draft_summary" in enriched_case:
        enriched_case["previous_draft"] = enriched_case.get("draft_summary")
    if planning_info:
        enriched_case.update(planning_info)
    return generate(enriched_case, safe_test_mode=safe_test_mode)

