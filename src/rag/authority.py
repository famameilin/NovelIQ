from __future__ import annotations

from src.rag.evidence_types import (
    AliasMapping,
    CanonicalEntity,
    ConfirmedRelation,
    EntityTypeFact,
    Level1AuthoritySnapshot,
)


class Level1AuthorityProvider:
    """Build the minimal Level 1 authority contract from graph tables."""

    def __init__(self, graph_repo) -> None:
        self._graph_repo = graph_repo

    def build_snapshot(self, run_id: str) -> Level1AuthoritySnapshot:
        alias_map = self._graph_repo.fetch_alias_map(run_id)
        entities = self._graph_repo.fetch_entities(run_id)
        relations = self._graph_repo.fetch_current_relations(run_id, active_only=True)

        alias_mappings = [
            AliasMapping(alias=alias, canonical=canonical)
            for alias, canonical in sorted(alias_map.items(), key=lambda item: (item[1], item[0]))
        ]
        canonical_entities = [
            CanonicalEntity(name=entity.canonical_name, entity_type=entity.entity_type or "character")
            for entity in sorted(entities, key=lambda row: row.canonical_name)
        ]
        confirmed_relations = [
            ConfirmedRelation(
                from_name=str(relation.from_name),
                to_name=str(relation.to_name),
                relation_type=str(relation.relation_type),
                is_active=bool(relation.is_active),
                first_seen_chunk=relation.first_seen_chunk,
                last_seen_chunk=relation.last_seen_chunk,
                support_count=relation.support_count,
                latest_event_id=relation.latest_event_id,
            )
            for relation in sorted(
                relations,
                key=lambda row: (str(row.from_name), str(row.to_name), str(row.relation_type)),
            )
        ]
        entity_types = [
            EntityTypeFact(name=entity.canonical_name, entity_type=entity.entity_type or "character")
            for entity in sorted(entities, key=lambda row: row.canonical_name)
        ]

        return Level1AuthoritySnapshot(
            alias_mappings=alias_mappings,
            canonical_entities=canonical_entities,
            confirmed_relations=confirmed_relations,
            entity_types=entity_types,
        )
