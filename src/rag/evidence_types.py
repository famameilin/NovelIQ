from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from src.knowledge.authority import (
    ActiveEntityContext,
    AliasMapping,
    CanonicalEntity,
    ConfirmedRelation,
    EntityTypeFact,
    Level1AuthoritySnapshot,
)

__all__ = [
    "ActiveEntityContext",
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
    confidence: float | None = None
    score: float | None = None
    chunk_id: int | None = None

    def __post_init__(self) -> None:
        if self.confidence is None:
            raw_confidence = self.metadata.get("confidence")
            self.confidence = float(raw_confidence) if raw_confidence is not None else None
        else:
            self.metadata.setdefault("confidence", self.confidence)

        if self.score is None:
            raw_score = self.metadata.get("score", self.metadata.get("similarity"))
            self.score = float(raw_score) if raw_score is not None else None
        else:
            self.metadata.setdefault("score", self.score)
            self.metadata.setdefault("similarity", self.score)

        if self.chunk_id is None:
            raw_chunk_id = self.metadata.get("chunk_id")
            self.chunk_id = int(raw_chunk_id) if raw_chunk_id is not None else None
        else:
            self.metadata.setdefault("chunk_id", self.chunk_id)


@dataclass(slots=True)
class EvidenceBundle:
    structured_evidence: list[EvidenceItem] = field(default_factory=list)
    local_evidence: list[EvidenceItem] = field(default_factory=list)
    semantic_evidence: list[EvidenceItem] = field(default_factory=list)
    requested_names: list[str] = field(default_factory=list)
    level1_snapshot: Level1AuthoritySnapshot | None = None
    request_meta: dict[str, Any] = field(default_factory=dict)
    generation_meta: dict[str, Any] = field(default_factory=dict)

    def clone_with_meta(
        self,
        *,
        request_meta: dict[str, Any] | None = None,
        generation_meta: dict[str, Any] | None = None,
    ) -> EvidenceBundle:
        """
        evidence service 需要在 cache reuse 时保留同一份证据内容，
              但用当前请求的 request_meta / generation_meta 重新打戳，避免不同 consumer 共用旧标签
        """

        return EvidenceBundle(
            structured_evidence=list(self.structured_evidence),
            local_evidence=list(self.local_evidence),
            semantic_evidence=list(self.semantic_evidence),
            requested_names=list(self.requested_names),
            level1_snapshot=self.level1_snapshot,
            request_meta=dict(request_meta if request_meta is not None else self.request_meta),
            generation_meta=dict(generation_meta if generation_meta is not None else self.generation_meta),
        )

    def structured_alias_map(self) -> dict[str, str]:
        alias_map: dict[str, str] = {}

        for item in self.structured_evidence:
            if item.evidence_type != "alias_mapping":
                continue
            alias = str(item.metadata.get("alias", "")).strip()
            canonical = str(item.metadata.get("canonical", "")).strip()
            if not alias or not canonical:
                parts = item.content.replace("->", "→").split("→", maxsplit=1)
                if len(parts) == 2:
                    alias = alias or parts[0].strip()
                    canonical = canonical or parts[1].strip()
            if alias and canonical:
                alias_map[alias] = canonical

        if alias_map:
            return alias_map

        if self.level1_snapshot is None:
            return {}

        return {
            mapping.alias: mapping.canonical
            for mapping in self.level1_snapshot.alias_mappings
            if mapping.alias and mapping.canonical and mapping.alias != mapping.canonical
        }
