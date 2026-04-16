from __future__ import annotations

import subprocess
import sys
from pathlib import Path

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


def test_importing_annotation_messages_in_fresh_interpreter_does_not_trigger_cycle() -> None:
    repo_root = Path(__file__).resolve().parents[2]
    result = subprocess.run(
        [sys.executable, "-c", "from src.models.local.annotation.messages import _build_annotation_messages_v2"],
        cwd=repo_root,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr


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


def test_render_disambig_prompt_context_falls_back_to_legacy_blocks_when_shared_renderer_returns_none() -> None:
    from src.models.local.disambiguation import render_disambig_prompt_context

    class CompatBundle:
        def render_disambig_candidates(self) -> str | None:
            return None

        def render_vector_evidence(self) -> str | None:
            return None

        def to_prompt_blocks(self) -> dict[str, str]:
            return {
                "structured_evidence": "",
                "disambig_candidates": "<Disambig_Candidates>\n- 「灰衣人」可能是：白芷\n</Disambig_Candidates>",
                "vector_evidence": "<Vector_Evidence>\nlegacy\n</Vector_Evidence>",
            }

    rendered = render_disambig_prompt_context(CompatBundle())

    assert rendered is not None
    assert "<Disambig_Candidates>" in rendered
    assert "<Vector_Evidence>" in rendered
