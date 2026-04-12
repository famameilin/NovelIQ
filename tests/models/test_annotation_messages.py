from src.models.local.annotation.messages import _build_annotation_messages_v2
from src.rag import EvidenceBundle, EvidenceItem


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
        active_entities="[]",
        disambig_context="<Legacy>should not be used</Legacy>",
        evidence_bundle=bundle,
    )

    user_content = messages[-1]["content"]
    assert "<Structured_Evidence>" in user_content
    assert "阿七 → 贺重明" in user_content
    assert "<Disambig_Candidates>" in user_content
    assert "<Vector_Evidence>" in user_content
    assert "<Legacy>should not be used</Legacy>" not in user_content
