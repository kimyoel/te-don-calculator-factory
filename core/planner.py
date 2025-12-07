"""
core.planner

Seed CSV 기반으로 새로운 todo 케이스를 설계하는 모듈.
"""

from __future__ import annotations

import csv
import random
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import json
from core import db
from config import Config

SEED_PATH = Path("data_seeds") / "debt_cases_30.csv"
CONFIG_PATH = Path("config.json")
DEFAULT_MAX_PER_BAND = 100


@dataclass
class SeedCase:
    case_id: str
    slug_base: str
    title_h1: str
    user_type: str
    relation: str
    amount_band: str
    situation_summary: str
    evidence_type: str


@dataclass
class PlannedCase:
    case_id: str
    slug: str
    main_keyword: str
    user_intent: str
    relationship: str
    situation_summary: str
    legal_strategy: str
    structure_type: str
    unique_data_point: str
    # DB 매핑용 필드
    title: str
    h1: str
    target_user: str
    pain_summary: str
    intro_copy: str
    keywords: str
    category: str
    status: str = "todo"
    batch_date: str = ""


def load_seed_cases() -> List[SeedCase]:
    seeds: List[SeedCase] = []
    if not SEED_PATH.exists():
        return seeds
    with SEED_PATH.open("r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            seeds.append(
                SeedCase(
                    case_id=row.get("case_id", "").strip(),
                    slug_base=row.get("slug_base", "").strip(),
                    title_h1=row.get("title_h1", "").strip(),
                    user_type=row.get("user_type", "").strip(),
                    relation=row.get("relation", "").strip(),
                    amount_band=row.get("amount_band", "").strip(),
                    situation_summary=row.get("situation_summary", "").strip(),
                    evidence_type=row.get("evidence_type", "").strip(),
                )
            )
    return seeds


def _short_uuid(n: int = 8) -> str:
    return uuid.uuid4().hex[:n]


def _pick_intent(seed: SeedCase) -> str:
    # 단순 규칙: 금액대/관계로 intent 결정
    if "100만 미만" in seed.amount_band:
        return "정보탐색"
    if "2000만" in seed.amount_band or "2000만 이상" in seed.amount_band:
        return "행동유도"
    return "계산"


def _pick_relationship(seed: SeedCase) -> str:
    if "가족" in seed.relation or "친구" in seed.relation or "지인" in seed.relation:
        return "가족/지인"
    if "B2B" in seed.case_id or "업체" in seed.user_type or "사업" in seed.user_type or "법인" in seed.user_type:
        return "B2B"
    if "강사" in seed.user_type or "근로자" in seed.user_type:
        return "B2C"
    return "C2C"


def _pick_strategy(seed: SeedCase) -> str:
    rel = _pick_relationship(seed)
    if rel == "B2B":
        if "하도급" in seed.situation_summary or "건설" in seed.user_type:
            return "지급명령"
        return "가압류"
    if "사기" in seed.situation_summary or "사기" in seed.case_id:
        return "형사고소"
    if "플랫폼" in seed.user_type or "정산" in seed.situation_summary:
        return "공정위신고"
    if "소액" in seed.amount_band or "100만" in seed.amount_band:
        return "소액심판"
    return "지급명령"


def _pick_structure(seed: SeedCase, intent: str) -> str:
    # intent/relationship 기반 레이아웃 타입 선택
    rel = _pick_relationship(seed)
    if intent == "행동유도":
        return "TYPE_A"
    if rel in ("가족/지인",):
        return "TYPE_C"
    return "TYPE_B"


def _build_planned_case(seed: SeedCase, domain: str) -> PlannedCase:
    main_keyword = seed.title_h1 or seed.situation_summary
    user_intent = _pick_intent(seed)
    relationship = _pick_relationship(seed)
    legal_strategy = _pick_strategy(seed)
    structure_type = _pick_structure(seed, user_intent)
    unique_data_point = seed.evidence_type or seed.amount_band

    case_id = f"DEBT-{_short_uuid(6).upper()}"
    slug = f"auto-미수금-{_short_uuid(8)}"

    keywords = ", ".join(
        [k for k in [main_keyword, seed.user_type, seed.relation, seed.amount_band, legal_strategy] if k]
    )
    intro_copy = f"{seed.situation_summary} / 전략: {legal_strategy} / 포인트: {unique_data_point}"

    return PlannedCase(
        case_id=case_id,
        slug=slug,
        main_keyword=main_keyword,
        user_intent=user_intent,
        relationship=relationship,
        situation_summary=seed.situation_summary,
        legal_strategy=legal_strategy,
        structure_type=structure_type,
        unique_data_point=unique_data_point,
        title=main_keyword,
        h1=main_keyword,
        target_user=seed.user_type or seed.relation,
        pain_summary=seed.situation_summary,
        intro_copy=intro_copy,
        keywords=keywords,
        category=domain,
    )


def suggest_new_cases(domain: str = "debt", limit: int = 5) -> List[Dict[str, Any]]:
    seeds = load_seed_cases()
    if not seeds:
        return []

    # 설정 로드
    try:
        max_per_band = int(Config.MAX_CASES_PER_STRATEGY_BAND)  # type: ignore[attr-defined]
    except Exception:
        max_per_band = DEFAULT_MAX_PER_BAND

    raw_counts = db.count_cases_by_strategy_and_amount()
    band_counts: Dict[Tuple[str, str], int] = {}
    for (ls, ab, st), cnt in raw_counts.items():
        key = (ls, ab)
        band_counts[key] = band_counts.get(key, 0) + cnt
    existing_slugs = set(db.get_all_slugs())
    results: List[Dict[str, Any]] = []

    while len(results) < limit:
        seed = random.choice(seeds)
        planned = _build_planned_case(seed, domain)
        if planned.slug in existing_slugs or any(r["slug"] == planned.slug for r in results):
            continue
        band_key = (planned.legal_strategy, seed.amount_band or "")
        current_cnt = band_counts.get(band_key, 0) + sum(
            1
            for r in results
            if r.get("legal_strategy") == planned.legal_strategy and (seed.amount_band or "") == seed.amount_band
        )
        if current_cnt >= max_per_band:
            continue

        band_counts[band_key] = band_counts.get(band_key, 0) + 1
        results.append(planned.__dict__)
    return results


if __name__ == "__main__":
    import json

    sample = suggest_new_cases(limit=5)
    print(json.dumps(sample, ensure_ascii=False, indent=2))
    print("현재 전략/금액대별 누적:", db.count_cases_by_strategy_and_amount())

