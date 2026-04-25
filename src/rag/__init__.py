"""
创建时间: 2025-03-12
创建者: TraeAI
任务: RAG 模块初始化

修改时间: 2026-03-30
修改者: TraeAI
任务: 重命名 RAGRetriever → DisambigContextProvider，移除向量检索层

修改时间: 2026-04-10
修改者: TraeAI
任务: implement-level3-vector-retrieval
修改内容: 重新导出 Level3VectorEvidence

修改时间: 2026-04-24
任务: llm-mention-rerank-chain
修改内容: 导出 LLM mention extraction service 与模型 rerank 边界类型，供上层按需注入。
"""

from src.rag.authority import Level1AuthorityProvider
from src.rag.evidence_types import (
    AliasMapping,
    CanonicalEntity,
    ConfirmedRelation,
    EntityTypeFact,
    EvidenceBundle,
    EvidenceItem,
    Level1AuthoritySnapshot,
)
from src.rag.level3_contracts import (
    Level3Objective,
    Level3QueryPlan,
    Level3Request,
    build_level3_request_fingerprint,
)
from src.rag.mention_extraction_service import MentionExtractionService
from src.rag.mention_extraction_types import MentionExtractionRequest, PersonMention
from src.rag.model_rerank import Level3ModelReranker, Level3RerankCandidate, Level3RerankResult
from src.rag.model_rerank_llm import LLMLevel3Reranker
from src.rag.retriever import (
    ActiveEntityLookup,
    AliasLookup,
    DisambigContextProvider,
    Level3NotReadyError,
    Level3VectorEvidence,
)

__all__ = [
    "DisambigContextProvider",
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
    "Level3Objective",
    "Level3Request",
    "Level3QueryPlan",
    "build_level3_request_fingerprint",
    "MentionExtractionService",
    "MentionExtractionRequest",
    "PersonMention",
    "Level3RerankCandidate",
    "Level3RerankResult",
    "Level3ModelReranker",
    "LLMLevel3Reranker",
]
