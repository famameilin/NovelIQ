"""
创建时间: 2026-04-12
创建者: TraeAI
任务: 用户请求创建证据类型数据结构
说明: 定义 EvidenceItem、EvidenceBundle 和 Level1AuthoritySnapshot 等数据类型，用于 RAG 模块的证据管理
"""

from dataclasses import dataclass


@dataclass
class EvidenceItem:
    evidence_type: str
    source: str
    content: str
    score: float | None = None
    confidence: float | None = None
    chunk_id: int | None = None
    metadata: dict[str, str | int | float | bool | None] | None = None


@dataclass
class EvidenceBundle:
    structured_evidence: list[EvidenceItem]
    local_evidence: list[EvidenceItem]
    semantic_evidence: list[EvidenceItem]

    def to_prompt_blocks(self) -> dict[str, str]:
        """派生 prompt 视图，用于兼容旧链路
        
        修改时间: 2026-04-12
        修改者: TraeAI
        修改内容: 实现 disambig_candidates 和 vector_evidence 的格式化输出
        """
        result: dict[str, str] = {
            "disambig_candidates": "",
            "vector_evidence": "",
        }
        
        disambig_items = [
            item for item in self.local_evidence
            if item.evidence_type == "disambig_candidate"
        ]
        if disambig_items:
            lines = ["<Disambig_Candidates>"]
            for item in disambig_items:
                lines.append(f"- {item.content}")
            lines.append("</Disambig_Candidates>")
            result["disambig_candidates"] = "\n".join(lines)
        
        vector_items = [
            item for item in self.semantic_evidence
            if item.evidence_type == "vector_evidence"
        ]
        if vector_items:
            lines = ["<Vector_Evidence>"]
            lines.append("以下是与当前上下文语义相似的历史片段，可能存在身份关联：")
            for item in vector_items:
                chunk_id = item.chunk_id if item.chunk_id is not None else "?"
                similarity = item.score if item.score is not None else 0.0
                lines.append(f"[Chunk {chunk_id}] (相似度: {similarity:.2f})")
                lines.append(item.content)
            lines.append("</Vector_Evidence>")
            result["vector_evidence"] = "\n".join(lines)
        
        return result


@dataclass
class AliasMapping:
    alias: str
    canonical: str
    source: str
    confidence: float | None = None


@dataclass
class CanonicalEntity:
    name: str


@dataclass
class ConfirmedRelation:
    from_name: str
    to_name: str
    relation_type: str
    is_active: bool = True


@dataclass
class EntityTypeFact:
    name: str
    entity_type: str


@dataclass
class Level1AuthoritySnapshot:
    alias_mappings: list[AliasMapping]
    canonical_entities: list[CanonicalEntity]
    confirmed_relations: list[ConfirmedRelation]
    entity_types: list[EntityTypeFact]
