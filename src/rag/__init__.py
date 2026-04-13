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
"""

from src.rag.authority import Level1AuthorityProvider
from src.rag.evidence_types import (
    ActiveEntityContext,
    AliasMapping,
    CanonicalEntity,
    ConfirmedRelation,
    EntityTypeFact,
    EvidenceBundle,
    EvidenceItem,
    Level1AuthoritySnapshot,
)
from src.rag.retriever import (
    ActiveEntityLookup,
    AliasLookup,
    DisambigContextProvider,
    DisambigResult,
    Level3NotReadyError,
    Level3VectorEvidence,
)

__all__ = [
    "DisambigContextProvider",
    "DisambigResult",
    "AliasLookup",
    "ActiveEntityLookup",
    "ActiveEntityContext",
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
]
