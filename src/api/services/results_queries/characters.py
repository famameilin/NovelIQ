"""
角色查询组装器

说明: 承载 characters 相关取数与响应装配；出现量归并、焦点评分与别名归一
分别在 `src.metrics.aggregate.aggregations` 与 `normalization`。
"""

from __future__ import annotations

from src.api.models.responses import CharacterStats
from src.fact_graph.read.annotations import fetch_chapter_characters_full
from src.fact_graph.read.normalization import build_name_resolution
from src.metrics.aggregate.aggregations import (
    merge_character_appearances,
    rank_character_appearances,
)
from src.storage import Storage


def _fetch_characters(
    run_id: str,
    annotation_repo: Storage,
    arc_scores: dict[str, float] | None = None,
    focus_characters: list[str] | None = None,
    main_characters: list[str] | None = None,
    limit: int | None = 50,
) -> list:
    """组装角色榜，过滤局部引用、归并别名并对齐诊断名单"""
    rows = fetch_chapter_characters_full(annotation_repo, run_id)
    name_resolution = build_name_resolution(
        annotation_repo,
        run_id,
        preferred_names=main_characters,
    )
    appearances = merge_character_appearances(rows, name_resolution)
    ranked = rank_character_appearances(
        appearances,
        name_resolution=name_resolution,
        arc_scores=arc_scores,
        focus_characters=focus_characters,
        main_characters=main_characters,
        limit=limit,
    )
    return [CharacterStats(**payload) for payload in ranked]
