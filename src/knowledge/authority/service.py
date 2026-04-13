from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from src.storage.repositories import GraphRepository

from .types import (
    AliasMapping,
    CanonicalEntity,
    ConfirmedRelation,
    EntityLifecycle,
    EntityTypeFact,
    GraphAuthorityView,
    Level1AuthoritySnapshot,
    RelationEvent,
    StableState,
    TimelineAuthorityView,
)


class KnowledgeGraphAuthorityService:
    """Single authority facade for graph consumers outside the repository layer."""

    def __init__(self, graph_repo: GraphRepository) -> None:
        self._graph_repo = graph_repo

    @classmethod
    def from_session(cls, session: Any) -> KnowledgeGraphAuthorityService:
        return cls(graph_repo=GraphRepository(session))

    def build_level1_snapshot(self, run_id: str) -> Level1AuthoritySnapshot:
        """Level 1 stays intentionally minimal for evidence consumers."""

        entities = self._graph_repo.fetch_entities(run_id)
        return Level1AuthoritySnapshot(
            alias_mappings=self._build_alias_mappings(self._graph_repo.fetch_alias_map(run_id)),
            canonical_entities=self._build_canonical_entities(entities),
            confirmed_relations=self._build_confirmed_relations(
                self._graph_repo.fetch_current_relations(run_id, active_only=True)
            ),
            entity_types=self._build_entity_type_facts(entities),
        )

    def build_timeline_view(self, run_id: str) -> TimelineAuthorityView:
        """Timeline consumes the character subgraph plus immutable relation history."""

        character_entities = self._build_canonical_entities(
            self._graph_repo.fetch_entities(run_id, entity_type="character")
        )
        character_ids = {entity.entity_id for entity in character_entities if entity.entity_id is not None}

        relation_events = [
            event
            for event in self._build_relation_events(self._graph_repo.fetch_relation_events(run_id))
            if event.from_entity_id in character_ids and event.to_entity_id in character_ids
        ]

        return TimelineAuthorityView(
            character_entities=character_entities,
            entity_lifecycles=self._build_entity_lifecycles(character_entities),
            relation_events=relation_events,
        )

    def build_graph_view(self, run_id: str, event_limit: int | None = 200) -> GraphAuthorityView:
        """Graph page and diagnosis consume richer authority projections."""

        entities = self._graph_repo.fetch_entities(run_id)
        confirmed_relations = self._build_confirmed_relations(
            self._graph_repo.fetch_current_relations(run_id, active_only=False)
        )
        all_relation_events = self._build_relation_events(self._graph_repo.fetch_relation_events(run_id))
        relation_events = all_relation_events[:event_limit] if event_limit is not None else all_relation_events
        stable_states = self._build_stable_states(entities)
        quality = self._build_graph_quality(confirmed_relations, all_relation_events)
        summary = self._build_graph_summary(stable_states, confirmed_relations, all_relation_events, quality)

        return GraphAuthorityView(
            canonical_entities=self._build_canonical_entities(entities),
            confirmed_relations=confirmed_relations,
            relation_events=relation_events,
            stable_states=stable_states,
            summary=summary,
            quality=quality,
        )

    def _build_alias_mappings(self, alias_map: dict[str, str]) -> list[AliasMapping]:
        return [
            AliasMapping(alias=alias, canonical=canonical)
            for alias, canonical in sorted(alias_map.items(), key=lambda item: (item[1], item[0]))
        ]

    def _build_canonical_entities(self, entities: Iterable[Any]) -> list[CanonicalEntity]:
        canonical_entities: list[CanonicalEntity] = []
        for entity in sorted(entities, key=lambda row: row.canonical_name):
            canonical_entities.append(
                CanonicalEntity(
                    name=entity.canonical_name,
                    entity_type=entity.entity_type or "character",
                    entity_id=entity.entity_id,
                    first_seen_chunk=entity.first_seen_chunk,
                    last_seen_chunk=entity.last_seen_chunk,
                    primary_role_function=entity.primary_role_function,
                    status=entity.status or "active",
                    source_confidence=entity.source_confidence,
                )
            )
        return canonical_entities

    def _build_confirmed_relations(self, relations: Iterable[dict[str, Any]]) -> list[ConfirmedRelation]:
        confirmed_relations: list[ConfirmedRelation] = []
        for relation in sorted(
            relations,
            key=lambda row: (str(row["from_name"]), str(row["to_name"]), str(row["type"])),
        ):
            confirmed_relations.append(
                ConfirmedRelation(
                    from_name=str(relation["from_name"]),
                    to_name=str(relation["to_name"]),
                    relation_type=str(relation["type"]),
                    from_entity_id=relation.get("from_entity_id"),
                    to_entity_id=relation.get("to_entity_id"),
                    is_active=bool(relation["is_active"]),
                    first_seen_chunk=relation.get("first_seen_chunk"),
                    last_seen_chunk=relation.get("last_seen_chunk"),
                    change_count=relation.get("change_count"),
                    support_count=relation.get("support_count"),
                    latest_event_id=relation.get("latest_event_id"),
                    tension_index=relation.get("tension_index"),
                )
            )
        return confirmed_relations

    def _build_relation_events(self, events: Iterable[dict[str, Any]]) -> list[RelationEvent]:
        relation_events: list[RelationEvent] = []
        for event in events:
            relation_events.append(
                RelationEvent(
                    relation_event_id=int(event["relation_event_id"]),
                    chunk_id=int(event["chunk_id"]),
                    from_entity_id=int(event["from_entity_id"]),
                    to_entity_id=int(event["to_entity_id"]),
                    from_name=str(event["from_name"]),
                    to_name=str(event["to_name"]),
                    relation_type=str(event["relation_type"]),
                    change_type=str(event["change_type"]),
                    evidence=str(event["evidence"]) if event.get("evidence") is not None else None,
                    confidence=float(event["confidence"]) if event.get("confidence") is not None else None,
                    directionality=str(event["directionality"]) if event.get("directionality") is not None else None,
                    source_relation_row_id=(
                        int(event["source_relation_row_id"])
                        if event.get("source_relation_row_id") is not None
                        else None
                    ),
                )
            )
        return relation_events

    def _build_entity_type_facts(self, entities: Iterable[Any]) -> list[EntityTypeFact]:
        return [
            EntityTypeFact(name=entity.canonical_name, entity_type=entity.entity_type or "character")
            for entity in sorted(entities, key=lambda row: row.canonical_name)
        ]

    def _build_entity_lifecycles(self, entities: Iterable[CanonicalEntity]) -> list[EntityLifecycle]:
        lifecycles: list[EntityLifecycle] = []
        for entity in entities:
            if entity.entity_id is None:
                continue
            lifecycles.append(
                EntityLifecycle(
                    entity_id=entity.entity_id,
                    name=entity.name,
                    entity_type=entity.entity_type,
                    first_seen_chunk=entity.first_seen_chunk,
                    last_seen_chunk=entity.last_seen_chunk,
                    status=entity.status,
                )
            )
        return lifecycles

    def _build_stable_states(self, entities: Iterable[Any]) -> list[StableState]:
        stable_states: list[StableState] = []
        for entity in sorted(entities, key=lambda row: row.canonical_name):
            stable_states.append(
                StableState(
                    entity_id=entity.entity_id,
                    name=entity.canonical_name,
                    entity_type=entity.entity_type or "character",
                    status=entity.status or "active",
                    primary_role_function=entity.primary_role_function,
                    first_seen_chunk=entity.first_seen_chunk,
                    last_seen_chunk=entity.last_seen_chunk,
                    source_confidence=entity.source_confidence,
                )
            )
        return stable_states

    def _build_graph_summary(
        self,
        stable_states: list[StableState],
        confirmed_relations: list[ConfirmedRelation],
        relation_events: list[RelationEvent],
        quality: dict[str, Any],
    ) -> dict[str, Any]:
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
                key=lambda item: (-(item.support_count or 0), -(item.last_seen_chunk or 0), item.from_name, item.to_name),
            )[:5]
        ]
        recent_events = [
            {
                "chunk_id": event.chunk_id,
                "type": event.relation_type,
                "change": event.change_type,
                "evidence": event.evidence,
            }
            for event in relation_events[:5]
        ]

        return {
            "node_count": node_count,
            "edge_count": edge_count,
            "density": round(density, 4),
            "core_characters": core_characters,
            "key_relations": key_relations,
            "recent_events": recent_events,
            "quality": quality,
        }

    def _build_graph_quality(
        self,
        confirmed_relations: list[ConfirmedRelation],
        relation_events: list[RelationEvent],
    ) -> dict[str, Any]:
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
        relation_conflicts = self._detect_relation_conflicts(confirmed_relations)
        return {
            "conflict_count": len(relation_conflicts),
            "low_confidence_count": len(low_confidence_events),
            "conflicts": relation_conflicts[:5],
            "low_confidence_samples": low_confidence_events[:5],
        }

    def _detect_relation_conflicts(self, confirmed_relations: list[ConfirmedRelation]) -> list[dict[str, Any]]:
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
