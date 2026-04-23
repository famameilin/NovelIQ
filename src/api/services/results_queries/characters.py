"""
角色查询组装器。

创建时间: 2026-04-23
创建者: Codex
任务: p1-api-route-service-decouple
说明: 承载 characters 相关查询组装逻辑。
"""

from __future__ import annotations

from typing import Any

from src.api.models.responses import CharacterStats
from src.config import settings
from src.config.constants import EMOTION_SCORE_MAPPING
from src.storage.repositories import AnnotationRepository, GraphRepository

from .common import _calculate_protagonist_scores


def _fetch_characters(
    run_id: str,
    annotation_repo: AnnotationRepository,
    arc_scores: dict[str, float] | None = None,
    main_characters: list[str] | None = None,
    limit: int | None = settings.api.query_limit,
) -> list:
    """获取角色统计数据。"""
    graph_repo = GraphRepository(annotation_repo.session)
    alias_map = graph_repo.fetch_alias_map(run_id)
    rows = annotation_repo.fetch_characters_with_scores(run_id)

    merged: dict[str, dict[str, Any]] = {}
    for row in rows:
        name: str = str(row.name)
        canonical = alias_map.get(name, name)
        role_function: str = str(row.role_function) if row.role_function else "unknown"
        emotion_raw: str | None = str(row.emotion_score) if row.emotion_score else None
        emotion_score = EMOTION_SCORE_MAPPING.get(emotion_raw, 0) if emotion_raw else 0

        if canonical not in merged:
            merged[canonical] = {
                "count": 1,
                "role_function_counts": {role_function: 1},
                "weighted_score": emotion_score,
            }
        else:
            merged[canonical]["count"] += 1
            merged[canonical]["weighted_score"] += emotion_score
            rf_counts = merged[canonical]["role_function_counts"]
            rf_counts[role_function] = rf_counts.get(role_function, 0) + 1

    result = []
    for name, data in merged.items():
        avg_score = data["weighted_score"] / data["count"] if data["count"] > 0 else 0
        rf_counts = data["role_function_counts"]
        total_count = data["count"]
        dominant_role = max(rf_counts, key=lambda key: rf_counts[key] or 0)
        dominant_count = rf_counts[dominant_role]
        dominant_ratio = dominant_count / total_count if total_count > 0 else 0.0

        result.append(
            CharacterStats(
                name=name,
                appearance_count=int(total_count),
                dominant_role_function=dominant_role,
                role_function_distribution=rf_counts,
                dominant_role_ratio=dominant_ratio,
                protagonist_score=None,
                is_protagonist=None,
                avg_emotion_score=avg_score,
            )
        )

    result.sort(key=lambda item: item.appearance_count, reverse=True)
    if arc_scores is not None and main_characters is not None:
        result = _calculate_protagonist_scores(result, arc_scores, main_characters)

    if limit is None:
        return result
    return result[:limit]
