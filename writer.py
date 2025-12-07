"""
writer.py

OpenAI Chat Completions 기반으로 pSEO 랜딩 페이지 JSON 콘텐츠를 생성하는 모듈.
I/O는 하지 않고, 입력 dict → 출력 dict만 담당한다.
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any, Dict, List

from openai import OpenAI

# 기본 모델은 환경변수 OPENAI_MODEL로 오버라이드 가능하며, 기본값은 gpt-5-mini입니다.
MODEL = os.getenv("OPENAI_MODEL", "gpt-5-mini")

# docs/content_guidelines.md 핵심 규칙 요약을 system 프롬프트에 넣습니다.
# (주의: 실제 규칙은 docs/content_guidelines.md를 확인해 최신 내용으로 업데이트해야 합니다.)
SYSTEM_PROMPT = """
당신은 '떼인 돈 계산기' pSEO 랜딩 콘텐츠를 생성하는 도우미입니다.
반드시 docs/content_guidelines.md에 정의된 JSON 스키마와 작성 규칙을 따르세요.
- 출력은 오직 JSON 한 개 객체만 반환합니다.
- 스키마 필수 필드를 빠뜨리지 말고, 불필요한 필드는 추가하지 마세요.
- 톤앤매너: 한국어, 직관적이고 간결한 안내, 법률 자문 아님을 명시.
- 법률 컴플라이언스: 확정적 승소/보상 보장은 금지, 전문 상담을 권고.
- 키워드/카테고리/FAQ는 입력 케이스 정보를 반영하고, 중복 없이 자연스럽게 작성.
"""


def _build_messages(case: Dict[str, Any]) -> List[Dict[str, str]]:
    """케이스 정보를 기반으로 Chat Completions 메시지 배열을 생성한다."""
    # 필수 입력이 누락되더라도 모델이 최대한 보완하도록 user 메시지에 모두 전달.
    user_prompt = {
        "role": "user",
        "content": (
            "아래 케이스 정보를 활용해 docs/content_guidelines.md의 JSON 스키마에 맞는 "
            "랜딩 페이지 콘텐츠를 JSON으로만 생성해 주세요.\n\n"
            "규칙:\n"
            "- 출력은 반드시 JSON 한 개 객체로만 반환 (추가 텍스트 금지)\n"
            "- 스키마 필수 필드 포함, 선택 필드는 가능하면 채우기\n"
            "- 법률 자문 아님을 명시하고, 단정적 승소 표현 금지\n\n"
            f"case_id: {case.get('case_id', '')}\n"
            f"slug: {case.get('slug', '')}\n"
            f"category: {case.get('category', '')}\n"
            f"summary: {case.get('summary', '')}\n"
            f"target_user: {case.get('target_user', '')}\n"
            f"pain_points: {case.get('pain_points', '')}\n"
            f"keywords: {case.get('keywords', '')}\n"
            "핵심 키워드와 pain_points를 자연스럽게 녹여서 JSON 스키마의 필드를 채워주세요."
        ),
    }

    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        user_prompt,
    ]


def generate_content(case: Dict[str, Any]) -> Dict[str, Any] | None:
    """
    OpenAI Chat Completions를 호출해 스키마에 맞는 콘텐츠 JSON을 반환한다.
    오류 시 예외를 던지지 않고 로그 후 None을 반환한다.
    """
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        logging.error("OPENAI_API_KEY가 설정되어 있지 않습니다.")
        return None

    client = OpenAI(api_key=api_key)

    try:
        messages = _build_messages(case)
        response = client.chat.completions.create(
            model=MODEL,
            messages=messages,
            response_format={"type": "json_object"},
        )
        content = response.choices[0].message.content
        return json.loads(content)
    except Exception as exc:  # noqa: BLE001
        logging.exception("콘텐츠 생성 중 오류가 발생했습니다: %s", exc)
        return None

