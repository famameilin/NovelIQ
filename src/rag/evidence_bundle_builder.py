"""
RAG EvidenceBundle 组装器

将 structured/local/historical evidence 的组装细节从 provider 主类中抽离
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from src.rag.evidence_types import EvidenceBundle, EvidenceItem

if TYPE_CHECKING:
    from src.knowledge.authority.types import ActiveEntityContext
    from src.rag.evidence_types import Level1AuthoritySnapshot
    from src.storage.repositories.chunk import KeywordMatchRow, SimilarParagraphRow


class EvidenceBundleBuilder:
    """
    EvidenceBundle 组装器

    统一封装各层 evidence item 的构造，provider 只负责编排调用顺序
    """

    def build_structured_bundle(
        self,
        snapshot: Level1AuthoritySnapshot,
        requested_names: list[str] | None = None,
    ) -> EvidenceBundle:
        """按请求名字构建 Level1 structured evidence"""
        normalized_requested_names = [name for name in (requested_names or []) if name]
        if requested_names is not None and not normalized_requested_names:
            # 显式传入空请求名表示“当前消费者没有可信实体锚点”，
            # 这里不能退回全量 Level1 事实，否则会把整本书的结构化事实误注入 direct-only 的消费者
            return EvidenceBundle(
                structured_evidence=[],
                requested_names=[],
            )
        relevant_names = set(normalized_requested_names)

        structured_evidence: list[EvidenceItem] = []
        canonical_entities = snapshot.canonical_entities
        if relevant_names:
            canonical_entities = [entity for entity in snapshot.canonical_entities if entity.name in relevant_names]
        for entity in canonical_entities:
            structured_evidence.append(
                EvidenceItem(
                    evidence_type="canonical_entity",
                    source=entity.source,
                    content=entity.name,
                    metadata={"name": entity.name, "entity_type": entity.entity_type},
                )
            )

        relations = snapshot.confirmed_relations
        if relevant_names:
            relations = [
                relation
                for relation in snapshot.confirmed_relations
                if relation.from_name in relevant_names or relation.to_name in relevant_names
            ]
        for relation in relations:
            structured_evidence.append(
                EvidenceItem(
                    evidence_type="confirmed_relation",
                    source=relation.source,
                    content=f"{relation.from_name}<{relation.relation_type}>{relation.to_name}",
                    metadata={
                        "from_name": relation.from_name,
                        "to_name": relation.to_name,
                        "relation_type": relation.relation_type,
                        "is_active": relation.is_active,
                        "first_seen_chunk": relation.first_seen_chunk,
                        "last_seen_chunk": relation.last_seen_chunk,
                        "support_count": relation.support_count,
                        "latest_event_id": relation.latest_event_id,
                    },
                )
            )

        entity_types = snapshot.entity_types
        if relevant_names:
            entity_types = [item for item in snapshot.entity_types if item.name in relevant_names]
        for item in entity_types:
            structured_evidence.append(
                EvidenceItem(
                    evidence_type="entity_type",
                    source=item.source,
                    content=f"{item.name}:{item.entity_type}",
                    metadata={"name": item.name, "entity_type": item.entity_type},
                )
            )

        return EvidenceBundle(
            structured_evidence=structured_evidence,
            requested_names=normalized_requested_names,
        )

    def build_active_entity_items(self, active_entities: list[ActiveEntityContext]) -> list[EvidenceItem]:
        """构建 Level2 活跃实体 evidence items"""
        return [
            EvidenceItem(
                evidence_type="active_entity",
                source=item.source,
                content=item.name,
                metadata={
                    "entity_id": item.entity_id,
                    "name": item.name,
                    "role": item.role,
                    "entity_type": item.entity_type,
                    "status": item.status,
                    "last_seen_chunk": item.last_seen_chunk,
                    "recent_action": item.recent_action,
                    "recent_emotion": item.recent_emotion,
                },
                chunk_id=item.last_seen_chunk,
            )
            for item in active_entities
        ]

    def build_paragraph_recall_items(self, level3_results: list[SimilarParagraphRow]) -> list[EvidenceItem]:
        """
        构建语义历史自然段证据
        """
        items: list[EvidenceItem] = []
        for result in level3_results:
            evidence_id = build_paragraph_evidence_id(
                result.chunk_id,
                result.paragraph_index,
                result.global_start_char,
                result.global_end_char,
            )
            metadata: dict[str, object] = {
                "evidence_id": evidence_id,
                "chunk_id": result.chunk_id,
                "paragraph_index": result.paragraph_index,
                "text": result.paragraph_text,
                "similarity": result.similarity,
                "evidence_granularity": "paragraph",
                "rerank_method": "paragraph_embedding",
                "paragraph_text_len": len(result.paragraph_text),
                "local_start_char": result.local_start_char,
                "local_end_char": result.local_end_char,
                "global_start_char": result.global_start_char,
                "global_end_char": result.global_end_char,
            }
            items.append(
                EvidenceItem(
                    evidence_type="semantic_recall",
                    source="paragraph_embeddings",
                    content=result.paragraph_text,
                    evidence_id=evidence_id,
                    metadata=metadata,
                    chunk_id=result.chunk_id,
                    score=result.similarity,
                    retrieval_method="semantic",
                )
            )
        return items

    def build_keyword_recall_items(self, matches: list[KeywordMatchRow]) -> list[EvidenceItem]:
        """
        构建关键词命中的历史自然段证据
        """
        return [
            EvidenceItem(
                evidence_type="keyword_recall",
                source="chunks.text",
                content=match.paragraph_text,
                evidence_id=build_paragraph_evidence_id(
                    match.chunk_id,
                    match.paragraph_index,
                    match.global_start_char,
                    match.global_end_char,
                ),
                metadata={
                    "paragraph_index": match.paragraph_index,
                    "local_start_char": match.local_start_char,
                    "local_end_char": match.local_end_char,
                    "global_start_char": match.global_start_char,
                    "global_end_char": match.global_end_char,
                    "matched_keywords": list(match.matched_keywords),
                    "match_count": match.match_count,
                    "evidence_granularity": "paragraph",
                },
                chunk_id=match.chunk_id,
                score=float(match.match_count),
                retrieval_method="keyword",
            )
            for match in matches
        ]

    def build_chunk_read_item(self, chunk_id: int, text: str) -> EvidenceItem:
        """
        构建受授权的历史 chunk 全文证据
        """
        evidence_id = f"chunk:{chunk_id}"
        return EvidenceItem(
            evidence_type="historical_chunk_read",
            source="chunks.text",
            content=text,
            evidence_id=evidence_id,
            metadata={"chunk_id": chunk_id, "evidence_granularity": "chunk"},
            chunk_id=chunk_id,
            retrieval_method="read",
        )


def build_paragraph_evidence_id(
    chunk_id: int,
    paragraph_index: int,
    global_start_char: int,
    global_end_char: int,
) -> str:
    """
    生成跨 keyword 与 semantic 共用的稳定段落证据 ID
    """
    return f"paragraph:{chunk_id}:{paragraph_index}:{global_start_char}:{global_end_char}"
