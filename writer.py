"""
writer.py

OpenAI Chat Completions 기반으로 pSEO 랜딩 페이지 JSON 콘텐츠를 생성하는 모듈.
I/O는 하지 않고, 입력 dict → 출력 dict만 담당한다.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Dict, List

from openai import OpenAI

from config import Config

# docs/content_guidelines.md 핵심 규칙 요약을 system 프롬프트에 넣습니다.
# (주의: 실제 규칙은 docs/content_guidelines.md를 확인해 최신 내용으로 업데이트해야 합니다.)
SYSTEM_PROMPT = """
당신은 '떼인 돈 계산기' pSEO 랜딩 콘텐츠를 생성하는 시니어 에디터입니다.
반드시 docs/content_guidelines.md에 정의된 JSON 스키마와 작성 규칙을 따르세요.

핵심 컴플라이언스 (한국어):
- 이 콘텐츠는 법률 자문이 아님을 명시.
- 승소/회수/결과를 보장하거나 확정적으로 단정하는 표현 금지.
- 법률 전문가 상담을 권유하는 문구 포함.
- 100% 회수, 무조건 승소, 보장 등의 표현 금지.
- JSON 한 개 객체만 반환, 필수 필드 누락 금지, 불필요 필드 추가 금지.
- 톤: 직관적·간결, 보수적이고 신중한 표현.

전개 규칙 (시작 금지/구조 다양화):
- "미수금이란?" 같은 정의로 시작하지 말 것. 사용자 상황/핵심 경고/결론부터 시작.
- user_intent/structure_type에 따라 전개를 달리한다:
  * intent=계산: 상단에 계산/지연이자 등 핵심 숫자 → 이후 절차 설명.
  * intent=행동유도: 지금 당장 할 1·2·3 단계 리스트 제시.
  * intent=정보탐색: 상황 설명 → 법적 쟁점 → 절차/주의점 순서.
  * structure_type=TYPE_A: TL;DR 한 줄 요약 → 중요한 숫자/결과 → 상세 설명.
  * structure_type=TYPE_B: 실제 유사 사례 스토리로 시작 → 판례/쟁점 정리.
  * structure_type=TYPE_C: FAQ + 체크리스트 위주 구성.
- relationship에 따라 어조:
  * B2B: 감정 최소화, 계약/세금계산서/하도급법 중심의 냉철한 톤.
  * C2C/가족/지인: 공감 한두 문단 후 법적 현실 설명.
- CTA:
  * 금액이 작으면 셀프 지급명령/소액심판 등 자조적 행동 제안.
  * 금액이 크거나 복잡하면 전문가 상담 필요 톤으로 마무리.
"""


def _build_messages(case: Dict[str, Any]) -> List[Dict[str, str]]:
    """케이스 정보를 기반으로 Chat Completions 메시지 배열을 생성한다."""
    # 필수 입력이 누락되더라도 모델이 최대한 보완하도록 user 메시지에 모두 전달.
    feedback = case.get("feedback", "")
    prev_draft = case.get("previous_draft", "")
    intent = case.get("user_intent", "")
    structure_type = case.get("structure_type", "")
    relationship = case.get("relationship", "")
    legal_strategy = case.get("legal_strategy", "")
    unique_point = case.get("unique_data_point", "")
    main_keyword = case.get("main_keyword", "")
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
            f"이전 초안 요약(있다면): {prev_draft}\n"
            f"개선해야 할 피드백(있다면): {feedback}\n"
            f"user_intent: {intent}\n"
            f"structure_type: {structure_type}\n"
            f"relationship: {relationship}\n"
            f"legal_strategy: {legal_strategy}\n"
            f"unique_data_point: {unique_point}\n"
            f"main_keyword: {main_keyword}\n"
            "위 의도/구조/어조/CTA 지침을 반영해, JSON 스키마 필드를 채워주세요."
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
    try:
        api_key = Config.API_KEY
        model = case.get("openai_model") or Config.WRITER_MODEL
    except ValueError as exc:
        logging.error(str(exc))
        return None

    client = OpenAI(api_key=api_key)

    try:
        messages = _build_messages(case)
        response = client.chat.completions.create(
            model=model,
            messages=messages,
            response_format={"type": "json_object"},
        )
        content = response.choices[0].message.content
        return json.loads(content)
    except Exception as exc:  # noqa: BLE001
        logging.exception("콘텐츠 생성 중 오류가 발생했습니다: %s", exc)
        return None

