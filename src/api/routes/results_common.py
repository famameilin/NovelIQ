"""
结果查询共享依赖与公共工具

创建时间: 2026-10-02
创建者: Trae
任务: 大文件拆分（routes/results.py → 同目录资源域子模块）
说明: 从 src/api/routes/results.py 拆出共享 Depends（resolve_run_id/get_db_session/
require_run_for_novel/require_readable_run_status）、pipeline 快照路由与公共工具，
供 results_export/results_paragraphs/results_topics/results_graph/results_metrics 复用；
路由注册顺序由主模块 src/api/routes/results.py 统一编排。
"""

from __future__ import annotations

import json
import math
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

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

# 说明: tags 由主模块 router（tags=["results"]）在 include 时统一附加，避免标签重复
router = APIRouter()


@router.get("/{novel_id}/pipeline", summary="已释放快照与连续性状态")
async def get_pipeline_snapshot(
    novel_id: str,
    run_id: Annotated[str, Depends(resolve_run_id)],
    session: Annotated[Session, Depends(get_db_session)],
) -> dict[str, Any]:
    from src.api.exceptions import AnalysisNotCompleteError
    from src.storage.repositories.pipeline_visibility import cutoff_view, require_released_cutoff

    _require_run_for_novel(session, novel_id, run_id)
    try:
        cutoff = require_released_cutoff(session, run_id)
    except ValueError as exc:
        raise AnalysisNotCompleteError(message=str(exc), run_status="running") from exc
    return cutoff_view(session, cutoff)


def _parse_emotion_trend_range(
    position_range: str | None,
) -> tuple[float, float] | None:
    """2026-08-15 解析情绪趋势 position 区间并统一校验输入"""
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
