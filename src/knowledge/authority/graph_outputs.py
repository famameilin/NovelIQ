from __future__ import annotations

from src.relation_network_metrics import summarize_relation_network

from .types import (
    ConfirmedRelation,
    GraphChange,
    GraphConflictSample,
    GraphKeyRelationHighlight,
    GraphLowConfidenceSample,
    GraphPageQualityDetails,
    GraphPageSummary,
    GraphQualitySignals,
    GraphSharedSummary,
    ParticipantState,
)

LOW_CONFIDENCE_REPORT_LIMIT = 20
GRAPH_PAGE_CONFLICT_SAMPLE_LIMIT = 5
GRAPH_PAGE_LOW_CONFIDENCE_SAMPLE_LIMIT = 5
GRAPH_PAGE_CORE_CHARACTER_LIMIT = 5
GRAPH_PAGE_KEY_RELATION_LIMIT = 5


# 2026-04-28，任务：将“网络密度”改为关系集中度口径。
# 修改原因：graph page 顶部指标要和用户看到的关系结构一致，因此这里改成
# 基于唯一人物对关系的集中度统计，而不是继续输出旧的图论密度。
def build_graph_shared_summary(
    participant_states: list[ParticipantState],
    confirmed_relations: list[ConfirmedRelation],
) -> GraphSharedSummary:
    """为共享下游消费者计算仅聚合级的图谱摘要计数器"""

    node_count, edge_count, density = summarize_relation_network(
        [(relation.from_name, relation.to_name) for relation in confirmed_relations],
        node_names=[state.name for state in participant_states if state.name],
    )

    return GraphSharedSummary(
        node_count=node_count,
        edge_count=edge_count,
        density=round(density, 4),
    )


def build_graph_page_summary(
    participant_states: list[ParticipantState],
    confirmed_relations: list[ConfirmedRelation],
) -> GraphPageSummary:
    """根据稳定 authority 事实计算仅供图谱页面使用的摘要高亮"""

    shared_summary = build_graph_shared_summary(participant_states, confirmed_relations)
    # graph page 的 `core_characters` 是页面契约字段，只能从 character 节点中挑选，
    # 不能因为组织/地点最近出现过就挤掉真正的角色
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
    graph_changes: list[GraphChange],
) -> GraphQualitySignals:
    """为共享下游消费者计算仅聚合级的图谱质量计数器"""

    low_confidence_count = sum(
        1
        for change in graph_changes
        if change.change_kind == "relation" and change.confidence == "low"
    )
    relation_conflicts = _detect_relation_conflicts(confirmed_relations)
    return GraphQualitySignals(
        conflict_count=len(relation_conflicts),
        low_confidence_count=low_confidence_count,
    )


def build_graph_quality_report(
    confirmed_relations: list[ConfirmedRelation],
    graph_changes: list[GraphChange],
) -> GraphQualitySignals:
    """把图谱质量明细收口为仅聚合级的报告计数器"""

    shared_quality = build_graph_quality_signals(confirmed_relations, graph_changes)
    # graph page 继续暴露全历史低置信事件计数；export/diagnosis
    # 复用的 report 保持稳定上限，避免长篇作品把低置信事件放大成全历史总数
    return GraphQualitySignals(
        conflict_count=shared_quality.conflict_count,
        low_confidence_count=min(shared_quality.low_confidence_count, LOW_CONFIDENCE_REPORT_LIMIT),
    )


def build_graph_page_quality(
    confirmed_relations: list[ConfirmedRelation],
    graph_changes: list[GraphChange],
) -> GraphPageQualityDetails:
    """根据稳定 authority 事实计算仅供图谱页面使用的质量明细"""

    shared_quality = build_graph_quality_signals(confirmed_relations, graph_changes)
    relation_conflicts = _detect_relation_conflicts(confirmed_relations)
    low_confidence_changes = [
        GraphLowConfidenceSample(
            change_id=change.change_id,
            graph_version_id=change.graph_version_id,
            chapter_id=change.chapter_id,
            fact_id=change.fact_id,
            fact_revision=change.fact_revision,
            effective_chunk_id=change.effective_chunk_id,
            relation_id=change.relation_id,
            from_name=change.from_name or "",
            to_name=change.to_name or "",
            relation_type=change.relation_type,
            change_kind=(
                str(change.changes[0].get("change_kind"))
                if change.changes
                else None
            ),
            confidence=change.confidence,
        )
        for change in graph_changes
        if change.change_kind == "relation" and change.confidence == "low"
    ]
    return GraphPageQualityDetails(
        conflict_count=shared_quality.conflict_count,
        low_confidence_count=shared_quality.low_confidence_count,
        conflicts=relation_conflicts[:GRAPH_PAGE_CONFLICT_SAMPLE_LIMIT],
        low_confidence_samples=low_confidence_changes[:GRAPH_PAGE_LOW_CONFIDENCE_SAMPLE_LIMIT],
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
        # 这里的 pair_key 语义上永远是“两端实体组成的二元组”，显式拼成
        # 固定长度 tuple，避免 mypy 把 sorted(...) 的结果推断成可变长度序列
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
                latest_relation_version_ids=[
                    relation.latest_relation_version_id
                    for relation in relations
                    if relation.latest_relation_version_id
                ],
            )
        )
    return conflicts
