from __future__ import annotations

from src.relation_network_metrics import summarize_relation_network

from .types import (
    ConfirmedRelation,
    GraphChange,
    GraphConflictSample,
    GraphQualitySignals,
    GraphSharedSummary,
    ParticipantState,
)

LOW_CONFIDENCE_REPORT_LIMIT = 20


# 图谱摘要中的网络密度使用唯一人物关系的集中度口径
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
        density=round(density, 4) if density is not None else None,
    )


def build_graph_quality_signals(
    confirmed_relations: list[ConfirmedRelation],
    graph_changes: list[GraphChange],
) -> GraphQualitySignals:
    """为共享下游消费者计算仅聚合级的图谱质量计数器"""

    low_confidence_count = sum(
        1 for change in graph_changes if change.change_kind == "relation" and change.confidence == "low"
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
            )
        )
    return conflicts
