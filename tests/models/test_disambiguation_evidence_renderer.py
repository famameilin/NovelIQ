from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from src.rag import (
    EvidenceBundle,
    EvidenceItem,
)


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


def test_render_disambig_candidates_uses_shared_bundle_fallback() -> None:
    from src.models.local.disambiguation import render_disambig_candidates

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
        requested_names=["灰衣人"],
    )

    rendered = render_disambig_candidates(bundle)

    assert rendered is not None
    assert "「灰衣人」可能是：白芷、侯飞白" in rendered


def test_render_disambig_prompt_context_returns_single_vector_block_when_no_candidates() -> None:
    from src.models.local.disambiguation import render_disambig_prompt_context

    bundle = EvidenceBundle(
        semantic_evidence=[
            EvidenceItem(
                evidence_type="semantic_recall",
                source="level3",
                content="灰衣人抬手露出袖中银针。",
                metadata={"chunk_id": 5, "text": "灰衣人抬手露出袖中银针。", "similarity": 0.92},
            )
        ]
    )

    rendered = render_disambig_prompt_context(bundle)

    assert rendered is not None
    assert rendered.startswith("<Vector_Evidence>")
    assert "<Disambig_Candidates>" not in rendered


def test_render_disambiguation_graph_hint_renders_aliases_and_relations() -> None:
    from src.models.local.disambiguation.evidence_renderer import render_disambiguation_graph_hint

    rendered = render_disambiguation_graph_hint(
        alias_map={"白老板": "白芷", "白芷": "白芷", "路人甲": "无关角色"},
        relations=[
            {"from_name": "白芷", "to_name": "侯飞白", "type": "盟友"},
            {"from_name": "无关角色", "to_name": "路人乙", "type": "路过"},
        ],
        existing_names=["白芷", "侯飞白"],
    )

    assert rendered is not None
    assert "【图谱已裁决的别名映射】" in rendered
    assert "- 白老板 → 白芷" in rendered
    assert "【图谱已确认的关系】" in rendered
    assert "- 白芷 ←盟友→ 侯飞白" in rendered
    assert "路人甲" not in rendered


def test_render_disambiguation_graph_hint_returns_none_when_no_relevant_facts() -> None:
    from src.models.local.disambiguation.evidence_renderer import render_disambiguation_graph_hint

    rendered = render_disambiguation_graph_hint(
        alias_map={"路人甲": "无关角色"},
        relations=[{"from_name": "无关角色", "to_name": "路人乙", "type": "路过"}],
        existing_names=["白芷"],
    )

    assert rendered is None


def test_render_disambiguation_prompt_context_sections_keeps_fixed_order() -> None:
    from src.models.local.disambiguation.evidence_renderer import (
        DisambiguationPromptContext,
        render_disambiguation_prompt_context_sections,
    )

    sections = render_disambiguation_prompt_context_sections(
        DisambiguationPromptContext(
            existing_character_hint="【已存在角色锚点】\n- 白芷",
            graph_hint="【图谱已确认的关系】\n- 白芷 ←盟友→ 侯飞白",
            shared_evidence_context="<Disambig_Candidates>\n「灰衣人」可能是：白芷\n</Disambig_Candidates>",
        )
    )

    assert sections == [
        "【已存在角色锚点】\n- 白芷",
        "【图谱已确认的关系】\n- 白芷 ←盟友→ 侯飞白",
        "<Disambig_Candidates>\n「灰衣人」可能是：白芷\n</Disambig_Candidates>",
    ]


def test_build_disambiguate_messages_renders_prompt_context_sections() -> None:
    from src.models.local.disambiguation.evidence_renderer import DisambiguationPromptContext
    from src.models.local.disambiguation.messages import build_disambiguate_messages

    messages = build_disambiguate_messages(
        candidates=[{"name": "灰衣人", "count": 3}],
        context_sentences={"灰衣人": "【身份线索】她自称白芷"},
        existing_names=["白芷"],
        prompt_context=DisambiguationPromptContext(
            existing_character_hint="【已存在角色锚点】\n- 白芷",
            graph_hint="【图谱已确认的关系】\n- 白芷 ←盟友→ 侯飞白",
            shared_evidence_context="<Vector_Evidence>\n[Chunk 5] 灰衣人忽然压低声音。\n</Vector_Evidence>",
        ),
    )

    user_content = messages[-1]["content"]
    assert "【已存在角色锚点】" in user_content
    assert "【图谱已确认的关系】" in user_content
    assert "<Vector_Evidence>" in user_content
    assert user_content.index("【已存在角色锚点】") < user_content.index("【图谱已确认的关系】")
    assert user_content.index("【图谱已确认的关系】") < user_content.index("<Vector_Evidence>")


def test_build_disambiguate_messages_filters_empty_prompt_context_sections() -> None:
    from src.models.local.disambiguation.evidence_renderer import DisambiguationPromptContext
    from src.models.local.disambiguation.messages import build_disambiguate_messages

    messages = build_disambiguate_messages(
        candidates=[{"name": "灰衣人", "count": 1}],
        context_sentences={"灰衣人": "她望向白芷。"},
        prompt_context=DisambiguationPromptContext(
            existing_character_hint="",
            graph_hint="【图谱已确认的关系】\n- 白芷 ←盟友→ 侯飞白",
            shared_evidence_context=None,
        ),
    )

    user_content = messages[-1]["content"]
    assert "【图谱已确认的关系】" in user_content
    assert "【已存在角色锚点】" not in user_content
