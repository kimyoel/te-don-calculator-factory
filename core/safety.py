"""
core.safety

PASS / EDIT / DISCARD 등급 기반 안전성 평가.
"""

from __future__ import annotations

import json
import logging
from typing import Dict, List, Optional

from openai import OpenAI

from config import Config

RED_FLAGS = [
    "100% 회수",
    "무조건 승소",
    "보장합니다",
    "전문 변호사",
    "대리해 드립니다",
    "책임집니다",
]

SOFT_FLAGS = [
    "승소 가능성이 높습니다",
    "확실히 받을 수 있습니다",
    "법률 자문",
    "법률 상담",
    "보장된 결과",
    "반드시",
    "절대",
    "무조건",
]

DEFAULT_SOFT_MODEL = "gpt-4.1-mini"


def _llm_soft_check(text: str) -> Optional[Dict[str, object]]:
    try:
        api_key = Config.API_KEY
        model = getattr(Config, "SAFETY_MODEL", None) or getattr(Config, "OPENAI_MODEL_SAFETY", None) or getattr(Config, "WRITER_MODEL", DEFAULT_SOFT_MODEL) or DEFAULT_SOFT_MODEL
    except Exception as exc:  # noqa: BLE001
        logging.warning("audit_soft: config error, skip soft audit: %s", exc)
        return None

    client = OpenAI(api_key=api_key)
    prompt = (
        "다음 한국어 텍스트가 법률 자문처럼 들리거나, 승소/회수 보장을 암시하는지 평가해주세요.\n"
        "- 위험하면 status='EDIT' 또는 'DISCARD'로 제안하고, 짧은 수정 피드백 또는 순화된 문장 예시를 제시.\n"
        "- 안전하면 status='PASS'.\n"
        "- JSON만 반환: {\"status\": \"PASS|EDIT|DISCARD\", \"reason\": \"...\", \"refined_content\": \"...\"}\n\n"
        f"텍스트:\n{text}\n"
    )
    try:
        resp = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": "너는 한국어 컴플라이언스 검수자다. JSON만 반환하라."},
                {"role": "user", "content": prompt},
            ],
            response_format={"type": "json_object"},
        )
        content = resp.choices[0].message.content or "{}"
        return json.loads(content)
    except Exception as exc:  # noqa: BLE001
        logging.warning("audit_soft: LLM error, skip soft audit: %s", exc)
        return None


def review_content(text: str) -> Dict[str, object]:
    """
    콘텐츠 안전성을 PASS / EDIT / DISCARD 중 하나로 분류.
    반환 예:
    {
      "status": "PASS" | "EDIT" | "DISCARD",
      "risk_score": int (0~100),
      "reason": str,
      "refined_content": str | None
    }
    """
    # 1) 하드 필터
    lower = text.lower()
    hard_hits = [flag for flag in RED_FLAGS if flag.lower() in lower]
    if hard_hits:
        return {
            "status": "DISCARD",
            "risk_score": 90,
            "reason": "하드 금지어 감지: " + ", ".join(hard_hits),
            "refined_content": None,
        }

    # 2) 휴리스틱 소프트 체크
    soft_hits = [flag for flag in SOFT_FLAGS if flag.lower() in lower]
    if soft_hits:
        return {
            "status": "EDIT",
            "risk_score": 60,
            "reason": "단정/보장 어투 감지: " + ", ".join(soft_hits),
            "refined_content": None,
        }

    # 3) LLM 소프트 체크 (best effort)
    llm_result = _llm_soft_check(text)
    if llm_result:
        st = llm_result.get("status", "PASS")
        reason = llm_result.get("reason", "")
        refined = llm_result.get("refined_content")
        if st == "DISCARD":
            return {"status": "DISCARD", "risk_score": 85, "reason": reason, "refined_content": refined}
        if st == "EDIT":
            return {"status": "EDIT", "risk_score": 55, "reason": reason, "refined_content": refined}
        return {"status": "PASS", "risk_score": 5, "reason": reason or "LLM pass", "refined_content": None}

    # 4) LLM 실패 시 PASS로 관대 처리
    return {"status": "PASS", "risk_score": 5, "reason": "soft check skipped", "refined_content": None}

