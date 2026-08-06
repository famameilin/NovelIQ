"""
重新导出 Level3VectorEvidence 与 NarrativeEvidenceService

RAG 检索粒度固定为一个自然段：只导出段落级向量检索与三级证据编排边界
"""

from src.rag.authority import Level1AuthorityProvider
from src.rag.evidence_contracts import (
    EvidenceConsumer,
    EvidenceObjective,
    EvidenceRequest,
    EvidenceRetrievalMethod,
    build_evidence_request_fingerprint,
)
from src.rag.evidence_types import (
    CanonicalEntity,
    ConfirmedRelation,
    EntityTypeFact,
    EvidenceBundle,
    EvidenceItem,
    Level1AuthoritySnapshot,
)
from src.rag.retriever import (
    ActiveEntityLookup,
    Level3NotReadyError,
    Level3VectorEvidence,
    NarrativeEvidenceService,
)

__all__ = [
    "NarrativeEvidenceService",
    "ActiveEntityLookup",
    "CanonicalEntity",
    "ConfirmedRelation",
    "EntityTypeFact",
    "EvidenceBundle",
    "EvidenceItem",
    "Level1AuthoritySnapshot",
    "Level1AuthorityProvider",
    "Level3NotReadyError",
    "Level3VectorEvidence",
    "EvidenceConsumer",
    "EvidenceObjective",
    "EvidenceRetrievalMethod",
    "EvidenceRequest",
    "build_evidence_request_fingerprint",
]
