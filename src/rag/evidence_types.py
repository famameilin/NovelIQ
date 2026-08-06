from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, cast

from src.knowledge.authority import (
    ActiveEntityContext,
    CanonicalEntity,
    ConfirmedRelation,
    EntityTypeFact,
    Level1AuthoritySnapshot,
)
from src.rag.evidence_contracts import EvidenceRetrievalMethod

__all__ = [
    "ActiveEntityContext",
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
    evidence_id: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    confidence: float | None = None
    score: float | None = None
    chunk_id: int | None = None
    retrieval_method: EvidenceRetrievalMethod | None = None

    def __post_init__(self) -> None:
        if self.evidence_id is None:
            raw_evidence_id = self.metadata.get("evidence_id")
            self.evidence_id = str(raw_evidence_id) if raw_evidence_id else None
        else:
            self.metadata.setdefault("evidence_id", self.evidence_id)

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

        if self.retrieval_method is None:
            raw_retrieval_method = self.metadata.get("retrieval_method")
            self.retrieval_method = (
                cast(EvidenceRetrievalMethod, str(raw_retrieval_method))
                if raw_retrieval_method
                else None
            )
        elif self.retrieval_method is not None:
            self.metadata.setdefault("retrieval_method", self.retrieval_method)


@dataclass(slots=True)
class EvidenceBundle:
    structured_evidence: list[EvidenceItem] = field(default_factory=list)
    local_evidence: list[EvidenceItem] = field(default_factory=list)
    historical_evidence: list[EvidenceItem] = field(default_factory=list)
    requested_names: list[str] = field(default_factory=list)
    reference_slots: list[str] = field(default_factory=list)
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
            historical_evidence=list(self.historical_evidence),
            requested_names=list(self.requested_names),
            reference_slots=list(self.reference_slots),
            request_meta=dict(request_meta if request_meta is not None else self.request_meta),
            generation_meta=dict(generation_meta if generation_meta is not None else self.generation_meta),
        )
