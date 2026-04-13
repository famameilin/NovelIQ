from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class AliasMapping:
    alias: str
    canonical: str
    source: str = "graph_alias_map"
    confidence: float | None = None


@dataclass(slots=True)
class CanonicalEntity:
    """Stable entity identity inside one run, not a transient mention."""

    name: str
    entity_type: str = "character"
    entity_id: int | None = None
    first_seen_chunk: int | None = None
    last_seen_chunk: int | None = None
    primary_role_function: str | None = None
    last_emotion_score: str | None = None
    last_action: str | None = None
    status: str = "active"
    source_confidence: float | None = None
    source: str = "graph_entities"


@dataclass(slots=True)
class ConfirmedRelation:
    """Current authority snapshot for a relation pair, without history."""

    from_name: str
    to_name: str
    relation_type: str
    from_entity_id: int | None = None
    to_entity_id: int | None = None
    is_active: bool = True
    first_seen_chunk: int | None = None
    last_seen_chunk: int | None = None
    change_count: int | None = None
    support_count: int | None = None
    latest_event_id: int | None = None
    tension_index: float | None = None
    source: str = "graph_relations_current"


@dataclass(slots=True)
class RelationEvent:
    """Immutable relation history event for timeline/history consumers."""

    relation_event_id: int
    chunk_id: int
    from_entity_id: int
    to_entity_id: int
    from_name: str
    to_name: str
    relation_type: str
    change_type: str
    evidence: str | None = None
    confidence: float | None = None
    directionality: str | None = None
    source_relation_row_id: int | None = None
    source: str = "graph_relation_events"


@dataclass(slots=True)
class EntityTypeFact:
    name: str
    entity_type: str
    source: str = "graph_entities"


@dataclass(slots=True)
class EntityLifecycle:
    """Stable span/state metadata that can be safely reused across consumers."""

    entity_id: int
    name: str
    entity_type: str
    first_seen_chunk: int | None = None
    last_seen_chunk: int | None = None
    status: str = "active"
    source: str = "graph_entities"


@dataclass(slots=True)
class StableState:
    """
    Cross-chunk stable entity state.

    Intentionally excludes transient local context like last_action or local emotion.
    """

    entity_id: int
    name: str
    entity_type: str
    status: str = "active"
    primary_role_function: str | None = None
    first_seen_chunk: int | None = None
    last_seen_chunk: int | None = None
    source_confidence: float | None = None
    source: str = "graph_entities"


@dataclass(slots=True)
class Level1AuthoritySnapshot:
    alias_mappings: list[AliasMapping] = field(default_factory=list)
    canonical_entities: list[CanonicalEntity] = field(default_factory=list)
    confirmed_relations: list[ConfirmedRelation] = field(default_factory=list)
    entity_types: list[EntityTypeFact] = field(default_factory=list)


@dataclass(slots=True)
class TimelineAuthorityView:
    character_entities: list[CanonicalEntity] = field(default_factory=list)
    entity_lifecycles: list[EntityLifecycle] = field(default_factory=list)
    relation_events: list[RelationEvent] = field(default_factory=list)


@dataclass(slots=True)
class GraphAuthorityView:
    canonical_entities: list[CanonicalEntity] = field(default_factory=list)
    confirmed_relations: list[ConfirmedRelation] = field(default_factory=list)
    relation_events: list[RelationEvent] = field(default_factory=list)
    stable_states: list[StableState] = field(default_factory=list)
    summary: dict[str, Any] = field(default_factory=dict)
    quality: dict[str, Any] = field(default_factory=dict)
