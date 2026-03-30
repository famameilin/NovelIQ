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
from src.metrics.timeline_metrics import (
    TimelineCandidate,
    calculate_tension_percentile,
    compute_four_phases,
    compute_importance_score,
    convert_to_timeline_phases,
    get_major_characters_by_span,
    select_timeline_nodes,
)
from src.storage.models import ChunkSummary, GraphEntity, GraphRelationEvent
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
    from src.api.models.timeline import RelationChangeEvent

    try:
        # 获取 chunk 文本列表
        chunk_texts = chunk_repo.fetch_chunk_texts(run_id)
        if not chunk_texts:
            return None

        chunk_ids = [cid for cid, _ in chunk_texts]
        total_chunks = len(chunk_ids)

        # 获取张力曲线
        rhythm_curve = stats_repo.fetch_rhythm_curve(run_id)
        tension_scores = [row[0] if row else 0.0 for row in rhythm_curve] if rhythm_curve else [0.5] * total_chunks

        # 确保张力数据长度匹配
        if len(tension_scores) < total_chunks:
            tension_scores.extend([0.5] * (total_chunks - len(tension_scores)))
        elif len(tension_scores) > total_chunks:
            tension_scores = tension_scores[:total_chunks]

        # 获取分块摘要
        summaries_data = (
            session.query(ChunkSummary.chunk_id, ChunkSummary.summary)
            .filter(ChunkSummary.run_id == run_id)
            .order_by(ChunkSummary.chunk_id)
            .all()
        )
        summary_map = {row[0]: row[1] for row in summaries_data}

        # 获取标注数据
        annotations = annotation_repo.fetch_chunk_annotations(run_id)
        annotation_map = {ann.chunk_id: ann for ann in annotations} if annotations else {}

        # 获取知识图谱数据
        entities = (
            session.query(GraphEntity)
            .filter(GraphEntity.run_id == run_id, GraphEntity.entity_type == "character")
            .all()
        )

        # 预构建实体ID到名称的映射
        entity_name_map: dict[int, str] = {
            e.entity_id: e.canonical_name for e in entities if e.entity_id is not None
        }

        relation_events = (
            session.query(GraphRelationEvent)
            .filter(GraphRelationEvent.run_id == run_id)
            .all()
        )

        # 计算四阶段划分
        phases = compute_four_phases(tension_scores, chunk_ids)
        timeline_phases = convert_to_timeline_phases(phases)

        # 获取主要角色
        major_characters = get_major_characters_by_span(entities, top_n=3)
        major_character_entries: list[tuple[str, int]] = []
        for char in major_characters:
            if char.first_seen_chunk is not None:
                try:
                    idx = chunk_ids.index(char.first_seen_chunk)
                    major_character_entries.append((char.canonical_name, idx))
                except ValueError:
                    pass

        # 获取关系断裂事件
        relation_break_events: list[tuple[int, RelationChangeEvent]] = []
        for rel_event in relation_events:
            if rel_event.change_type == "断裂":
                try:
                    idx = chunk_ids.index(rel_event.chunk_id)
                    from_char = entity_name_map.get(
                        rel_event.from_entity_id, str(rel_event.from_entity_id)
                    )
                    to_char = entity_name_map.get(
                        rel_event.to_entity_id, str(rel_event.to_entity_id)
                    )
                    relation_break_events.append(
                        (
                            idx,
                            RelationChangeEvent(
                                from_char=from_char,
                                to_char=to_char,
                                relation_type=rel_event.relation_type,
                                change_type=rel_event.change_type,
                                evidence=rel_event.evidence,
                            ),
                        )
                    )
                except ValueError:
                    pass

        # 创建候选节点
        candidates: list[TimelineCandidate] = []
        for i, (chunk_id, text) in enumerate(chunk_texts):
            progress = i / (total_chunks - 1) if total_chunks > 1 else 0.0

            ann = annotation_map.get(chunk_id)
            pivot_moment = ann.pivot_moment if ann else False
            cliffhanger = ann.cliffhanger if ann else False
            event_type = ann.event_type if ann else ""
            emotional_valence = ann.emotional_valence if ann else ""

            event = summary_map.get(chunk_id, "")
            if not event:
                event = text[:30] + "..." if len(text) > 30 else text

            character_entries: list[str] = []
            character_exits: list[str] = []
            for char in entities:
                if char.first_seen_chunk == chunk_id:
                    character_entries.append(char.canonical_name)
                if char.last_seen_chunk == chunk_id:
                    character_exits.append(char.canonical_name)

            relation_changes: list[RelationChangeEvent] = []
            for event_data in relation_events:
                if event_data.chunk_id == chunk_id:
                    from_char = entity_name_map.get(
                        event_data.from_entity_id, str(event_data.from_entity_id)
                    )
                    to_char = entity_name_map.get(
                        event_data.to_entity_id, str(event_data.to_entity_id)
                    )
                    relation_changes.append(
                        RelationChangeEvent(
                            from_char=from_char,
                            to_char=to_char,
                            relation_type=event_data.relation_type,
                            change_type=event_data.change_type,
                            evidence=event_data.evidence,
                        )
                    )

            is_major_character = bool(
                set(character_entries) | set(character_exits)
                & {c.canonical_name for c in major_characters}
            )

            importance_score, level = compute_importance_score(
                pivot_moment=pivot_moment,
                cliffhanger=cliffhanger,
                tension_composite=tension_scores[i],
                all_tensions=tension_scores,
                event_type=event_type,
                emotional_valence=emotional_valence,
                has_relation_change=bool(relation_changes),
                has_character_entry=bool(character_entries),
                has_character_exit=bool(character_exits),
                is_major_character=is_major_character,
            )

            candidates.append(
                TimelineCandidate(
                    chunk_id=chunk_id,
                    progress=progress,
                    importance_score=importance_score,
                    level=level,
                    event=event,
                    characters=character_entries + character_exits,
                    is_pivot=pivot_moment,
                    is_cliffhanger=cliffhanger,
                    tension_percentile=calculate_tension_percentile(tension_scores[i], tension_scores),
                    node_type="character_entry" if character_entries else ("character_exit" if character_exits else "plot"),
                    relation_changes=relation_changes if relation_changes else None,
                    character_entries=character_entries if character_entries else None,
                    character_exits=character_exits if character_exits else None,
                )
            )

        # 筛选节点
        from src.metrics.timeline_metrics import convert_to_timeline_nodes
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
    except Exception:
        return None


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
