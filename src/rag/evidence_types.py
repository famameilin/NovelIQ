from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from src.knowledge.authority import (
    AliasMapping,
    CanonicalEntity,
    ConfirmedRelation,
    EntityTypeFact,
    Level1AuthoritySnapshot,
)

__all__ = [
    "AliasMapping",
    "CanonicalEntity",
    "ConfirmedRelation",
    "EntityTypeFact",
    "Level1AuthoritySnapshot",
    "EvidenceItem",
    "EvidenceBundle",
]


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

