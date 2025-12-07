"""
core.renderer_client

renderer.generate_and_save_landing 래퍼.
"""

from __future__ import annotations

from typing import Any, Dict

import renderer


def render_and_save(content: Dict[str, Any]) -> None:
    renderer.generate_and_save_landing(content)

