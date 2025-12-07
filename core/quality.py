"""
core.quality

간단한 유사도 측정(TF 기반 코사인)과 고유 블록 카운트.
"""

from __future__ import annotations

import math
import re
from collections import Counter
from pathlib import Path
from typing import Any, Dict, List, Optional

from core import db


def _tokenize(text: str) -> List[str]:
    return [t for t in re.split(r"\W+", text.lower()) if t]


def _cosine(a: Counter, b: Counter) -> float:
    if not a or not b:
        return 0.0
    dot = sum(a[k] * b.get(k, 0) for k in a)
    na = math.sqrt(sum(v * v for v in a.values()))
    nb = math.sqrt(sum(v * v for v in b.values()))
    if na == 0 or nb == 0:
        return 0.0
    return dot / (na * nb)


def _load_text_by_slug(slug: str) -> str:
    path = Path("public") / f"{slug}.html"
    if not path.exists():
        return ""
    try:
        text = path.read_text(encoding="utf-8")
        text = re.sub(r"<[^>]+>", " ", text)
        return text
    except Exception:
        return ""


def compute_similarity_against_recent(draft_text: str, limit: int = 100) -> float:
    slugs = db.list_published_slugs(limit=limit)
    draft_vec = Counter(_tokenize(draft_text))
    max_sim = 0.0
    for slug in slugs:
        txt = _load_text_by_slug(slug)
        if not txt:
            continue
        vec = Counter(_tokenize(txt))
        sim = _cosine(draft_vec, vec)
        if sim > max_sim:
            max_sim = sim
    return max_sim


def compute_similarity_to_existing(content_text: str, limit: int = 100) -> float:
    """최근 published 문서와의 최대 유사도."""
    return compute_similarity_against_recent(content_text, limit=limit)


def compute_uniqueness_score(max_similarity: float) -> float:
    return 1.0 - max(0.0, min(1.0, max_similarity))


def count_unique_blocks(content_text: str, planning_info: Optional[Dict[str, Any]]) -> int:
    """
    문단 단위로 분할하고, planning_info 관련 키워드가 포함된 문단 수를 센다.
    """
    if planning_info is None:
        planning_info = {}
    keywords = []
    for key in ["main_keyword", "unique_data_point", "legal_strategy", "relationship", "user_intent", "structure_type"]:
        val = planning_info.get(key)
        if val:
            keywords.append(str(val))
    # amount_band는 seed에서만 있었지만 있을 경우 대비
    if planning_info.get("amount_band"):
        keywords.append(str(planning_info.get("amount_band")))
    # case keywords 문자열도 활용
    if planning_info.get("keywords"):
        keywords.extend(str(planning_info.get("keywords")).split(","))

    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", content_text) if p.strip()]
    count = 0
    lowered_keys = [k.lower().strip() for k in keywords if k]
    for p in paragraphs:
        lp = p.lower()
        if any(k in lp for k in lowered_keys):
            count += 1
    return count


def compute_pui_score(content_text: str, planning_info: Optional[Dict[str, Any]], safety_result: Optional[Dict[str, Any]]) -> Dict[str, int]:
    """
    PUI 점수(구조/데이터/EEAT 합산)를 반환한다.
    간단한 휴리스틱 기반.
    """
    planning_info = planning_info or {}
    structure_score = 0
    data_score = 0
    eeat_score = 0

    intent = (planning_info.get("user_intent") or "").lower()
    structure = (planning_info.get("structure_type") or "").lower()
    text_lower = content_text.lower()

    # 구조 점수 (0~40)
    if intent == "계산" and "tl;dr" in text_lower:
        structure_score += 10
    if intent == "행동유도" and ("단계" in text_lower or "1." in text_lower or "2." in text_lower):
        structure_score += 10
    if intent == "정보탐색" and ("사례" in text_lower or "스토리" in text_lower):
        structure_score += 8
    if structure == "type_a" and ("요약" in text_lower or "tl;dr" in text_lower):
        structure_score += 6
    if structure == "type_b" and ("사례" in text_lower or "스토리" in text_lower):
        structure_score += 6
    if structure == "type_c" and ("faq" in text_lower or "체크리스트" in text_lower):
        structure_score += 6
    structure_score = min(structure_score, 40)

    # 데이터 점수 (0~35)
    numbers = re.findall(r"\d[\d,\.]*", content_text)
    data_score += min(len(numbers) * 2, 15)
    unique_point = planning_info.get("unique_data_point") or ""
    legal_strategy = planning_info.get("legal_strategy") or ""
    if unique_point and unique_point.lower() in text_lower:
        data_score += 8
    if legal_strategy and legal_strategy.lower() in text_lower:
        data_score += 6
    if "%" in content_text or "이자" in text_lower:
        data_score += 4
    data_score = min(data_score, 35)

    # EEAT 점수 (0~25)
    if "법률 자문이 아닙니다" in content_text or "법률 자문이 아닙니다".lower() in text_lower:
        eeat_score += 6
    if "전문가와 상의" in content_text or "전문가와 상담" in content_text:
        eeat_score += 6
    if safety_result and safety_result.get("status") == "PASS":
        eeat_score += 6
    if "무조건" not in text_lower and "100%" not in text_lower and "승소" not in text_lower:
        eeat_score += 4
    eeat_score = min(eeat_score, 25)

    total = min(100, structure_score + data_score + eeat_score)
    return {
        "total": int(total),
        "structure_score": int(structure_score),
        "data_score": int(data_score),
        "eeat_score": int(eeat_score),
    }

