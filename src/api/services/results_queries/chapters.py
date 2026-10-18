"""
章节查询组装器

说明: 承载章节标注相关查询组装逻辑（M9a-2：chunk 命名下线，
仅保留章节标注展开，数据源为 chapter_annotations 表）。

角色/关系/对话的引用裁决与按章归组在 `src.metrics.aggregate.normalization`，
本模块只做取数与响应装配。
"""

from __future__ import annotations

from src.api.models.responses import (
    ChapterAnnotation,
    ChapterCharacter,
    ChapterDialogue,
    ChapterRelation,
)
from src.fact_graph.read import ExportGraphAuthorityView, KnowledgeGraphAuthorityService
from src.fact_graph.read.annotations import fetch_chapter_characters_full, fetch_chapter_dialogues_full
from src.fact_graph.read.normalization import (
    partition_chapter_characters,
    partition_chapter_dialogues,
    partition_chapter_relations,
)
from src.metrics.queries.annotations import fetch_chapter_annotations_full
from src.metrics.values import read_emotion_score
from src.storage import Storage


def _fetch_chapter_annotations(
    run_id: str,
    annotation_repo: Storage,
    valid_character_names: set[str] | None = None,
    export_graph_view: ExportGraphAuthorityView | None = None,
) -> list:
    """组装章节标注并过滤未解析的局部角色引用"""
    annotations_raw = fetch_chapter_annotations_full(annotation_repo, run_id)
    characters_raw = fetch_chapter_characters_full(annotation_repo, run_id)
    dialogues_raw = fetch_chapter_dialogues_full(annotation_repo, run_id)

    if export_graph_view is None:
        authority_service = KnowledgeGraphAuthorityService.from_session(annotation_repo)
        export_graph_view = authority_service.build_export_view(run_id)

    characters_by_chunk = partition_chapter_characters(
        characters_raw,
        valid_character_names=valid_character_names,
    )
    relations_by_chunk = partition_chapter_relations(
        export_graph_view,
        valid_character_names=valid_character_names,
    )
    dialogues_by_chunk = partition_chapter_dialogues(
        dialogues_raw,
        valid_character_names=valid_character_names,
    )

    result: list[ChapterAnnotation] = []
    for annotation_row in annotations_raw:
        chapter_id = int(annotation_row.chapter_id)
        result.append(
            ChapterAnnotation(
                chapter_id=chapter_id,
                emotional_valence=(
                    read_emotion_score(annotation_row.emotional_valence)
                    if annotation_row.emotional_valence is not None
                    else None
                ),
                event_type=str(annotation_row.event_type) if annotation_row.event_type else None,
                pivot_moment=(bool(annotation_row.pivot_moment) if annotation_row.pivot_moment is not None else None),
                cliffhanger=(bool(annotation_row.cliffhanger) if annotation_row.cliffhanger is not None else None),
                has_foreshadowing=(
                    bool(annotation_row.has_foreshadowing) if annotation_row.has_foreshadowing is not None else None
                ),
                is_strong_setup=(
                    bool(annotation_row.is_strong_setup)
                    if getattr(annotation_row, "is_strong_setup", None) is not None
                    else None
                ),
                foreshadowing_desc=(
                    str(annotation_row.foreshadowing_desc) if annotation_row.foreshadowing_desc else None
                ),
                why_unresolved_now=(
                    str(annotation_row.why_unresolved_now)
                    if getattr(annotation_row, "why_unresolved_now", None)
                    else None
                ),
                payoff_likelihood=(
                    str(annotation_row.payoff_likelihood)
                    if getattr(annotation_row, "payoff_likelihood", None)
                    else None
                ),
                foreshadowing_root_event_id=(
                    str(annotation_row.foreshadowing_root_event_id)
                    if getattr(annotation_row, "foreshadowing_root_event_id", None)
                    else None
                ),
                coverage_warnings=list(getattr(annotation_row, "coverage_warnings", None) or []),
                characters=[ChapterCharacter(**payload) for payload in characters_by_chunk.get(chapter_id, [])],
                relations=[ChapterRelation(**payload) for payload in relations_by_chunk.get(chapter_id, [])],
                dialogues=[ChapterDialogue(**payload) for payload in dialogues_by_chunk.get(chapter_id, [])],
            )
        )

    return result
