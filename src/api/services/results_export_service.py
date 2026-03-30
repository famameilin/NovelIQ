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

from loguru import logger

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
from src.metrics.timeline_metrics import build_timeline_candidates, convert_to_timeline_nodes, select_timeline_nodes
from src.storage.repositories import (
    AnnotationRepository,
    ChunkRepository,
    DiagnosisRepository,
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
    entity_repo: EntityRepository,
    alias_map: dict[str, str],
) -> tuple[Any, dict[str, float] | None, list[str] | None, set[str], list[str]]:
    """
    加载角色相关数据

    修改时间: 2026-03-28
    修改者: TraeAI
    任务: fix-hierarchical-relation-filter
    修改内容: 添加 entity_repo 参数，将 entities 表中的实体也加入 valid_character_names

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

    entity_names = entity_repo.fetch_all_canonical_names(novel_id, run_id)
    valid_character_names = valid_character_names | entity_names

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
) -> tuple[list, list, Any, list, Any, dict[str, Any], dict[str, Any]]:
    """
    加载聚合统计数据

    Returns:
        (character_relations, hierarchical_relations, global_stats, chunk_cultures, token_usage_stats, aggregate_metrics, graph_summary)
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
    graph_summary = DiagnosisRepository(stats_repo.session).fetch_graph_summary(run_id)

    return (
        character_relations,
        hierarchical_relations,
        global_stats,
        chunk_cultures,
        token_usage_stats,
        aggregate_metrics,
        graph_summary,
    )


def _fetch_timeline_data(
    run_id: str,
    session: Any,
    chunk_repo: ChunkRepository,
    annotation_repo: AnnotationRepository,
    stats_repo: StatsRepository,
) -> dict[str, Any] | None:
    """
    获取时间轴数据用于导出

    Returns:
        时间轴数据字典，包含 phases, nodes, tension_curve
    """
    try:
        (
            candidates,
            tension_scores,
            chunk_ids,
            total_chunks,
            timeline_phases,
            major_character_entries,
            relation_break_events,
        ) = build_timeline_candidates(run_id, chunk_repo, annotation_repo, stats_repo)
    except ValueError:
        return None
    except Exception as e:
        logger.warning(f"Failed to build timeline data: {e}")
        return None

    selected_nodes = select_timeline_nodes(
        candidates=candidates,
        chunk_ids=chunk_ids,
        tension_scores=tension_scores,
        major_character_entries=major_character_entries,
        relation_break_events=relation_break_events,
        min_nodes=10,
        max_nodes=20,
    )

    timeline_nodes = convert_to_timeline_nodes(selected_nodes)

    return {
        "phases": [p.model_dump() for p in timeline_phases],
        "nodes": [n.model_dump() for n in timeline_nodes],
        "tension_curve": tension_scores,
        "total_chunks": total_chunks,
    }


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
    graph_summary: dict[str, Any] | None = None,
    timeline_data: dict[str, Any] | None = None,
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
        "emotion_curve": [e.model_dump(exclude_none=True) for e in emotion_curve],
        "rhythm_curve": [r.model_dump(exclude_none=True) for r in rhythm_curve],
        "characters": [c.model_dump(exclude_none=True) for c in characters],
        "topics": [t.model_dump(exclude_none=True) for t in topics],
        "diagnosis": diagnosis.model_dump(exclude_none=True) if diagnosis else None,
        "chunk_styles": [s.model_dump(exclude_none=True) for s in chunk_styles],
        "chunk_annotations": [a.model_dump(exclude_none=True) for a in chunk_annotations],
        "character_relations": [r.model_dump(exclude_none=True) for r in character_relations],
        "hierarchical_relations": [r.model_dump(exclude_none=True) for r in hierarchical_relations],
        "global_stats": global_stats.model_dump(exclude_none=True) if global_stats else None,
        "chunk_cultures": [c.model_dump(exclude_none=True) for c in chunk_cultures],
        "aggregate_metrics": aggregate_metrics,
        "token_usage_stats": token_usage_stats.model_dump(exclude_none=True),
        "graph_summary": graph_summary or {},
        "graph_quality_report": (graph_summary or {}).get("quality", {}),
        "timeline": timeline_data,
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
        run_id, novel_id, stats_repo, annotation_repo, entity_repo, alias_map
    )
    missing_fields.extend(char_missing)

    diagnosis = _fetch_diagnosis(run_id, novel_id, stats_repo, alias_map)
    if not diagnosis:
        missing_fields.append("diagnosis")

    topics, chunk_styles, chunk_annotations, chunk_missing = load_chunk_bundle(
        run_id, annotation_repo, chunk_repo, alias_map, valid_character_names
    )
    missing_fields.extend(chunk_missing)

    (
        character_relations,
        hierarchical_relations,
        global_stats,
        chunk_cultures,
        token_usage_stats,
        aggregate_metrics,
        graph_summary,
    ) = load_aggregate_bundle(
        run_id, novel_id, stats_repo, annotation_repo, chunk_repo, entity_repo, alias_map, valid_character_names
    )

    novel_name = _fetch_novel_name(run_id, novel_id, stats_repo)

    # 获取时间轴数据
    timeline_data = _fetch_timeline_data(
        run_id=run_id,
        session=stats_repo.session,
        chunk_repo=chunk_repo,
        annotation_repo=annotation_repo,
        stats_repo=stats_repo,
    )
    if not timeline_data:
        missing_fields.append("timeline")

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
        graph_summary=graph_summary,
        timeline_data=timeline_data,
    )

    return results_data, missing_fields, novel_name
