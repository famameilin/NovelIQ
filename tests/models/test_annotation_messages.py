from src.models.local.annotation.evidence_renderer import (
    render_annotation_evidence_blocks,
    render_foreshadowing_prompt_blocks,
)
from src.models.local.annotation.messages import (
    _build_annotation_messages_v2,
    _build_foreshadowing_messages,
)
from src.rag import (
    AliasMapping,
    CanonicalEntity,
    ConfirmedRelation,
    EntityTypeFact,
    EvidenceBundle,
    EvidenceItem,
    Level1AuthoritySnapshot,
)


def test_build_annotation_messages_prefers_structured_evidence_bundle_blocks() -> None:
    bundle = EvidenceBundle(
        structured_evidence=[
            EvidenceItem(
                evidence_type="alias_mapping",
                source="level1",
                content="阿七 → 贺重明",
                metadata={"alias": "阿七", "canonical": "贺重明"},
            ),
        ],
        local_evidence=[
            EvidenceItem(
                evidence_type="disambig_candidate",
                source="level2",
                content="「阿七」可能是：贺重明",
            ),
        ],
        semantic_evidence=[
            EvidenceItem(
                evidence_type="vector_evidence",
                source="level3",
                content="灰衣人站在门外。",
                chunk_id=7,
                score=0.88,
            ),
        ],
    )

    messages = _build_annotation_messages_v2(
        text="阿七抬头看向门外。",
        evidence_bundle=bundle,
    )

    user_content = messages[-1]["content"]
    assert "<Narrative_Evidence_Level1>" in user_content
    assert "已确认别名：阿七 -> 贺重明" in user_content
    assert "<Vector_Evidence>" in user_content


def test_render_annotation_evidence_blocks_keeps_phase1_prompt_shape() -> None:
    bundle = EvidenceBundle(
        structured_evidence=[
            EvidenceItem(
                evidence_type="alias_mapping",
                source="level1",
                content="阿七 → 贺重明",
                metadata={"alias": "阿七", "canonical": "贺重明"},
            ),
        ],
        local_evidence=[
            EvidenceItem(
                evidence_type="disambig_candidate",
                source="level2",
                content="「阿七」可能是：贺重明",
            ),
        ],
        semantic_evidence=[
            EvidenceItem(
                evidence_type="vector_evidence",
                source="level3",
                content="甲" * 220,
                chunk_id=7,
                score=0.88,
            ),
        ],
    )

    blocks = render_annotation_evidence_blocks(bundle)

    assert len(blocks) == 3
    assert blocks[0].startswith("<Structured_Evidence>")
    assert blocks[1].startswith("<Disambig_Candidates>")
    assert blocks[2].startswith("<Vector_Evidence>")
    assert ("甲" * 200) + "..." in blocks[2]


def _build_foreshadowing_bundle() -> EvidenceBundle:
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
            EvidenceItem(
                evidence_type="confirmed_relation",
                source="level1",
                content="白芷<盟友>侯飞白",
                metadata={
                    "from_name": "白芷",
                    "to_name": "侯飞白",
                    "relation_type": "盟友",
                    "is_active": True,
                },
            ),
            EvidenceItem(
                evidence_type="entity_type",
                source="level1",
                content="白芷:character",
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
                    "role": "other",
                    "recent_action": "观察",
                    "recent_emotion": "平静",
                    "last_seen_chunk": 11,
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
                metadata={
                    "chunk_id": 5,
                    "similarity": 0.92,
                    "text": "灰衣人抬手露出袖中银针。",
                },
            )
        ],
        requested_names=["灰衣人"],
        level1_snapshot=Level1AuthoritySnapshot(
            alias_mappings=[AliasMapping(alias="灰衣人", canonical="白芷")],
            canonical_entities=[CanonicalEntity(name="白芷", entity_type="character")],
            confirmed_relations=[ConfirmedRelation(from_name="白芷", to_name="侯飞白", relation_type="盟友")],
            entity_types=[EntityTypeFact(name="白芷", entity_type="character")],
        ),
    )


def test_render_foreshadowing_prompt_blocks_uses_level123_sections() -> None:
    bundle = _build_foreshadowing_bundle()

    blocks = render_foreshadowing_prompt_blocks(bundle)

    assert blocks.level1_facts is not None
    assert "<Narrative_Evidence_Level1>" in blocks.level1_facts
    assert "稳定实体事实" in blocks.level1_facts

    assert blocks.level2_context is not None
    assert "<Narrative_Evidence_Level2>" in blocks.level2_context
    assert "白芷" in blocks.level2_context
    assert "「灰衣人」可能是：白芷" not in blocks.level2_context

    assert blocks.level3_echoes is not None
    assert "<Narrative_Evidence_Level3>" in blocks.level3_echoes
    assert "anchor_text 必须来自<当前文本>" in blocks.level3_echoes


def test_build_foreshadowing_messages_appends_shared_evidence_sections() -> None:
    bundle = _build_foreshadowing_bundle()

    messages = _build_foreshadowing_messages(
        text="阿七摸到袖中发烫的玉佩，心里莫名发紧。",
        prev_chunk_text="前文提到他刚从旧宅出来。",
        next_chunk_text="后文写他在夜里被人追杀。",
        novel_title="归藏",
        main_characters="阿七、沈青禾",
        evidence_bundle=bundle,
    )

    user_content = messages[-1]["content"]
    assert "<Narrative_Evidence_Level1>" in user_content
    assert "<Narrative_Evidence_Level2>" in user_content
    assert "<Narrative_Evidence_Level3>" in user_content
    assert "稳定实体事实" in user_content
    assert "anchor_text 必须来自<当前文本>" in user_content
    assert "<Disambig_Candidates>" not in user_content


def test_build_foreshadowing_messages_without_bundle_keeps_prompt_shape() -> None:
    messages = _build_foreshadowing_messages(
        text="阿七摸到袖中发烫的玉佩，心里莫名发紧。",
        prev_chunk_text="前文提到他刚从旧宅出来。",
        next_chunk_text="后文写他在夜里被人追杀。",
    )

    user_content = messages[-1]["content"]
    assert "<Narrative_Evidence_Level1>" not in user_content
    assert "<Narrative_Evidence_Level2>" not in user_content
    assert "<Narrative_Evidence_Level3>" not in user_content
