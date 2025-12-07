"""
planner_generate_cases.py

매일 새로운 pSEO 케이스를 자동 기획하여 data/cases.csv에 status="todo" 행으로 추가합니다.
동작:
 1) 기존 cases.csv를 읽어 중복(slug, case_id, keywords, category) 정보를 수집
 2) OpenAI 계획용 모델로 신규 케이스 후보 JSON 리스트(최대 10개)를 생성
 3) 중복을 피하고 필드를 채워 data/cases.csv에 추가 (status="todo", batch_date="")
"""

from __future__ import annotations

import csv
import json
import logging
import os
from pathlib import Path
from typing import Dict, List, Set

from openai import OpenAI

CASES_PATH = Path("data") / "cases.csv"
MAX_NEW_CASES = 10
PLANNER_MODEL = os.getenv("OPENAI_MODEL_PLANNER", "gpt-5.1")


def get_existing_cases() -> Dict[str, Set[str]]:
    """cases.csv를 읽어 중복 체크용 집합을 반환한다."""
    existing = {
        "case_id": set(),
        "slug": set(),
        "keywords": set(),
        "category": set(),
        "rows": [],
        "fieldnames": [],
    }
    if not CASES_PATH.exists():
        return existing

    with CASES_PATH.open("r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        existing["fieldnames"] = reader.fieldnames or []
        for row in reader:
            existing["rows"].append(row)
            existing["case_id"].add((row.get("case_id") or "").strip())
            existing["slug"].add((row.get("slug") or "").strip())
            existing["keywords"].add((row.get("keywords") or "").strip())
            existing["category"].add((row.get("category") or "").strip())
    return existing


def _build_planner_prompt(existing: Dict[str, Set[str]]) -> List[Dict[str, str]]:
    """OpenAI로 새 케이스를 기획하도록 프롬프트를 구성한다."""
    existing_slugs = list(existing.get("slug", []))
    existing_ids = list(existing.get("case_id", []))
    existing_keywords = list(existing.get("keywords", []))
    existing_categories = list(existing.get("category", []))

    system_msg = {
        "role": "system",
        "content": (
            "너는 '떼인 돈 계산기' pSEO 랜딩을 기획하는 어시스턴트야. "
            "아래 JSON 스키마를 따르는 새 케이스 최대 10개를 만들어. "
            "중복 slug/case_id/keywords를 피하고, 법률 자문을 보장하지 않는 톤으로 작성해."
        ),
    }
    user_msg = {
        "role": "user",
        "content": (
            "기존 케이스들:\n"
            f"- case_id: {existing_ids}\n"
            f"- slug: {existing_slugs}\n"
            f"- keywords: {existing_keywords}\n"
            f"- category: {existing_categories}\n\n"
            "새 케이스 10개 이하를 JSON 리스트로 반환해. "
            "필드: case_id, slug, category, title, h1, target_user, pain_summary, intro_copy, "
            "keywords, faq1_q, faq1_a, faq2_q, faq2_a, faq3_q, faq3_a. "
            "중복이나 유사 키워드는 피하고, slug는 URL-safe 소문자-하이픈 형식으로. "
            "반드시 JSON만 반환해."
        ),
    }
    return [system_msg, user_msg]


def plan_new_cases(existing: Dict[str, Set[str]]) -> List[Dict[str, str]]:
    """OpenAI를 호출해 신규 케이스를 계획한다."""
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        logging.error("OPENAI_API_KEY가 설정되어 있지 않습니다.")
        return []

    client = OpenAI(api_key=api_key)
    try:
        messages = _build_planner_prompt(existing)
        resp = client.chat.completions.create(
            model=PLANNER_MODEL,
            messages=messages,
            response_format={"type": "json_object"},
        )
        content = resp.choices[0].message.content
        data = json.loads(content)
        if isinstance(data, dict) and "cases" in data:
            data = data["cases"]
        if not isinstance(data, list):
            logging.error("모델 응답이 리스트가 아닙니다.")
            return []
        return data[:MAX_NEW_CASES]
    except Exception as exc:  # noqa: BLE001
        logging.exception("케이스 기획 호출 실패: %s", exc)
        return []


def _ensure_fieldnames(fieldnames: List[str]) -> List[str]:
    """필수 필드(status, batch_date)를 포함하도록 필드명을 보강한다."""
    required = [
        "case_id",
        "slug",
        "title",
        "h1",
        "target_user",
        "pain_summary",
        "intro_copy",
        "keywords",
        "faq1_q",
        "faq1_a",
        "faq2_q",
        "faq2_a",
        "faq3_q",
        "faq3_a",
        "status",
        "batch_date",
    ]
    merged = list(dict.fromkeys(fieldnames + required))
    return merged


def append_cases_to_csv(existing: Dict[str, Set[str]], new_cases: List[Dict[str, str]]) -> None:
    """신규 케이스를 기존 rows와 함께 다시 저장한다."""
    rows = existing.get("rows", [])
    fieldnames = _ensure_fieldnames(existing.get("fieldnames", []))

    for case in new_cases:
        row = {k: "" for k in fieldnames}
        for key in row.keys():
            if key in case:
                row[key] = case[key]
        row["status"] = "todo"
        row["batch_date"] = ""
        rows.append(row)

    with CASES_PATH.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    existing = get_existing_cases()
    new_cases = plan_new_cases(existing)

    if not new_cases:
        logging.info("추가할 케이스 없음.")
        return

    append_cases_to_csv(existing, new_cases)
    logging.info("신규 케이스 %d건을 추가했습니다.", len(new_cases))


if __name__ == "__main__":
    main()

