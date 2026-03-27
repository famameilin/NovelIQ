"""
结果导出服务

创建时间: 2026-03-28
创建者: TraeAI
任务: consolidate-codebase-architecture
说明: 从 results.py 提取的结果导出逻辑，负责数据获取和组装
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from src.api.routes.results_converters import _convert_aggregate_result
from src.api.routes.results_fetchers import (
    _fetch_character_relations,
    _fetch_characters,
    _fetch_chunk_annotations,
    _fetch_chunk_cultures,
    _fetch_chunk_styles,
    _fetch_diagnosis,
    _fetch_emotion_curve,
    _fetch_global_stats,
    _fetch_hierarchical_relations,
    _fetch_novel_name,
    _fetch_rhythm_curve,
    _fetch_token_usage_stats,
    _fetch_topics,
)
from src.metrics.aggregate import aggregate_all_metrics
from src.storage.repositories import (
    AnnotationRepository,
    ChunkRepository,
    EntityRepository,
    StatsRepository,
)


def load_core_results(
    run_id: str,
    stats_repo: StatsRepository,
) -> tuple[list, list, list[str]]:
    """
    加载核心结果数据：情感曲线、节奏曲线、缺失字段

    Returns:
        (emotion_curve, rhythm_curve, missing_fields)
    """
    missing_fields: list[str] = []

    emotion_curve = _fetch_emotion_curve(run_id, stats_repo)
    if not emotion_curve:
        missing_fields.append("emotion_curve")

    rhythm_curve = _fetch_rhythm_curve(run_id, stats_repo)
    if not rhythm_curve:
        missing_fields.append("rhythm_curve")

    return emotion_curve, rhythm_curve, missing_fields


def load_character_bundle(
    run_id: str,
    novel_id: str,
    stats_repo: StatsRepository,
    annotation_repo: AnnotationRepository,
    alias_map: dict[str, str],
) -> tuple[Any, dict[str, float] | None, list[str] | None, set[str], list[str]]:
    """
    加载角色相关数据

    Returns:
        (characters, arc_scores, main_characters, valid_character_names, missing_fields)
    """
    missing_fields: list[str] = []

    diagnosis = _fetch_diagnosis(run_id, novel_id, stats_repo, alias_map)
    if not diagnosis:
        missing_fields.append("diagnosis")

    arc_scores: dict[str, float] | None = None
    main_characters: list[str] | None = None
    if diagnosis:
        arc_scores = diagnosis.arc_scores if isinstance(diagnosis.arc_scores, dict) else None
        main_characters = diagnosis.main_characters

    characters = _fetch_characters(run_id, annotation_repo, arc_scores, main_characters, limit=None)
    if not characters:
        missing_fields.append("characters")
    valid_character_names = {character.name for character in characters}

    return characters, arc_scores, main_characters, valid_character_names, missing_fields


def load_chunk_bundle(
    run_id: str,
    annotation_repo: AnnotationRepository,
    chunk_repo: ChunkRepository,
    alias_map: dict[str, str],
    valid_character_names: set[str],
) -> tuple[list, list, list, list[str]]:
    """
    加载分块相关数据

    Returns:
        (topics, chunk_styles, chunk_annotations, missing_fields)
    """
    missing_fields: list[str] = []

    topics = _fetch_topics(run_id, chunk_repo, alias_map)

    chunk_styles = _fetch_chunk_styles(run_id, chunk_repo)
    if not chunk_styles:
        missing_fields.append("chunk_styles")

    chunk_annotations = _fetch_chunk_annotations(
        run_id,
        annotation_repo,
        alias_map,
        valid_character_names=valid_character_names,
    )
    if not chunk_annotations:
        missing_fields.append("chunk_annotations")

    return topics, chunk_styles, chunk_annotations, missing_fields


def load_aggregate_bundle(
    run_id: str,
    novel_id: str,
    stats_repo: StatsRepository,
    annotation_repo: AnnotationRepository,
    chunk_repo: ChunkRepository,
    entity_repo: EntityRepository,
    alias_map: dict[str, str],
    valid_character_names: set[str],
) -> tuple[list, list, Any, list, Any, dict[str, Any]]:
    """
    加载聚合统计数据

    Returns:
        (character_relations, hierarchical_relations, global_stats, chunk_cultures, token_usage_stats, aggregate_metrics)
    """
    character_relations = _fetch_character_relations(
        run_id,
        annotation_repo,
        alias_map,
        valid_character_names=valid_character_names,
    )
    hierarchical_relations = _fetch_hierarchical_relations(
        novel_id,
        run_id,
        entity_repo,
        valid_character_names=valid_character_names,
    )
    global_stats = _fetch_global_stats(run_id, stats_repo, chunk_repo)

    result = aggregate_all_metrics(run_id, annotation_repo, chunk_repo, stats_repo)
    chunk_cultures = _fetch_chunk_cultures(run_id, chunk_repo)
    narrative_structure, emotion_stats, character_stats, style_stats, culture_stats = _convert_aggregate_result(result)

    aggregate_metrics = {
        "narrative_structure": narrative_structure.model_dump() if narrative_structure else None,
        "emotion_stats": emotion_stats.model_dump() if emotion_stats else None,
        "character_stats": character_stats.model_dump() if character_stats else None,
        "style_stats": style_stats.model_dump() if style_stats else None,
        "culture_stats": culture_stats.model_dump() if culture_stats else None,
    }

    token_usage_stats = _fetch_token_usage_stats(run_id, novel_id, stats_repo)

    return character_relations, hierarchical_relations, global_stats, chunk_cultures, token_usage_stats, aggregate_metrics


def build_export_payload(
    task_id: str,
    novel_id: str,
    novel_name: str | None,
    emotion_curve: list,
    rhythm_curve: list,
    characters: list,
    topics: list,
    diagnosis: Any,
    chunk_styles: list,
    chunk_annotations: list,
    character_relations: list,
    hierarchical_relations: list,
    global_stats: Any,
    chunk_cultures: list,
    aggregate_metrics: dict[str, Any],
    token_usage_stats: Any,
) -> dict[str, Any]:
    """
    构建导出 payload
    """
    return {
        "task_id": task_id,
        "novel_id": novel_id,
        "novel_name": novel_name,
        "generated_at": datetime.now().isoformat(),
        "total_chunks": global_stats.total_chunks if global_stats else 0,
        "total_chars": global_stats.total_chars if global_stats else 0,
        "emotion_curve": [e.model_dump() for e in emotion_curve],
        "rhythm_curve": [r.model_dump() for r in rhythm_curve],
        "characters": [c.model_dump() for c in characters],
        "topics": [t.model_dump() for t in topics],
        "diagnosis": diagnosis.model_dump() if diagnosis else None,
        "chunk_styles": [s.model_dump() for s in chunk_styles],
        "chunk_annotations": [a.model_dump() for a in chunk_annotations],
        "character_relations": [r.model_dump() for r in character_relations],
        "hierarchical_relations": [r.model_dump() for r in hierarchical_relations],
        "global_stats": global_stats.model_dump() if global_stats else None,
        "chunk_cultures": [c.model_dump() for c in chunk_cultures],
        "aggregate_metrics": aggregate_metrics,
        "token_usage_stats": token_usage_stats.model_dump(),
    }


def fetch_all_results_data(
    novel_id: str,
    task_id: str,
    run_id: str,
    stats_repo: StatsRepository,
    annotation_repo: AnnotationRepository,
    chunk_repo: ChunkRepository,
    entity_repo: EntityRepository,
) -> tuple[dict[str, Any], list[str], str | None]:
    """
    获取所有分析结果数据

    创建时间: 2026-03-13
    创建者: TraeAI
    任务: refactor-api-layer-functions

    修改时间: 2026-03-28
    修改者: TraeAI
    任务: consolidate-codebase-architecture
    修改内容: 拆分为多个子函数，简化主函数逻辑
    """
    alias_map = annotation_repo.fetch_alias_map(run_id)

    emotion_curve, rhythm_curve, missing_fields = load_core_results(run_id, stats_repo)

    characters, arc_scores, main_characters, valid_character_names, char_missing = load_character_bundle(
        run_id, novel_id, stats_repo, annotation_repo, alias_map
    )
    missing_fields.extend(char_missing)

    diagnosis = _fetch_diagnosis(run_id, novel_id, stats_repo, alias_map)
    if not diagnosis:
        missing_fields.append("diagnosis")

    topics, chunk_styles, chunk_annotations, chunk_missing = load_chunk_bundle(
        run_id, annotation_repo, chunk_repo, alias_map, valid_character_names
    )
    missing_fields.extend(chunk_missing)

    character_relations, hierarchical_relations, global_stats, chunk_cultures, token_usage_stats, aggregate_metrics = load_aggregate_bundle(
        run_id, novel_id, stats_repo, annotation_repo, chunk_repo, entity_repo, alias_map, valid_character_names
    )

    novel_name = _fetch_novel_name(run_id, novel_id, stats_repo)

    results_data = build_export_payload(
        task_id=task_id,
        novel_id=novel_id,
        novel_name=novel_name,
        emotion_curve=emotion_curve,
        rhythm_curve=rhythm_curve,
        characters=characters,
        topics=topics,
        diagnosis=diagnosis,
        chunk_styles=chunk_styles,
        chunk_annotations=chunk_annotations,
        character_relations=character_relations,
        hierarchical_relations=hierarchical_relations,
        global_stats=global_stats,
        chunk_cultures=chunk_cultures,
        aggregate_metrics=aggregate_metrics,
        token_usage_stats=token_usage_stats,
    )

    return results_data, missing_fields, novel_name
