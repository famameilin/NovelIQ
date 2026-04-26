"""
创建时间: 2026-04-26
修改者: Codex
任务: phase2-setup-pool
说明: foreshadowing thread 结果查询组装器。
"""

from __future__ import annotations

from src.api.models.responses import ForeshadowingThreadResponse
from src.storage.repositories import AnnotationRepository


def _fetch_foreshadowing_threads(
    run_id: str,
    annotation_repo: AnnotationRepository,
) -> list[ForeshadowingThreadResponse]:
    """
    获取 setup thread 汇总视图。

    创建时间: 2026-04-26
    任务: phase2-setup-pool
    新建原因: route 层只需要稳定 response model，不应自己拼 thread 命中聚合。
    """

    rows = annotation_repo.fetch_foreshadowing_threads(run_id)
    return [
        ForeshadowingThreadResponse(
            setup_id=row.setup_id,
            first_chunk_id=row.first_chunk_id,
            last_chunk_id=row.last_chunk_id,
            anchor_chunk_ids=row.anchor_chunk_ids,
            setup_summary=row.setup_summary,
            setup_kind=row.setup_kind,
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
