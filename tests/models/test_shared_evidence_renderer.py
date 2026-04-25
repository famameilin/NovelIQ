from __future__ import annotations

from src.knowledge.authority import (
    ActiveEntityContext,
    AliasMapping,
    CanonicalEntity,
    ConfirmedRelation,
    EntityTypeFact,
    Level1AuthoritySnapshot,
)
from src.models.local.evidence_renderer_shared import (
    render_active_entities_from_authority,
    render_shared_evidence_sections,
    select_shared_evidence_sections,
)
from src.rag import EvidenceBundle, EvidenceItem


def _build_bundle() -> EvidenceBundle:
    return EvidenceBundle(
        structured_evidence=[
            EvidenceItem(
                evidence_type="alias_mapping",
                source="level1",
                content="灰衣人 -> 白芷",
                metadata={"alias": "灰衣人", "canonical": "白芷"},
            ),
            EvidenceItem(
                evidence_type="canonical_entity",
                source="level1",
                content="白芷",
                metadata={"name": "白芷", "entity_type": "character"},
            ),
        ],
        local_evidence=[
            EvidenceItem(
                evidence_type="active_entity",
                source="level2",
                content="白芷",
                metadata={
                    "name": "白芷",
                    "role": "helper",
                    "recent_action": "观察",
                    "recent_emotion": "平静",
                    "last_seen_chunk": 12,
                },
            ),
            EvidenceItem(
                evidence_type="disambig_candidate",
                source="level2",
                content="「灰衣人」可能是：白芷",
            ),
        ],
        semantic_evidence=[
            EvidenceItem(
                evidence_type="semantic_recall",
                source="level3",
                content="灰衣人抬手露出袖中银针。",
                metadata={"chunk_id": 5, "text": "灰衣人抬手露出袖中银针。", "similarity": 0.92},
            )
        ],
        requested_names=["灰衣人"],
    )


def test_render_shared_evidence_sections_returns_all_base_sections() -> None:
    sections = render_shared_evidence_sections(_build_bundle())

    assert sections.structured_evidence is not None
    assert sections.level1_facts is not None
    assert sections.active_entities is not None
    assert sections.disambig_candidates is not None
    assert sections.vector_evidence is not None


def test_select_shared_evidence_sections_keeps_requested_order_and_filters_empty_values() -> None:
    sections = render_shared_evidence_sections(_build_bundle())

    selected = select_shared_evidence_sections(
        sections,
        ("active_entities", "level1_facts", "vector_evidence"),
    )

    assert len(selected) == 3
    assert selected[0].startswith("【近期活跃角色】")
    assert selected[1].startswith("<Narrative_Evidence_Level1>")
    assert selected[2].startswith("<Vector_Evidence>")


def test_render_shared_evidence_sections_can_suppress_level1_alias_lines() -> None:
    sections = render_shared_evidence_sections(
        _build_bundle(),
        include_level1_alias_mappings=False,
    )

    assert sections.level1_facts is not None
    assert "已确认别名：" not in sections.level1_facts
    assert "已确认实体：白芷" in sections.level1_facts


def test_render_shared_evidence_sections_snapshot_fallback_respects_empty_requested_names() -> None:
    """
    创建时间: 2026-04-26
    任务: fix-empty-requested-names-level1-fallback
    说明: 显式空 `requested_names` 表示当前 consumer 没有可信 Level1 目标；
          renderer 不应再从 snapshot 回退整本书的结构化事实。
    """
    bundle = EvidenceBundle(
        requested_names=[],
        level1_snapshot=Level1AuthoritySnapshot(
            alias_mappings=[AliasMapping(alias="灰衣人", canonical="白芷")],
            canonical_entities=[CanonicalEntity(name="白芷", entity_type="character")],
            confirmed_relations=[ConfirmedRelation(from_name="白芷", to_name="侯飞白", relation_type="盟友")],
            entity_types=[EntityTypeFact(name="白芷", entity_type="character")],
        ),
    )

    sections = render_shared_evidence_sections(bundle)

    assert sections.level1_facts is None


def test_render_shared_evidence_sections_snapshot_fallback_keeps_request_scoped_lines() -> None:
    """
    创建时间: 2026-04-26
    任务: fix-empty-requested-names-level1-fallback
    说明: snapshot-only bundle 仍可作为兼容输入，但只能渲染与 `requested_names`
          命中的 alias/canonical 相关的事实，不能回退成全量快照。
    """
    bundle = EvidenceBundle(
        requested_names=["灰衣人"],
        level1_snapshot=Level1AuthoritySnapshot(
            alias_mappings=[
                AliasMapping(alias="灰衣人", canonical="白芷"),
                AliasMapping(alias="旧代号", canonical="韩山"),
            ],
            canonical_entities=[
                CanonicalEntity(name="白芷", entity_type="character"),
                CanonicalEntity(name="韩山", entity_type="character"),
            ],
            confirmed_relations=[
                ConfirmedRelation(from_name="白芷", to_name="侯飞白", relation_type="盟友"),
                ConfirmedRelation(from_name="韩山", to_name="旧友", relation_type="同伴"),
            ],
            entity_types=[
                EntityTypeFact(name="白芷", entity_type="character"),
                EntityTypeFact(name="韩山", entity_type="character"),
            ],
        ),
    )

    sections = render_shared_evidence_sections(bundle)

    assert sections.level1_facts is not None
    assert "已确认别名：灰衣人 -> 白芷" in sections.level1_facts
    assert "已确认实体：白芷 (character)" in sections.level1_facts
    assert "已确认关系：白芷 -盟友-> 侯飞白" in sections.level1_facts
    assert "旧代号 -> 韩山" not in sections.level1_facts
    assert "已确认实体：韩山" not in sections.level1_facts


