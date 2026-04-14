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
    """
    Stable entity identity inside one run.

    Intentionally excludes transient prompt-local state like last_action or
    last_emotion_score so Level 1 stays a minimal reusable authority contract.
    """

    name: str
    entity_type: str = "character"
    entity_id: int | None = None
    first_seen_chunk: int | None = None
    last_seen_chunk: int | None = None
    primary_role_function: str | None = None
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
    """
    Stable span/state metadata that can be safely reused across consumers.

    For timeline consumers this is the protected source of truth for
    character entry/exit spans. Downstream code should not re-derive
    lifecycle windows from repository rows.
    """

    entity_id: int
    name: str
    entity_type: str
    first_seen_chunk: int | None = None
    last_seen_chunk: int | None = None
    status: str = "active"
    source: str = "graph_entities"


@dataclass(slots=True)
class ActiveEntityContext:
    """
    Level 2 local context contract for nearby active entities.

    This keeps prompt consumers off the repository row shape while still
    exposing the recent local state they need for annotation/disambiguation.
    """

    name: str
    entity_id: int | None = None
    role: str | None = None
    entity_type: str = "character"
    status: str = "active"
    last_seen_chunk: int | None = None
    recent_action: str | None = None
    recent_emotion: str | None = None
    source: str = "graph_active_entities"


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
    """
    Minimal Level 1 authority contract for evidence consumers.

    This snapshot exists to feed EvidenceBundle/Level1 assembly and should stay
    free of timeline history, graph product summaries, and prompt-local state.
    """

    alias_mappings: list[AliasMapping] = field(default_factory=list)
    canonical_entities: list[CanonicalEntity] = field(default_factory=list)
    confirmed_relations: list[ConfirmedRelation] = field(default_factory=list)
    entity_types: list[EntityTypeFact] = field(default_factory=list)


@dataclass(slots=True)
class TimelineAuthorityView:
    """
    Protected timeline-facing authority contract.

    The view is intentionally narrower than the full graph authority surface:
    - ``character_entities`` contains only the character subgraph.
    - ``entity_lifecycles`` stays aligned with that same character set.
    - ``relation_events`` contains immutable history events whose two endpoints
      both belong to the character subgraph.

    Timeline consumers should treat this as the shared contract and avoid
    depending on repository row shapes or current-relation projections.
    """

    character_entities: list[CanonicalEntity] = field(default_factory=list)
    entity_lifecycles: list[EntityLifecycle] = field(default_factory=list)
    relation_events: list[RelationEvent] = field(default_factory=list)


@dataclass(slots=True)
class GraphAuthorityView:
    """
    Protected graph-facing authority facts.

    This contract deliberately stops at stable facts:
    - canonical entity identity
    - current confirmed relations
    - immutable relation history events
    - stable entity states

    Product-layer summaries/quality cards belong to graph page assemblers,
    while diagnosis/aggregate conclusions belong to higher-level analysis.
    If another downstream needs a different slice, add a dedicated contract
    instead of borrowing repository rows or overloading Level1/Timeline
    boundaries.
    """

    canonical_entities: list[CanonicalEntity] = field(default_factory=list)
    confirmed_relations: list[ConfirmedRelation] = field(default_factory=list)
    relation_events: list[RelationEvent] = field(default_factory=list)
    stable_states: list[StableState] = field(default_factory=list)


@dataclass(slots=True)
class GraphAuthorityReport:
    """
    Narrow authority-owned graph signals for non-graph product consumers.

    Export and diagnosis may reuse these aggregate graph signals as inputs, but
    the final diagnosis/aggregate conclusions are assembled outside authority.
    The quality payload is intentionally aggregate-only so these consumers do
    not recouple to graph page detail samples through report-level shortcuts.
    """

    summary: dict[str, Any] = field(default_factory=dict)
    quality: dict[str, Any] = field(default_factory=dict)
