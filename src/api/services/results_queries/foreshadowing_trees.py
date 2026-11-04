"""伏笔轨迹与事件定位的响应装配"""

from __future__ import annotations

from dataclasses import asdict

from src.api.models.responses import ForeshadowingTreeResponse
from src.event_trees.read.foreshadowing import fetch_foreshadowing_trees
from src.storage import Storage


def _fetch_foreshadowing_trees(
    run_id: str,
    annotation_repo: Storage,
) -> list[ForeshadowingTreeResponse]:
    """
    获取伏笔树汇总视图
    """

    rows = fetch_foreshadowing_trees(annotation_repo, run_id)
    return [ForeshadowingTreeResponse.model_validate(asdict(row)) for row in rows]
