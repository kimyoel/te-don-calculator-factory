"""
run_agent.py

간단한 Python 루프 에이전트:
 - MCP 서버(mcp_server.py)를 실행해둔 상태에서, MCP 클라이언트를 통해 툴을 호출
 - 하루 목표량(TARGET_PER_DAY)을 맞출 때까지, 부족분은 planner_suggest_cases + append_cases로 충원
 - run_case_pipeline으로 케이스를 처리해 published를 올린다.

실행 전제:
 - 별도 터미널에서 `python mcp_server.py` 실행 중이어야 함
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List

from fastmcp import Client

SERVER_URL = "http://127.0.0.1:8765/mcp"
DEFAULT_CONFIG_PATH = Path("config.json")
DEFAULTS = {
    "target_per_day": 10,
    "max_refill_loops": 3,
    "domain_type": "debt",
    "openai_model_writer": "gpt-5-mini",
    "openai_model_safety": "gpt-5-mini",
    "similarity_threshold": 0.4,
    "initial_launch_limit": 100,
}


def _unwrap(result) -> Any:
    """CallToolResult나 Pydantic 객체를 파이썬 기본 타입으로 평탄화."""

    def normalize(obj):
        if obj is None:
            return None
        # Pydantic v2 모델 처리
        if hasattr(obj, "model_dump"):
            return normalize(obj.model_dump())
        # Pydantic v1 호환
        if hasattr(obj, "dict"):
            return normalize(obj.dict())
        # Pydantic RootModel(v1) 또는 root 필드 호환
        if hasattr(obj, "__root__"):
            try:
                return normalize(obj.__root__)  # type: ignore[attr-defined]
            except Exception:
                pass
        if hasattr(obj, "root"):
            try:
                return normalize(obj.root)  # type: ignore[attr-defined]
            except Exception:
                pass
        # 일반 객체를 dict로 변환 시도
        if hasattr(obj, "__dict__"):
            return {k: normalize(v) for k, v in obj.__dict__.items()}
        if isinstance(obj, dict):
            return {k: normalize(v) for k, v in obj.items()}
        if isinstance(obj, (list, tuple, set)):
            return [normalize(v) for v in obj]
        return obj

    if result is None:
        return None
    # 1) structured_content에 result 키가 있으면 최우선
    structured = getattr(result, "structured_content", None)
    if structured not in (None, {}, []):
        if isinstance(structured, dict) and "result" in structured:
            return normalize(structured["result"])
        return normalize(structured)
    # 2) CallToolResult.data
    if getattr(result, "data", None) is not None:
        return normalize(result.data)
    # content fallback
    if getattr(result, "content", None) is not None:
        return normalize(result.content)
    return normalize(result)


def count_published_today(client: Client) -> int:
    # 간단히 전체 published를 세는 툴이 없으므로 todo 기반으로만 진행하고,
    # 실제 published 카운트는 파이프라인 결과에 따라 증가시킨다.
    # 초기 published_today는 0으로 시작해 루프 내에서 누적.
    return 0


async def list_todo(client: Client, limit: int) -> List[Dict[str, Any]]:
    res = await client.call_tool("list_todo_cases", {"limit": limit})
    logging.debug("raw list_todo_cases result: %r", res)
    data = _unwrap(res) or []
    if not isinstance(data, list):
        return []
    # dict로 강제 변환 및 필터링
    cleaned: List[Dict[str, Any]] = []
    for item in data:
        if hasattr(item, "model_dump"):
            item = item.model_dump()
        if hasattr(item, "__dict__") and not isinstance(item, dict):
            item = dict(item.__dict__)
        if not isinstance(item, dict):
            continue
        if not item.get("case_id"):
            continue
        cleaned.append(item)
    return cleaned


async def plan_and_append(client: Client, product_type: str, shortage: int, dry_run: bool) -> int:
    ideas = _unwrap(
        await client.call_tool(
            "planner_suggest_cases",
            {
                "product_type": product_type,
                "max_n": shortage * 2 if shortage > 0 else 2,
            },
        )
    )
    if not ideas:
        return 0
    if dry_run:
        logging.info("🧪 DRY-RUN: planner가 %s건 만들었지만 DB에는 안 넣어요.", len(ideas))
        return len(ideas)
    await client.call_tool("append_cases", {"cases": ideas})
    return len(ideas)


async def process_todo(
    client: Client,
    todo: List[Dict[str, Any]],
    needed: int,
    dry_run: bool,
    published_ids: List[str],
    discarded: List[str],
) -> int:
    published = 0
    for row in todo:
        if published >= needed:
            break
        case_id = row.get("case_id") or row.get("id")
        if not case_id:
            continue
        if dry_run:
            logging.info("🧪 DRY-RUN: run_case_pipeline 패스 (%s)", case_id)
            continue
        result = _unwrap(
            await client.call_tool(
                "run_case_pipeline",
                {"case_id": case_id, "max_attempts": 2},
            )
        ) or {}
        status = result.get("status")
        if status == "published":
            published += 1
            published_ids.append(case_id)
            logging.info("✅ 발행 완료: %s -> %s", case_id, result.get("html_path"))
        elif status == "discarded":
            discarded.append(f"{case_id}:{result}")
            logging.info("🧹 폐기됨: %s (%s)", case_id, result)
        else:
            logging.info("ℹ️ 처리 결과: %s (%s)", case_id, result)
    return published


def load_config(path: Path) -> Dict[str, Any]:
    if not path.exists():
        logging.warning("⚠️ config 파일이 없어 기본값을 사용합니다: %s", path)
        return dict(DEFAULTS)
    try:
        with path.open("r", encoding="utf-8") as f:
            data = json.load(f)
        cfg = dict(DEFAULTS)
        cfg.update({k: v for k, v in data.items() if v is not None})
        return cfg
    except Exception as exc:  # noqa: BLE001
        logging.warning("⚠️ config 로드 실패(%s), 기본값 사용: %s", path, exc)
        return dict(DEFAULTS)


def setup_logging(verbose: bool) -> Path:
    Path("logs").mkdir(exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    log_path = Path("logs") / f"run_agent-{ts}.log"
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)s: %(message)s",
        handlers=[
            logging.StreamHandler(),
            logging.FileHandler(log_path, encoding="utf-8"),
        ],
    )
    return log_path


async def main_async(args: argparse.Namespace) -> None:
    log_path = setup_logging(args.verbose)
    cfg = load_config(Path(args.config))
    target_per_day = int(cfg.get("target_per_day", DEFAULTS["target_per_day"]))
    max_refill_loops = int(cfg.get("max_refill_loops", DEFAULTS["max_refill_loops"]))
    domain_type = cfg.get("domain_type", DEFAULTS["domain_type"])
    initial_limit = int(cfg.get("initial_launch_limit", DEFAULTS["initial_launch_limit"]))

    logging.info("🔧 설정 로드: %s", cfg)
    logging.info("🗒 로그 파일: %s", log_path)

    client = Client(SERVER_URL)
    published_ids: List[str] = []
    discarded: List[str] = []
    planned_total = 0

    try:
        async with client:
            try:
                test = await client.call_tool("list_todo_cases", {"limit": 1})
                unwrapped_test = _unwrap(test)
                logging.info("✅ MCP 연결 성공 (%s)", SERVER_URL)
                logging.info("🗂 list_todo_cases 원본 결과: %r", test)
                logging.info("🗂 list_todo_cases 해제 결과: %s", unwrapped_test)
            except Exception as conn_exc:  # noqa: BLE001
                logging.error("❌ MCP 연결 실패 (%s): %s", SERVER_URL, conn_exc)
                return

            # 초기 론칭 안전 모드: 전체 published 수 상한 체크
            from core import db  # 로컬 임포트로 의존 최소화

            total_published = db.count_published_total()
            if initial_limit > 0 and (not args.ignore_initial_limit) and total_published >= initial_limit:
                logging.warning(
                    "⚠️ 초기 발행 상한 도달(%s건). SEO/콘솔 리뷰까지 자동 생산을 멈춥니다.",
                    total_published,
                )
                return

            published_today = count_published_today(client)
            loop_count = 0

            while published_today < target_per_day and loop_count < max_refill_loops:
                needed = target_per_day - published_today
                if needed <= 0:
                    break

                logging.info("🔁 루프 %s: 현재 published=%s, 필요=%s", loop_count + 1, published_today, needed)

                todo = await list_todo(client, limit=needed * 2)
                if len(todo) < needed:
                    shortage = needed - len(todo)
                    logging.info("📋 TODO 부족 %s개 → planner 호출로 보충합니다.", shortage)
                    planned_total += await plan_and_append(
                        client,
                        product_type=domain_type,
                        shortage=shortage,
                        dry_run=args.dry_run,
                    )
                    todo = await list_todo(client, limit=needed * 2)

                gained = await process_todo(
                    client,
                    todo,
                    needed,
                    args.dry_run,
                    published_ids,
                    discarded,
                )
                published_today += gained
                loop_count += 1

            logging.info("📊 요약: published=%s, discarded=%s, planned=%s, dry_run=%s",
                         len(published_ids), len(discarded), planned_total, args.dry_run)
            logging.info("🟢 발행 ID: %s", published_ids)
            logging.info("🧹 폐기 목록: %s", discarded)
            logging.info("🗒 로그 파일: %s", log_path)
    except Exception as exc:  # noqa: BLE001
        logging.error("❌ MCP 클라이언트 예외: %s", exc)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default="config.json", help="설정 파일 경로 (json)")
    parser.add_argument("--dry-run", action="store_true", help="실제 append/publish 없이 로그만 출력")
    parser.add_argument("--verbose", action="store_true", help="디버그 로그 출력")
    parser.add_argument("--ignore-initial-limit", action="store_true", help="initial_launch_limit 무시")
    args = parser.parse_args()
    asyncio.run(main_async(args))

