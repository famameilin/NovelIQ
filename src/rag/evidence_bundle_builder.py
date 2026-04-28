"""
RAG EvidenceBundle 组装器

将 structured/local/semantic evidence 的组装细节从 provider 主类中抽离
"""

from __future__ import annotations

from typing import TYPE_CHECKING, cast

from src.rag.evidence_types import EvidenceBundle, EvidenceItem

if TYPE_CHECKING:
    from src.knowledge.authority.types import ActiveEntityContext
    from src.rag.evidence_types import Level1AuthoritySnapshot
    from src.storage.repositories.chunk import SimilarChunkRow


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
                level1_snapshot=snapshot,
            )
        relevant_names = set(normalized_requested_names)
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
            requested_names=normalized_requested_names,
            level1_snapshot=snapshot,
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

    def build_active_entity_fallback_items(self, candidates: list[str]) -> list[EvidenceItem]:
        """构建缺少 authority view 时的 Level2 fallback items"""
        return [
            EvidenceItem(
                evidence_type="active_entity",
                source="graph_active_entities",
                content=name,
                metadata={"name": name},
            )
            for name in candidates
        ]

    def _build_semantic_recall_metadata(self, result: SimilarChunkRow) -> dict[str, object]:
        """
        冻结 Level3 semantic_recall 的 metadata 合同；即使某些字段当前为空，也保持键名稳定，
              便于后续日志观察、共享 renderer 和延期评测直接复用

        显式暴露 chunk / paragraph / business / final 分数，并删除已废弃的旧分数字段

        paragraph offset metadata 改为显式 local/global 字段，不再继续输出旧的歧义字段名

        冻结 LLM mention / query_variant / model rerank 观察字段，不改变 EvidenceBundle 主结构
        """
        chunk_semantic_score = (
            result.chunk_semantic_score
            if result.chunk_semantic_score is not None
            else result.similarity
        )
        paragraph_semantic_score = result.paragraph_semantic_score
        business_rerank_score = result.business_rerank_score
        final_rank_score = (
            result.final_rank_score
            if result.final_rank_score is not None
            else business_rerank_score
            if business_rerank_score is not None
            else paragraph_semantic_score
            if paragraph_semantic_score is not None
            else chunk_semantic_score
        )
        metadata: dict[str, object] = {
            "chunk_id": result.chunk_id,
            "text": result.text,
            "similarity": final_rank_score,
            "emotional_valence": result.emotional_valence,
            "evidence_granularity": "chunk",
            "rerank_method": "chunk_embedding",
            "chunk_text_len": len(result.text),
            "query_kind": result.query_kind,
            "mention_text": result.mention_text,
            "mention_type": result.mention_type,
            "mention_source": result.mention_source,
            "mention_confidence": result.mention_confidence,
            "query_variant": result.query_variant,
            "matched_features": list(result.matched_features),
            "feature_overlap": list(result.feature_overlap),
            "active_entity_bonus": result.active_entity_bonus,
            "identity_clue_bonus": result.identity_clue_bonus,
            "candidate_related_bonus": result.candidate_related_bonus,
            "time_decay": result.time_decay,
            "rerank_penalty": result.rerank_penalty,
            "penalties": list(result.penalties),
            "local_preview": result.local_preview,
            "paragraph_index": result.paragraph_index,
            "paragraph_local_start_char": result.paragraph_local_start_char,
            "paragraph_local_end_char": result.paragraph_local_end_char,
            "paragraph_global_start_char": result.paragraph_global_start_char,
            "paragraph_global_end_char": result.paragraph_global_end_char,
            "chunk_semantic_score": chunk_semantic_score,
            "paragraph_semantic_score": paragraph_semantic_score,
            "business_rerank_score": business_rerank_score,
            "model_rerank_score": result.model_rerank_score,
            "model_rerank_reason": result.model_rerank_reason,
            "model_confidence": result.model_confidence,
            "model_rerank_enabled": result.model_rerank_enabled,
            "rerank_source": result.rerank_source,
            "final_rank_score": final_rank_score,
        }
        if result.local_preview:
            metadata.update(
                {
                    "evidence_granularity": "paragraph",
                    "rerank_method": "chunk_then_paragraph",
                    "local_preview_len": len(result.local_preview),
                }
            )
        if result.business_rerank_score is not None:
            metadata["business_rerank_method"] = "mention_feature_rerank"
        if result.model_rerank_score is not None:
            metadata["rerank_method"] = "model_rerank"
        return metadata

    def build_semantic_recall_items(self, level3_results: list[SimilarChunkRow]) -> list[EvidenceItem]:
        """
        构建 Level3 通用语义召回证据

        mention query 产物额外写入 metadata，不改变 EvidenceBundle 主结构

        将 paragraph rerank 的局部 preview 与分数写入 metadata，供 renderer 优先展示局部 evidence

        写入 mention-aware rerank 分数与加权原因，便于后续评测和日志核对

        显式转换 final_rank_score，避免 metadata 的宽 object 类型影响静态检查
        """
        items: list[EvidenceItem] = []
        for result in level3_results:
            metadata = self._build_semantic_recall_metadata(result)
            final_rank_score = cast(float | int | str | None, metadata["final_rank_score"])
            items.append(
                EvidenceItem(
                    evidence_type="semantic_recall",
                    source="chunk_embeddings",
                    content=result.text,
                    metadata=metadata,
                    chunk_id=result.chunk_id,
                    score=float(final_rank_score) if final_rank_score is not None else None,
                )
            )
        return items

    def build_emotion_exemplar_items(self, level3_results: list[SimilarChunkRow]) -> list[EvidenceItem]:
        """
        构建用于情绪判断的 Level3 专用证据

        emotion exemplar 只消费 chunk 级语义召回，避免 mention 身份检索结果污染情绪证据

        paragraph rerank 仅影响 semantic_recall；emotion exemplar 继续使用 chunk 级分数，
                  避免局部 paragraph 分数污染整段 chunk 示例排序语义

        emotion exemplar 固定读取显式 chunk 语义分，避免 final/business 分数误入情绪示例排序
        """
        exemplar_items: list[EvidenceItem] = []
        for result in level3_results:
            if result.query_kind != "chunk":
                continue
            emotional_valence = result.emotional_valence
            if emotional_valence in (None, "", "neutral"):
                continue

            exemplar_similarity = (
                result.chunk_semantic_score
                if result.chunk_semantic_score is not None
                else result.similarity
            )
            metadata = {
                "chunk_id": result.chunk_id,
                "text": result.text,
                "similarity": exemplar_similarity,
                "emotional_valence": emotional_valence,
                "evidence_purpose": "emotion",
            }
            exemplar_items.append(
                EvidenceItem(
                    evidence_type="emotion_exemplar",
                    source="chunk_embeddings",
                    content=result.text,
                    metadata=metadata,
                    chunk_id=result.chunk_id,
                    score=exemplar_similarity,
                )
            )
        return sorted(exemplar_items, key=lambda item: item.score if item.score is not None else 0.0, reverse=True)
