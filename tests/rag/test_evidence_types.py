"""
创建时间: 2026-04-12
创建者: TraeAI
任务: 用户请求创建证据类型测试
说明: 测试 EvidenceItem、EvidenceBundle 和 Level1AuthoritySnapshot 等数据类型
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


def test_evidence_item_creation():
    item = EvidenceItem(
        evidence_type="alias_mapping",
        source="level1",
        content="张三 → 张三丰",
        confidence=0.9,
    )
    assert item.evidence_type == "alias_mapping"
    assert item.source == "level1"
    assert item.content == "张三 → 张三丰"
    assert item.confidence == 0.9


def test_evidence_bundle_creation():
    bundle = EvidenceBundle(
        structured_evidence=[],
        local_evidence=[
            EvidenceItem(evidence_type="disambig_candidate", source="level2", content="「张三」可能是：张三丰、张三郎"),
        ],
        semantic_evidence=[],
    )
    assert len(bundle.local_evidence) == 1


def test_to_prompt_blocks_empty():
    bundle = EvidenceBundle(
        structured_evidence=[],
        local_evidence=[],
        semantic_evidence=[],
    )
    blocks = bundle.to_prompt_blocks()
    assert blocks["structured_evidence"] == ""
    assert blocks["disambig_candidates"] == ""
    assert blocks["vector_evidence"] == ""


def test_to_prompt_blocks_structured_evidence():
    bundle = EvidenceBundle(
        structured_evidence=[
            EvidenceItem(
                evidence_type="alias_mapping",
                source="level1",
                content="张三 → 张三丰",
                metadata={"alias": "张三", "canonical": "张三丰"},
            ),
        ],
        local_evidence=[],
        semantic_evidence=[],
    )
    blocks = bundle.to_prompt_blocks()
    assert "<Structured_Evidence>" in blocks["structured_evidence"]
    assert "张三 → 张三丰" in blocks["structured_evidence"]
    assert bundle.structured_alias_map() == {"张三": "张三丰"}


def test_to_prompt_blocks_disambig_candidates():
    bundle = EvidenceBundle(
        structured_evidence=[],
        local_evidence=[
            EvidenceItem(evidence_type="disambig_candidate", source="level2", content="「张三」可能是：张三丰、张三郎"),
            EvidenceItem(evidence_type="disambig_candidate", source="level2", content="「李四」可能是：李四郎"),
        ],
        semantic_evidence=[],
    )
    blocks = bundle.to_prompt_blocks()
    assert "<Disambig_Candidates>" in blocks["disambig_candidates"]
    assert "「张三」可能是：张三丰、张三郎" in blocks["disambig_candidates"]


def test_to_prompt_blocks_vector_evidence():
    bundle = EvidenceBundle(
        structured_evidence=[],
        local_evidence=[],
        semantic_evidence=[
            EvidenceItem(
                evidence_type="vector_evidence",
                source="level3",
                content="灰衣人缓缓转过身来...",
                chunk_id=42,
                score=0.85,
            ),
        ],
    )
    blocks = bundle.to_prompt_blocks()
    assert "<Vector_Evidence>" in blocks["vector_evidence"]
    assert "[Chunk 42]" in blocks["vector_evidence"]
    assert "0.85" in blocks["vector_evidence"]


def test_to_prompt_blocks_vector_evidence_is_bounded_like_legacy_formatter():
    bundle = EvidenceBundle(
        structured_evidence=[],
        local_evidence=[],
        semantic_evidence=[
            EvidenceItem(
                evidence_type="vector_evidence",
                source="level3",
                content="甲" * 250,
                chunk_id=index,
                score=0.9,
            )
            for index in range(5)
        ],
    )
    blocks = bundle.to_prompt_blocks()
    assert blocks["vector_evidence"].count("[Chunk") == 3
    assert ("甲" * 200) + "..." in blocks["vector_evidence"]


def test_level1_authority_snapshot_creation():
    snapshot = Level1AuthoritySnapshot(
        alias_mappings=[AliasMapping(alias="张三", canonical="张三丰", source="graph")],
        canonical_entities=[CanonicalEntity(name="张三丰")],
        confirmed_relations=[ConfirmedRelation(from_name="张三丰", to_name="宋远桥", relation_type="师徒")],
        entity_types=[EntityTypeFact(name="张三丰", entity_type="character")],
    )
    assert len(snapshot.alias_mappings) == 1
    assert len(snapshot.canonical_entities) == 1
