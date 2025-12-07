"""
config.py

환경 변수 및 .env 로드 설정을 담당합니다.
로컬에서는 .env(또는 .env.local)를 읽고, 서버에서는 환경변수만으로도 동작합니다.
필수: OPENAI_API_KEY (없으면 ValueError)
선택: OPENAI_MODEL_WRITER (기본값: "gpt-5-mini")
"""

from __future__ import annotations

import os
from typing import Optional

from dotenv import load_dotenv

# .env, .env.local 등을 자동 로드 (존재하지 않아도 조용히 통과)
load_dotenv()


class Config:
    """환경 변수 기반 설정."""

    API_KEY: str
    WRITER_MODEL: str

    # 초기화
    API_KEY = os.getenv("OPENAI_API_KEY") or ""
    if not API_KEY:
        raise ValueError("필수 환경변수 OPENAI_API_KEY가 설정되어 있지 않습니다.")

    WRITER_MODEL = os.getenv("OPENAI_MODEL_WRITER", "gpt-5-mini")

