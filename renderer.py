"""
renderer.py

템플릿 HTML에 콘텐츠 딕셔너리를 주입해 pSEO 랜딩 페이지를 생성합니다.
OpenAI 호출은 포함하지 않으며, 파일 입출력은 템플릿 로드/결과 저장만 수행합니다.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict

TEMPLATE_PATH = Path("public") / "template_landing.html"
TEMPLATE_TYPE_A = Path("public") / "template_type_a.html"
TEMPLATE_TYPE_B = Path("public") / "template_type_b.html"
TEMPLATE_TYPE_C = Path("public") / "template_type_c.html"
OUTPUT_DIR = Path("public")


def load_template(path: Path) -> str:
    """템플릿 파일을 읽어 문자열로 반환합니다."""
    return path.read_text(encoding="utf-8")


DEFAULT_DISCLAIMER = "이 콘텐츠는 일반 정보 제공용 예시이며, 법률 자문이 아닙니다. 실제 분쟁 대응은 법률 전문가와 상담하세요."


def _build_replacements(content: Dict[str, Any]) -> Dict[str, str]:
    """콘텐츠 딕셔너리에서 템플릿 치환용 맵을 생성합니다."""
    page_meta = content.get("page_meta", {}) or {}
    hero = content.get("hero_section", {}) or {}
    situation = content.get("situation_analysis", {}) or {}
    action = content.get("action_guide", {}) or {}
    faq_list = content.get("faq_section", []) or []
    legal = content.get("legal_safety", {}) or {}

    # FAQ 최대 3개까지만 기본 매핑
    faq_map: Dict[str, str] = {}
    for idx in range(3):
        q_key = f"FAQ{idx+1}_Q"
        a_key = f"FAQ{idx+1}_A"
        if idx < len(faq_list):
            faq_map[q_key] = faq_list[idx].get("question", "")
            faq_map[a_key] = faq_list[idx].get("answer", "")
        else:
            faq_map[q_key] = ""
            faq_map[a_key] = ""

    replacements = {
        "TITLE": page_meta.get("title", ""),
        "DESCRIPTION": page_meta.get("description", ""),
        "KEYWORDS": page_meta.get("keywords", ""),
        "H1": hero.get("headline", ""),
        "INTRO": hero.get("intro_copy", ""),
        "PAIN_POINT": situation.get("pain_summary", ""),
        "ACTION_STEPS": action.get("guidance", ""),
        "LEGAL_DISCLAIMER": legal.get("disclaimer", "") or DEFAULT_DISCLAIMER,
        **faq_map,
    }
    return replacements


def render_landing_html(template_html: str, content: Dict[str, Any]) -> str:
    """
    템플릿 문자열과 콘텐츠 딕셔너리를 받아 플레이스홀더를 치환한 HTML을 반환합니다.
    순수 문자열 처리만 수행합니다.
    """
    replacements = _build_replacements(content)
    rendered = template_html
    for key, value in replacements.items():
        rendered = rendered.replace(f"{{{{{key}}}}}", value)
    return rendered


def save_landing_html(slug: str, html: str) -> None:
    """렌더링된 HTML을 public/{slug}.html에 저장합니다."""
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    out_path = OUTPUT_DIR / f"{slug}.html"
    out_path.write_text(html, encoding="utf-8")


def generate_and_save_landing(content: Dict[str, Any]) -> None:
    """
    content["page_meta"]["slug"]를 사용해 템플릿을 렌더링 후 저장합니다.
    """
    slug = (content.get("page_meta") or {}).get("slug")
    if not slug:
        raise ValueError("content.page_meta.slug 가 필요합니다.")

    # 구조 타입별 템플릿 선택
    structure_type = content.get("structure_type") or (content.get("page_meta") or {}).get("structure_type")
    template_path = TEMPLATE_PATH
    if structure_type == "TYPE_A":
        template_path = TEMPLATE_TYPE_A
    elif structure_type == "TYPE_B":
        template_path = TEMPLATE_TYPE_B
    elif structure_type == "TYPE_C":
        template_path = TEMPLATE_TYPE_C

    template_html = load_template(template_path)
    final_html = render_landing_html(template_html, content)
    save_landing_html(slug, final_html)

