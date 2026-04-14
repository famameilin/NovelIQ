from __future__ import annotations

from typing import Any

from .types import ConfirmedRelation, RelationEvent, StableState


def build_graph_summary_payload(
    stable_states: list[StableState],
    confirmed_relations: list[ConfirmedRelation],
) -> dict[str, Any]:
    """Compute graph-owned summary counters from stable authority facts."""

    node_count = len(stable_states)
    edge_count = len(confirmed_relations)
    density = 0.0
    if node_count > 1:
        density = float(edge_count) / float(node_count * (node_count - 1))

    core_characters = [
        state.name
        for state in sorted(
            stable_states,
            key=lambda item: (item.last_seen_chunk is None, -(item.last_seen_chunk or 0), item.name),
        )[:5]
    ]
    key_relations = [
        {
            "from": relation.from_name,
            "to": relation.to_name,
            "type": relation.relation_type,
            "support_count": int(relation.support_count or 0),
        }
        for relation in sorted(
            confirmed_relations,
            key=lambda item: (
                -(item.support_count or 0),
                -(item.last_seen_chunk or 0),
                item.from_name,
                item.to_name,
            ),
        )[:5]
    ]

    return {
        "node_count": node_count,
        "edge_count": edge_count,
        "density": round(density, 4),
        "core_characters": core_characters,
        "key_relations": key_relations,
    }


def build_graph_quality_payload(
    confirmed_relations: list[ConfirmedRelation],
    relation_events: list[RelationEvent],
) -> dict[str, Any]:
    """Compute graph-page quality details from stable authority facts."""

    low_confidence_events = [
        {
            "relation_event_id": event.relation_event_id,
            "chunk_id": event.chunk_id,
            "from_name": event.from_name,
            "to_name": event.to_name,
            "relation_type": event.relation_type,
            "change_type": event.change_type,
            "confidence": event.confidence,
        }
        for event in relation_events
        if event.confidence is None or event.confidence < 0.6
    ]
    relation_conflicts = _detect_relation_conflicts(confirmed_relations)
    return {
        "conflict_count": len(relation_conflicts),
        "low_confidence_count": len(low_confidence_events),
        "conflicts": relation_conflicts[:5],
        "low_confidence_samples": low_confidence_events[:5],
    }


def build_graph_quality_report(
    confirmed_relations: list[ConfirmedRelation],
    relation_events: list[RelationEvent],
) -> dict[str, int]:
    """Collapse graph quality details into aggregate-only report counters."""

    detailed_quality = build_graph_quality_payload(confirmed_relations, relation_events)
    return {
        "conflict_count": int(detailed_quality["conflict_count"]),
        "low_confidence_count": int(detailed_quality["low_confidence_count"]),
    }


def _detect_relation_conflicts(confirmed_relations: list[ConfirmedRelation]) -> list[dict[str, Any]]:
    pair_map: dict[tuple[int | None, int | None, str, str], list[ConfirmedRelation]] = {}
    for relation in confirmed_relations:
        pair_key = tuple(
            sorted(
                [
                    (relation.from_entity_id, relation.from_name),
                    (relation.to_entity_id, relation.to_name),
                ],
                key=lambda item: (item[0] is None, item[0] if item[0] is not None else item[1]),
            )
        )
        pair_map[pair_key] = pair_map.get(pair_key, []) + [relation]

    conflicts: list[dict[str, Any]] = []
    for pair_key, relations in pair_map.items():
        relation_types = {relation.relation_type for relation in relations if relation.relation_type}
        if len(relation_types) < 2:
            continue
        conflicts.append(
            {
                "entity_pair": [pair_key[0][0], pair_key[1][0]],
                "entity_names": sorted({pair_key[0][1], pair_key[1][1]}),
                "relation_types": sorted(relation_types),
                "relation_count": len(relations),
                "latest_event_ids": [relation.latest_event_id for relation in relations if relation.latest_event_id],
            }
        )
    return conflicts
