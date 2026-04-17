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


def test_level1_authority_snapshot_creation():
    snapshot = Level1AuthoritySnapshot(
        alias_mappings=[AliasMapping(alias="张三", canonical="张三丰", source="graph")],
        canonical_entities=[CanonicalEntity(name="张三丰")],
        confirmed_relations=[ConfirmedRelation(from_name="张三丰", to_name="宋远桥", relation_type="师徒")],
        entity_types=[EntityTypeFact(name="张三丰", entity_type="character")],
    )
    assert len(snapshot.alias_mappings) == 1
    assert len(snapshot.canonical_entities) == 1
