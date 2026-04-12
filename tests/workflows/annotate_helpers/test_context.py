"""
创建时间: 2026-04-12
创建者: TraeAI
任务: 用户请求创建 ChunkContext 测试
说明: 测试 ChunkContext.evidence_bundle 字段和遗留兼容字段
"""

from src.rag.evidence_types import EvidenceBundle, EvidenceItem
from src.workflows.annotate_helpers.context import ChunkContext


def test_chunk_context_has_evidence_bundle():
    bundle = EvidenceBundle(
        structured_evidence=[],
        local_evidence=[],
        semantic_evidence=[],
    )
    context = ChunkContext(evidence_bundle=bundle)
    assert context.evidence_bundle is not None
    assert isinstance(context.evidence_bundle, EvidenceBundle)


def test_chunk_context_all_fields():
    bundle = EvidenceBundle(
        structured_evidence=[],
        local_evidence=[
            EvidenceItem(evidence_type="disambig_candidate", source="level2", content="「张三」可能是：张三丰"),
        ],
        semantic_evidence=[],
    )

    context = ChunkContext(
        prev_chunk_text="上一段文本",
        active_entities_str="活跃实体：张三、李四",
        disambig_context_str="<Disambig_Candidates>\n- 「张三」可能是：张三丰\n</Disambig_Candidates>",
        next_chunk_text="下一段文本",
        evidence_bundle=bundle,
    )

    assert context.prev_chunk_text == "上一段文本"
    assert context.active_entities_str == "活跃实体：张三、李四"
    assert context.disambig_context_str is not None
    assert context.evidence_bundle is not None


def test_chunk_context_evidence_bundle_default_none():
    context = ChunkContext()
    assert context.evidence_bundle is None


def test_chunk_context_all_fields_default_none():
    context = ChunkContext()
    assert context.prev_chunk_text is None
    assert context.active_entities_str is None
    assert context.disambig_context_str is None
    assert context.next_chunk_text is None
    assert context.vector_evidence_str is None
    assert context.evidence_bundle is None


def test_chunk_context_keeps_legacy_fields_optional():
    bundle = EvidenceBundle(
        structured_evidence=[],
        local_evidence=[
            EvidenceItem(evidence_type="disambig_candidate", source="level2", content="「张三」可能是：张三丰"),
            EvidenceItem(evidence_type="disambig_candidate", source="level2", content="「李四」可能是：李四郎"),
        ],
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

    context = ChunkContext(evidence_bundle=bundle)
    assert context.evidence_bundle is bundle
    assert context.disambig_context_str is None


def test_chunk_context_allows_explicit_legacy_disambig_context():
    bundle = EvidenceBundle(
        structured_evidence=[],
        local_evidence=[],
        semantic_evidence=[],
    )

    context = ChunkContext(
        evidence_bundle=bundle,
        disambig_context_str="<Legacy_Disambig />",
    )
    assert context.disambig_context_str == "<Legacy_Disambig />"


def test_chunk_context_vector_evidence_str_deprecated():
    context = ChunkContext(
        vector_evidence_str="旧的向量证据字符串",
    )
    assert context.vector_evidence_str == "旧的向量证据字符串"
    assert context.evidence_bundle is None


def test_chunk_context_evidence_bundle_with_structured_evidence():
    bundle = EvidenceBundle(
        structured_evidence=[
            EvidenceItem(evidence_type="alias_mapping", source="level1", content="张三 → 张三丰"),
        ],
        local_evidence=[],
        semantic_evidence=[],
    )

    context = ChunkContext(evidence_bundle=bundle)

    assert context.evidence_bundle is not None
    assert len(context.evidence_bundle.structured_evidence) == 1
    assert context.evidence_bundle.structured_evidence[0].evidence_type == "alias_mapping"
