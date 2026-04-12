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

修改时间: 2026-04-12
修改者: TraeAI
任务: 用户请求创建证据类型数据结构
修改内容: 导出 EvidenceItem、EvidenceBundle、Level1AuthoritySnapshot 等类型
"""

from src.rag.evidence_types import (
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
    "Level3NotReadyError",
    "Level3VectorEvidence",
    "EvidenceItem",
    "EvidenceBundle",
    "AliasMapping",
    "CanonicalEntity",
    "ConfirmedRelation",
    "EntityTypeFact",
    "Level1AuthoritySnapshot",
]
