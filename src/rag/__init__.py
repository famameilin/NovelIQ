"""


重新导出 Level3VectorEvidence

导出 LLM mention extraction service 与模型 rerank 边界类型，供上层按需注入

公开语义切换到 NarrativeEvidenceService；不再导出 DisambigContextProvider 旧命名
"""

from src.rag.authority import Level1AuthorityProvider
from src.rag.evidence_contracts import (
    EvidenceConsumer,
    EvidenceObjective,
    EvidenceRequest,
    Level3QueryPlan,
    build_evidence_request_fingerprint,
)
from src.rag.evidence_types import (
    AliasMapping,
    CanonicalEntity,
    ConfirmedRelation,
    EntityTypeFact,
    EvidenceBundle,
    EvidenceItem,
    Level1AuthoritySnapshot,
)
from src.rag.mention_extraction_service import MentionExtractionService
from src.rag.mention_extraction_types import MentionExtractionRequest, PersonMention
from src.rag.model_rerank import Level3ModelReranker, Level3RerankCandidate, Level3RerankResult
from src.rag.model_rerank_llm import LLMLevel3Reranker
from src.rag.retriever import (
    ActiveEntityLookup,
    AliasLookup,
    Level3NotReadyError,
    Level3VectorEvidence,
    NarrativeEvidenceService,
)

__all__ = [
    "NarrativeEvidenceService",
    "AliasLookup",
    "ActiveEntityLookup",
    "AliasMapping",
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
    "EvidenceRequest",
    "Level3QueryPlan",
    "build_evidence_request_fingerprint",
    "MentionExtractionService",
    "MentionExtractionRequest",
    "PersonMention",
    "Level3RerankCandidate",
    "Level3RerankResult",
    "Level3ModelReranker",
    "LLMLevel3Reranker",
]
