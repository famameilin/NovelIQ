from __future__ import annotations

from .types import (
    ConfirmedRelation,
    GraphConflictSample,
    GraphKeyRelationHighlight,
    GraphLowConfidenceSample,
    GraphPageQualityDetails,
    GraphPageSummary,
    GraphQualitySignals,
    GraphSharedSummary,
    ParticipantState,
    RelationEvent,
)

LOW_CONFIDENCE_REPORT_LIMIT = 20
GRAPH_PAGE_CONFLICT_SAMPLE_LIMIT = 5
GRAPH_PAGE_LOW_CONFIDENCE_SAMPLE_LIMIT = 5
GRAPH_PAGE_CORE_CHARACTER_LIMIT = 5
GRAPH_PAGE_KEY_RELATION_LIMIT = 5


def build_graph_shared_summary(
    participant_states: list[ParticipantState],
    confirmed_relations: list[ConfirmedRelation],
) -> GraphSharedSummary:
    """Compute aggregate-only graph summary counters for shared downstream consumers."""

    node_count = len(participant_states)
    edge_count = len(confirmed_relations)
    density = 0.0
    if node_count > 1:
        density = float(edge_count) / float(node_count * (node_count - 1))

    return GraphSharedSummary(
        node_count=node_count,
        edge_count=edge_count,
        density=round(density, 4),
    )


def build_graph_page_summary(
    participant_states: list[ParticipantState],
    confirmed_relations: list[ConfirmedRelation],
) -> GraphPageSummary:
    """Compute graph-page-only summary highlights from stable authority facts."""

    shared_summary = build_graph_shared_summary(participant_states, confirmed_relations)
    # 中文注释：graph page 的 `core_characters` 是页面契约字段，只能从 character 节点中挑选，
    # 不能因为组织/地点最近出现过就挤掉真正的角色。
    core_characters = [
        state.name
        for state in sorted(
            [state for state in participant_states if state.entity_type == "character"],
            key=lambda item: (item.last_seen_chunk is None, -(item.last_seen_chunk or 0), item.name),
        )[:GRAPH_PAGE_CORE_CHARACTER_LIMIT]
    ]
    key_relations = [
        GraphKeyRelationHighlight(
            from_name=relation.from_name,
            to_name=relation.to_name,
            relation_type=relation.relation_type,
            support_count=int(relation.support_count or 0),
        )
        for relation in sorted(
            confirmed_relations,
            key=lambda item: (
                -(item.support_count or 0),
                -(item.last_seen_chunk or 0),
                item.from_name,
                item.to_name,
            ),
        )[:GRAPH_PAGE_KEY_RELATION_LIMIT]
    ]

    return GraphPageSummary(
        node_count=shared_summary.node_count,
        edge_count=shared_summary.edge_count,
        density=shared_summary.density,
        core_characters=core_characters,
        key_relations=key_relations,
    )


def build_graph_quality_signals(
    confirmed_relations: list[ConfirmedRelation],
    relation_events: list[RelationEvent],
) -> GraphQualitySignals:
    """Compute aggregate-only graph quality counters for shared downstream consumers."""

    low_confidence_count = sum(1 for event in relation_events if event.confidence is None or event.confidence < 0.6)
    relation_conflicts = _detect_relation_conflicts(confirmed_relations)
    return GraphQualitySignals(
        conflict_count=len(relation_conflicts),
        low_confidence_count=low_confidence_count,
    )


def build_graph_quality_report(
    confirmed_relations: list[ConfirmedRelation],
    relation_events: list[RelationEvent],
) -> GraphQualitySignals:
    """Collapse graph quality details into aggregate-only report counters."""

    shared_quality = build_graph_quality_signals(confirmed_relations, relation_events)
    # 中文注释：graph page 继续暴露全历史低置信事件计数；但 export/diagnosis
    # 复用的 report 必须保持旧 summary contract，避免长篇作品把 low_confidence_count
    # 悄悄放大成“全历史事件总数”。
    return GraphQualitySignals(
        conflict_count=shared_quality.conflict_count,
        low_confidence_count=min(shared_quality.low_confidence_count, LOW_CONFIDENCE_REPORT_LIMIT),
    )


def build_graph_page_quality(
    confirmed_relations: list[ConfirmedRelation],
    relation_events: list[RelationEvent],
) -> GraphPageQualityDetails:
    """Compute graph-page-only quality details from stable authority facts."""

    shared_quality = build_graph_quality_signals(confirmed_relations, relation_events)
    relation_conflicts = _detect_relation_conflicts(confirmed_relations)
    low_confidence_events = [
        GraphLowConfidenceSample(
            relation_event_id=event.relation_event_id,
            chunk_id=event.chunk_id,
            from_name=event.from_name,
            to_name=event.to_name,
            relation_type=event.relation_type,
            change_type=event.change_type,
            confidence=event.confidence,
        )
        for event in relation_events
        if event.confidence is None or event.confidence < 0.6
    ]
    return GraphPageQualityDetails(
        conflict_count=shared_quality.conflict_count,
        low_confidence_count=shared_quality.low_confidence_count,
        conflicts=relation_conflicts[:GRAPH_PAGE_CONFLICT_SAMPLE_LIMIT],
        low_confidence_samples=low_confidence_events[:GRAPH_PAGE_LOW_CONFIDENCE_SAMPLE_LIMIT],
    )


def _detect_relation_conflicts(confirmed_relations: list[ConfirmedRelation]) -> list[GraphConflictSample]:
    pair_map: dict[tuple[tuple[int | None, str], tuple[int | None, str]], list[ConfirmedRelation]] = {}
    for relation in confirmed_relations:
        sorted_pair = sorted(
            [
                (relation.from_entity_id, relation.from_name),
                (relation.to_entity_id, relation.to_name),
            ],
            key=lambda item: (item[0] is None, item[0] if item[0] is not None else item[1]),
        )
        # 中文注释：这里的 pair_key 语义上永远是“两端实体组成的二元组”，显式拼成
        # 固定长度 tuple，避免 mypy 把 sorted(...) 的结果推断成可变长度序列。
        pair_key = (sorted_pair[0], sorted_pair[1])
        pair_map[pair_key] = pair_map.get(pair_key, []) + [relation]

    conflicts: list[GraphConflictSample] = []
    for pair_key, relations in pair_map.items():
        relation_types = {relation.relation_type for relation in relations if relation.relation_type}
        if len(relation_types) < 2:
            continue
        conflicts.append(
            GraphConflictSample(
                entity_pair=[pair_key[0][0], pair_key[1][0]],
                entity_names=sorted({pair_key[0][1], pair_key[1][1]}),
                relation_types=sorted(relation_types),
                relation_count=len(relations),
                latest_event_ids=[relation.latest_event_id for relation in relations if relation.latest_event_id],
            )
        )
    return conflicts
