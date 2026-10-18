"""结果查询共享依赖与查询参数解析"""

from __future__ import annotations

import json
import math

from fastapi import APIRouter, HTTPException

from src.api.dependencies import (
    get_db_session,
    resolve_run_id,
)
from src.api.dependencies import (
    require_readable_run_status as _require_readable_run_status,
)
from src.api.dependencies import (
    require_run_for_novel as _require_run_for_novel,
)

__all__ = [
    "_parse_emotion_trend_range",
    "_require_readable_run_status",
    "_require_run_for_novel",
    "get_db_session",
    "resolve_run_id",
    "router",
]

# tags 由主模块 router（tags=["results"]）在 include 时统一附加，避免标签重复
router = APIRouter()


def _parse_emotion_trend_range(
    position_range: str | None,
) -> tuple[float, float] | None:
    """解析情绪趋势 position 区间并统一校验输入"""
    if position_range is None:
        return None
    raw = position_range.strip()
    try:
        values = json.loads(raw) if raw.startswith("[") else [part.strip() for part in raw.split(",")]
        if not isinstance(values, list) or len(values) != 2:
            raise ValueError
        start, end = float(values[0]), float(values[1])
    except (TypeError, ValueError, json.JSONDecodeError) as exc:
        raise HTTPException(
            status_code=422,
            detail="range 格式必须为 start,end 或 [start,end]",
        ) from exc

    if not all(math.isfinite(value) and 0 <= value <= 1 for value in (start, end)):
        raise HTTPException(status_code=422, detail="range 的 position 必须位于 0~1")
    if start >= end:
        raise HTTPException(status_code=422, detail="range 起点必须小于终点")
    return start, end
