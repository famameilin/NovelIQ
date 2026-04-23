"""
RAG EvidenceBundle 组装器。

创建时间: 2026-04-23
任务: p1-rag-retriever-split
说明: 将 structured/local/semantic evidence 的组装细节从 provider 主类中抽离。
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from src.rag.evidence_types import EvidenceBundle, EvidenceItem

if TYPE_CHECKING:
    from src.knowledge.authority.types import ActiveEntityContext
    from src.rag.evidence_types import Level1AuthoritySnapshot
    from src.storage.repositories.chunk import SimilarChunkRow


class EvidenceBundleBuilder:
    """
    EvidenceBundle 组装器。

    创建时间: 2026-04-23
    任务: p1-rag-retriever-split
    说明: 统一封装各层 evidence item 的构造，provider 只负责编排调用顺序。
    """

    def build_structured_bundle(
        self,
        snapshot: Level1AuthoritySnapshot,
        names_in_chunk: list[str] | None = None,
    ) -> EvidenceBundle:
        """按请求名字构建 Level1 structured evidence。"""
        requested_names = [name for name in (names_in_chunk or []) if name]
        relevant_names = set(requested_names)
        if relevant_names:
            related_canonicals = {
                mapping.canonical for mapping in snapshot.alias_mappings if mapping.alias in relevant_names
            }
            relevant_names |= related_canonicals

        structured_evidence: list[EvidenceItem] = []
        alias_mappings = snapshot.alias_mappings
        if relevant_names:
            alias_mappings = [
                mapping
                for mapping in snapshot.alias_mappings
                if mapping.alias in relevant_names or mapping.canonical in relevant_names
            ]
        for mapping in alias_mappings:
            structured_evidence.append(
                EvidenceItem(
                    evidence_type="alias_mapping",
                    source=mapping.source,
                    content=f"{mapping.alias} -> {mapping.canonical}",
                    metadata={
                        "alias": mapping.alias,
                        "canonical": mapping.canonical,
                        "confidence": mapping.confidence,
                    },
                )
            )

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
            requested_names=requested_names,
            level1_snapshot=snapshot,
        )

    def build_active_entity_items(self, active_entities: list[ActiveEntityContext]) -> list[EvidenceItem]:
        """构建 Level2 活跃实体 evidence items。"""
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

    def build_active_entity_fallback_items(self, candidates: list[str]) -> list[EvidenceItem]:
        """构建缺少 authority view 时的 Level2 fallback items。"""
        return [
            EvidenceItem(
                evidence_type="active_entity",
                source="graph_active_entities",
                content=name,
                metadata={"name": name},
            )
            for name in candidates
        ]

    def build_semantic_recall_items(self, level3_results: list[SimilarChunkRow]) -> list[EvidenceItem]:
        """
        构建 Level3 通用语义召回证据。

        修改时间: 2026-04-23
        任务: level3-mention-retrieval
        修改说明: mention query 产物额外写入 metadata，不改变 EvidenceBundle 主结构。

        修改时间: 2026-04-24
        任务: level3-paragraph-rerank
        修改说明: 将 paragraph rerank 的局部 preview 与分数写入 metadata，供 renderer 优先展示局部 evidence。
        """
        items: list[EvidenceItem] = []
        for result in level3_results:
            metadata = {
                "chunk_id": result.chunk_id,
                "text": result.text,
                "similarity": result.similarity,
                "emotional_valence": result.emotional_valence,
                "evidence_granularity": "chunk",
                "rerank_method": "chunk_embedding",
                "chunk_text_len": len(result.text),
            }
            if result.local_preview:
                metadata.update(
                    {
                        "evidence_granularity": "paragraph",
                        "rerank_method": "chunk_then_paragraph",
                        "local_preview": result.local_preview,
                        "local_preview_len": len(result.local_preview),
                        "paragraph_index": result.paragraph_index,
                        "paragraph_similarity": result.paragraph_similarity,
                        "paragraph_start_char": result.paragraph_start_char,
                        "paragraph_end_char": result.paragraph_end_char,
                        "chunk_similarity": result.chunk_similarity,
                    }
                )
            if result.query_kind == "mention":
                metadata.update(
                    {
                        "query_kind": "mention",
                        "mention_text": result.mention_text,
                        "mention_type": result.mention_type,
                        "matched_features": list(result.matched_features),
                    }
                )
            items.append(
                EvidenceItem(
                    evidence_type="semantic_recall",
                    source="chunk_embeddings",
                    content=result.text,
                    metadata=metadata,
                )
            )
        return items

    def build_emotion_exemplar_items(self, level3_results: list[SimilarChunkRow]) -> list[EvidenceItem]:
        """
        构建用于情绪判断的 Level3 专用证据。

        修改时间: 2026-04-23
        任务: level3-mention-review-fix
        修改说明: emotion exemplar 只消费 chunk 级语义召回，避免 mention 身份检索结果污染情绪证据。
        """
        exemplar_items: list[EvidenceItem] = []
        for result in level3_results:
            if result.query_kind != "chunk":
                continue
            emotional_valence = result.emotional_valence
            if emotional_valence in (None, "", "neutral"):
                continue

            metadata = {
                "chunk_id": result.chunk_id,
                "text": result.text,
                "similarity": result.similarity,
                "emotional_valence": emotional_valence,
                "evidence_purpose": "emotion",
            }
            exemplar_items.append(
                EvidenceItem(
                    evidence_type="emotion_exemplar",
                    source="chunk_embeddings",
                    content=result.text,
                    metadata=metadata,
                )
            )
        return exemplar_items
