"""
说明: foreshadowing thread 结果查询组装器
"""

from __future__ import annotations

from src.api.models.responses import ForeshadowingThreadResponse
from src.storage.repositories import AnnotationRepository


def _fetch_foreshadowing_threads(
    run_id: str,
    annotation_repo: AnnotationRepository,
) -> list[ForeshadowingThreadResponse]:
    """
    获取 setup thread 汇总视图
    """

    rows = annotation_repo.fetch_foreshadowing_threads(run_id)
    return [
        ForeshadowingThreadResponse(
            setup_id=row.setup_id,
            first_chapter_id=row.first_chapter_id,
            last_chapter_id=row.last_chapter_id,
            anchor_chapter_ids=row.anchor_chapter_ids,
            setup_summary=row.setup_summary,
            setup_kind=row.setup_kind,
            expected_payoff_family=row.expected_payoff_family,
            payoff_likelihood=row.payoff_likelihood,
            confidence=row.confidence,
            strength=row.strength,
            status=row.status,
            active=row.active,
            latest_reason=row.latest_reason,
            latest_why_unresolved_now=row.latest_why_unresolved_now,
        )
        for row in rows
    ]