def test_render_shared_evidence_sections_respects_requested_name_filter_for_fallback_candidates() -> None:
    bundle = EvidenceBundle(
        local_evidence=[
            EvidenceItem(
                evidence_type="active_entity",
                source="level2",
                content="白芷",
                metadata={"name": "白芷"},
            ),
            EvidenceItem(
                evidence_type="active_entity",
                source="level2",
                content="侯飞白",
                metadata={"name": "侯飞白"},
            ),
        ],
        requested_names=["灰衣人", "旧别名"],
    )

    sections = render_shared_evidence_sections(
        bundle,
        fallback_requested_names={"灰衣人"},
    )

    assert sections.disambig_candidates is not None
    assert "「灰衣人」可能是：白芷、侯飞白" in sections.disambig_candidates
    assert "「旧别名」可能是" not in sections.disambig_candidates


def test_render_active_entities_from_authority_renders_without_temporary_bundle() -> None:
    rendered = render_active_entities_from_authority(
        [
            ActiveEntityContext(
                name="白芷",
                entity_id=7,
                role="helper",
                last_seen_chunk=12,
                recent_action="观察",
                recent_emotion="平静",
            )
        ]
    )

    assert rendered is not None
    assert rendered.startswith("【近期活跃角色】")
    assert "白芷" in rendered
    assert "[chunk=12]" in rendered


def test_render_shared_evidence_sections_can_render_emotion_exemplars_separately() -> None:
    bundle = EvidenceBundle(
        semantic_evidence=[
            EvidenceItem(
                evidence_type="semantic_recall",
                source="level3",
                content="她面无表情地收剑入鞘。",
                metadata={"chunk_id": 2, "text": "她面无表情地收剑入鞘。", "similarity": 0.87},
            ),
            EvidenceItem(
                evidence_type="emotion_exemplar",
                source="chunk_embeddings",
                content="她面带笑意，眸色却冷。",
                metadata={
                    "chunk_id": 9,
                    "text": "她面带笑意，眸色却冷。",
                    "similarity": 0.92,
                    "emotional_valence": "mild_negative",
                },
            ),
        ]
    )

    sections = render_shared_evidence_sections(bundle)

    assert sections.vector_evidence is not None
    assert sections.emotion_exemplars is not None
    assert "<Emotion_Exemplars>" in sections.emotion_exemplars
    assert "[Chunk 9]" in sections.emotion_exemplars


def test_render_shared_evidence_sections_can_exclude_vector_chunks_covered_by_emotion_exemplars() -> None:
    """
    创建时间: 2026-04-24
    任务: level3-mention-retrieval-closure
    说明: 共享 renderer 若要求 emotion exemplar 优先，应能按 chunk_id 排除同 chunk 的 vector evidence，
          避免同一历史片段重复占用两类证据预算。
    """
    bundle = EvidenceBundle(
        semantic_evidence=[
            EvidenceItem(
                evidence_type="semantic_recall",
                source="level3",
                content="她面带笑意，眸色却冷。",
                metadata={"chunk_id": 9, "text": "她面带笑意，眸色却冷。", "similarity": 0.92},
            ),
            EvidenceItem(
                evidence_type="semantic_recall",
                source="level3",
                content="她面无表情地收剑入鞘。",
                metadata={"chunk_id": 2, "text": "她面无表情地收剑入鞘。", "similarity": 0.87},
            ),
            EvidenceItem(
                evidence_type="emotion_exemplar",
                source="chunk_embeddings",
                content="她面带笑意，眸色却冷。",
                metadata={
                    "chunk_id": 9,
                    "text": "她面带笑意，眸色却冷。",
                    "similarity": 0.92,
                    "emotional_valence": "mild_negative",
                },
            ),
        ]
    )

    sections = render_shared_evidence_sections(
        bundle,
        exclude_vector_chunks_with_emotion_exemplars=True,
    )

    assert sections.vector_evidence is not None
    assert "[Chunk 2]" in sections.vector_evidence
    assert "[Chunk 9]" not in sections.vector_evidence
    assert sections.emotion_exemplars is not None
    assert "[Chunk 9]" in sections.emotion_exemplars


def test_render_shared_evidence_sections_prioritizes_background_entities_in_vector_evidence() -> None:
    """
    创建时间: 2026-04-25
    任务: evidence-service-request-unification
    说明: `background_entities` 只应作为 renderer 背景 hint 使用；
          这里验证它会优先展示和背景名更相关的 vector evidence，而不会回流到 requested_names/fallback。
    """
    bundle = EvidenceBundle(
        semantic_evidence=[
            EvidenceItem(
                evidence_type="semantic_recall",
                source="level3",
                content="陌生人翻过残墙，场景相似。",
                metadata={"chunk_id": 1, "text": "陌生人翻过残墙，场景相似。", "similarity": 0.93},
            ),
            EvidenceItem(
                evidence_type="semantic_recall",
                source="level3",
                content="白芷抬手按住袖中银针。",
                metadata={"chunk_id": 2, "text": "白芷抬手按住袖中银针。", "similarity": 0.89},
            ),
        ],
        request_meta={"background_entities": ["白芷"]},
    )

    sections = render_shared_evidence_sections(
        bundle,
        max_vector_chunks=1,
    )

    assert sections.vector_evidence is not None
    assert "[Chunk 2]" in sections.vector_evidence
    assert "[Chunk 1]" not in sections.vector_evidence
