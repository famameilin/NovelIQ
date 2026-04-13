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
    name: str
    entity_type: str = "character"
    source: str = "graph_entities"


@dataclass(slots=True)
class ConfirmedRelation:
    from_name: str
    to_name: str
    relation_type: str
    is_active: bool = True
    first_seen_chunk: int | None = None
    last_seen_chunk: int | None = None
    support_count: int | None = None
    latest_event_id: int | None = None
    source: str = "graph_relations_current"


@dataclass(slots=True)
class EntityTypeFact:
    name: str
    entity_type: str
    source: str = "graph_entities"


@dataclass(slots=True)
class Level1AuthoritySnapshot:
    alias_mappings: list[AliasMapping] = field(default_factory=list)
    canonical_entities: list[CanonicalEntity] = field(default_factory=list)
    confirmed_relations: list[ConfirmedRelation] = field(default_factory=list)
    entity_types: list[EntityTypeFact] = field(default_factory=list)


@dataclass(slots=True)
class EvidenceItem:
    evidence_type: str
    source: str
    content: str
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class EvidenceBundle:
    structured_evidence: list[EvidenceItem] = field(default_factory=list)
    local_evidence: list[EvidenceItem] = field(default_factory=list)
    semantic_evidence: list[EvidenceItem] = field(default_factory=list)
    requested_names: list[str] = field(default_factory=list)
    level1_snapshot: Level1AuthoritySnapshot | None = None

