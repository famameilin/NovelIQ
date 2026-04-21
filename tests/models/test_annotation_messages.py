from src.models.local.annotation.evidence_renderer import (
    render_annotation_evidence_blocks,
    render_annotation_prompt_blocks,
    render_dialogue_attribution_evidence_sections,
    render_relation_extraction_evidence_sections,
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
                content="阿七 -> 贺重明",
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
    assert "<Disambig_Candidates>" in user_content
    assert "「阿七」可能是：贺重明" in user_content
    assert "<Vector_Evidence>" in user_content


def test_render_annotation_prompt_blocks_can_drop_bundle_alias_lines_when_alias_map_is_explicit() -> None:
    bundle = EvidenceBundle(
        structured_evidence=[
            EvidenceItem(
                evidence_type="alias_mapping",
                source="level1",
                content="灰衣人 -> 白芷",
                metadata={"alias": "灰衣人", "canonical": "白芷"},
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
        ],
    )

    blocks = render_annotation_prompt_blocks(
        bundle,
        include_level1_alias_mappings=False,
    )

    assert blocks.disambig_context is not None
    assert "灰衣人 -> 白芷" not in blocks.disambig_context
    assert "已确认别名：" not in blocks.disambig_context
    assert "已确认关系：" in blocks.disambig_context


def test_render_annotation_evidence_blocks_keeps_phase1_prompt_shape() -> None:
    bundle = EvidenceBundle(
        structured_evidence=[
            EvidenceItem(
                evidence_type="alias_mapping",
                source="level1",
                content="阿七 -> 贺重明",
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


def _build_phase1_overflow_bundle() -> EvidenceBundle:
    structured = [
        EvidenceItem(
            evidence_type="alias_mapping",
            source="level1",
            content=f"别名{i} -> 人物{i}",
            metadata={"alias": f"别名{i}", "canonical": f"人物{i}"},
        )
        for i in range(1, 5)
    ]
    structured.extend(
        [
            EvidenceItem(
                evidence_type="canonical_entity",
                source="level1",
                content=f"人物{i}",
                metadata={"name": f"人物{i}", "entity_type": "character"},
            )
            for i in range(1, 4)
        ]
    )
    structured.extend(
        [
            EvidenceItem(
                evidence_type="confirmed_relation",
                source="level1",
                content=f"人物{i}<盟友>人物{i + 1}",
                metadata={
                    "from_name": f"人物{i}",
                    "to_name": f"人物{i + 1}",
                    "relation_type": "盟友",
                    "is_active": True,
                },
            )
            for i in range(1, 5)
        ]
    )

    local = [
        EvidenceItem(
            evidence_type="active_entity",
            source="level2",
            content=f"人物{i}",
            metadata={
                "name": f"人物{i}",
                "role": "other",
                "recent_action": f"动作{i}",
                "recent_emotion": f"情绪{i}",
                "last_seen_chunk": 20 - i,
            },
        )
        for i in range(1, 6)
    ]
    local.extend(
        [
            EvidenceItem(
                evidence_type="disambig_candidate",
                source="level2",
                content=f"「别名{i}」可能是：人物{i}",
            )
            for i in range(1, 5)
        ]
    )

    semantic = [
        EvidenceItem(
            evidence_type="semantic_recall",
            source="level3",
            content=f"人物{i}历史片段：" + ("甲" * 180),
            metadata={
                "chunk_id": i,
                "similarity": 0.93 - i * 0.01,
                "text": f"人物{i}历史片段：" + ("甲" * 180),
            },
        )
        for i in range(1, 4)
    ]

    return EvidenceBundle(
        structured_evidence=structured,
        local_evidence=local,
        semantic_evidence=semantic,
        requested_names=[f"别名{i}" for i in range(1, 5)],
    )


def test_build_foreshadowing_messages_appends_shared_evidence_blocks() -> None:
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
    assert "<Structured_Evidence>" in user_content
    assert "<Disambig_Candidates>" in user_content
    assert "<Vector_Evidence>" in user_content
    assert "<Narrative_Evidence_Level1>" not in user_content
    assert "<Narrative_Evidence_Level2>" not in user_content
    assert "<Narrative_Evidence_Level3>" not in user_content
    assert "【近期活跃角色】" not in user_content


def test_build_foreshadowing_messages_uses_disambig_fallback_from_requested_names() -> None:
    bundle = EvidenceBundle(
        local_evidence=[
            EvidenceItem(
                evidence_type="active_entity",
                source="level2",
                content="白芷",
                metadata={"name": "白芷", "role": "other"},
            ),
            EvidenceItem(
                evidence_type="active_entity",
                source="level2",
                content="侯飞白",
                metadata={"name": "侯飞白", "role": "other"},
            ),
        ],
        requested_names=["灰衣人"],
    )

    messages = _build_foreshadowing_messages(
        text="灰衣人忽然掠过墙头。",
        evidence_bundle=bundle,
    )

    user_content = messages[-1]["content"]
    assert "<Disambig_Candidates>" in user_content
    assert "「灰衣人」可能是：白芷、侯飞白" in user_content
    assert "【近期活跃角色】" not in user_content
    assert "<Narrative_Evidence_Level1>" not in user_content


def test_render_annotation_prompt_blocks_trims_phase1_shared_evidence_context() -> None:
    blocks = render_annotation_prompt_blocks(_build_phase1_overflow_bundle())

    assert blocks.active_entities is not None
    assert blocks.disambig_context is not None

    active_section = blocks.active_entities
    disambig_context = blocks.disambig_context

    level1_start = disambig_context.index("<Narrative_Evidence_Level1>")
    disambig_start = disambig_context.index("<Disambig_Candidates>")
    vector_start = disambig_context.index("<Vector_Evidence>")
    level1_section = disambig_context[level1_start:disambig_start]
    disambig_section = disambig_context[disambig_start:vector_start]
    vector_section = disambig_context[vector_start:]

    assert sum(1 for line in active_section.splitlines() if line.startswith("- ")) == 4
    assert sum(1 for line in level1_section.splitlines() if line.startswith("- ")) == 8
    assert sum(1 for line in level1_section.splitlines() if "已确认别名：" in line) == 3
    assert sum(1 for line in level1_section.splitlines() if "已确认实体：" in line) == 2
    assert sum(1 for line in level1_section.splitlines() if "已确认关系：" in line) == 3
    assert sum(1 for line in disambig_section.splitlines() if line.startswith("「")) == 3
    assert vector_section.count("[Chunk ") == 2
    assert "[Chunk 3]" not in vector_section
    assert "..." in vector_section


def test_build_foreshadowing_messages_without_bundle_keeps_prompt_shape() -> None:
    messages = _build_foreshadowing_messages(
        text="阿七摸到袖中发烫的玉佩，心里莫名发紧。",
        prev_chunk_text="前文提到他刚从旧宅出来。",
        next_chunk_text="后文写他在夜里被人追杀。",
    )

    user_content = messages[-1]["content"]
    assert "<Structured_Evidence>" not in user_content
    assert "<Disambig_Candidates>" not in user_content
    assert "<Vector_Evidence>" not in user_content


def test_build_foreshadowing_messages_with_empty_bundle_sections_keeps_prompt_clean() -> None:
    messages = _build_foreshadowing_messages(
        text="阿七摸到袖中发烫的玉佩，心里莫名发紧。",
        evidence_bundle=EvidenceBundle(),
    )

    user_content = messages[-1]["content"]
    assert "<Structured_Evidence>" not in user_content
    assert "<Disambig_Candidates>" not in user_content
    assert "<Vector_Evidence>" not in user_content
    assert "【近期活跃角色】" not in user_content


def test_render_annotation_prompt_blocks_includes_emotion_exemplars_only_for_phase1() -> None:
    bundle = EvidenceBundle(
        semantic_evidence=[
            EvidenceItem(
                evidence_type="semantic_recall",
                source="level3",
                content="她抬眼时神色冷得惊人。",
                metadata={
                    "chunk_id": 6,
                    "similarity": 0.89,
                    "text": "她抬眼时神色冷得惊人。",
                },
            ),
            EvidenceItem(
                evidence_type="emotion_exemplar",
                source="chunk_embeddings",
                content="她唇角含笑，眼底却没有温度。",
                metadata={
                    "chunk_id": 6,
                    "similarity": 0.91,
                    "text": "她唇角含笑，眼底却没有温度。",
                    "emotional_valence": "mild_negative",
                },
            ),
        ]
    )

    phase1_blocks = render_annotation_prompt_blocks(bundle)
    phase3_sections = render_dialogue_attribution_evidence_sections(bundle)
    phase4_sections = render_relation_extraction_evidence_sections(bundle)

    assert phase1_blocks.disambig_context is not None
    assert "<Emotion_Exemplars>" in phase1_blocks.disambig_context
    assert phase1_blocks.vector_evidence is None
    assert "<Vector_Evidence>" not in phase1_blocks.disambig_context
    assert all("<Emotion_Exemplars>" not in section for section in phase3_sections)
    assert all("<Emotion_Exemplars>" not in section for section in phase4_sections)
    assert any("<Vector_Evidence>" in section and "[Chunk 6]" in section for section in phase3_sections)
    assert any("<Vector_Evidence>" in section and "[Chunk 6]" in section for section in phase4_sections)
