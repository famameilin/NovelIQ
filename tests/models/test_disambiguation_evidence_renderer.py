from __future__ import annotations

from src.models.local.disambiguation import render_graph_feedback_hint
from src.rag import (
    AliasMapping,
    ConfirmedRelation,
    EvidenceBundle,
    EvidenceItem,
    Level1AuthoritySnapshot,
)


def test_render_graph_feedback_hint_excludes_inactive_relations() -> None:
    bundle = EvidenceBundle(
        level1_snapshot=Level1AuthoritySnapshot(
            alias_mappings=[AliasMapping(alias="灰衣人", canonical="白芷")],
            confirmed_relations=[
                ConfirmedRelation(
                    from_name="白芷",
                    to_name="侯飞白",
                    relation_type="盟友",
                    is_active=False,
                )
            ],
        )
    )

    hint = render_graph_feedback_hint(bundle, existing_names=["白芷"], base_hint="BASE")

    assert hint is not None
    assert "BASE" in hint
    assert "灰衣人 → 白芷" in hint
    assert "盟友" not in hint


def test_render_disambig_prompt_context_supports_legacy_candidate_and_vector_items() -> None:
    from src.models.local.disambiguation import render_disambig_prompt_context

    bundle = EvidenceBundle(
        local_evidence=[
            EvidenceItem(
                evidence_type="disambig_candidate",
                source="level2",
                content="「灰衣人」可能是：白芷、侯飞白",
            )
        ],
        semantic_evidence=[
            EvidenceItem(
                evidence_type="vector_evidence",
                source="level3",
                content="灰衣人抬手露出袖中银针。",
                chunk_id=5,
                score=0.92,
            )
        ],
    )

    rendered = render_disambig_prompt_context(bundle)

    assert rendered is not None
    assert "<Disambig_Candidates>" in rendered
    assert "「灰衣人」可能是：白芷、侯飞白" in rendered
    assert "<Vector_Evidence>" in rendered
