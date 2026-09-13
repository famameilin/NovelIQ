"""
说明: 伏笔树结果查询组装器（2026-09-13 伏笔即事件树）
"""

from __future__ import annotations

from src.api.models.responses import ForeshadowingTreeResponse
from src.storage.repositories import AnnotationRepository


def _fetch_foreshadowing_trees(
    run_id: str,
    annotation_repo: AnnotationRepository,
) -> list[ForeshadowingTreeResponse]:
    """
    获取伏笔树汇总视图
    """

    rows = annotation_repo.fetch_foreshadowing_trees(run_id)
    return [
        ForeshadowingTreeResponse(
            root_event_id=row.root_event_id,
            tree_id=row.tree_id,
            first_chapter_id=row.first_chapter_id,
            last_chapter_id=row.last_chapter_id,
            anchor_chapter_ids=row.anchor_chapter_ids,
            description=row.description,
            expected_payoff_family=row.expected_payoff_family,
            payoff_likelihood=row.payoff_likelihood,
            strength=row.strength,
            status=row.status,
            active=row.active,
            latest_reason=row.latest_reason,
            latest_why_unresolved_now=row.latest_why_unresolved_now,
        )
        for row in rows
    ]
