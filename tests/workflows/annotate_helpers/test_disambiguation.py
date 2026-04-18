from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.models.local.disambiguation import (
    DisambiguationPromptContext,
    DisambiguationState,
    ExtendedDisambigResult,
    build_evidence_profile,
)
from src.rag import EvidenceBundle, EvidenceItem
from src.workflows.annotate_helpers import disambiguation as disambig_mod
from src.workflows.annotate_helpers.disambiguation import pipeline as pipeline_mod


def _candidates(*names: str) -> list[dict[str, int | str]]:
    return [{"name": name, "count": 1} for name in names]


class _FakeDisambigClient:
    def __init__(self) -> None:
        self._config = SimpleNamespace(model="test-model")
        self.received_existing_names: list[str] | None = None
        self.received_prompt_context: DisambiguationPromptContext | None = None

    async def disambiguate_characters(
        self,
        candidates,
        context_sentences=None,
        existing_names=None,
        prompt_context=None,
    ):
        self.received_existing_names = existing_names
        self.received_prompt_context = prompt_context
        return ExtendedDisambigResult(canonical_decisions={}, entity_types={}, entity_relations=[])

    def is_cloud_api(self) -> bool:
        return False


class _FakeRagRetriever:
    def __init__(
        self,
        bundle: EvidenceBundle,
        *,
        level3_available: bool = True,
        requires_level3: bool = False,
    ) -> None:
        self.bundle = bundle
        self.level3_available = level3_available
        self._requires_level3 = requires_level3
        self.calls: list[dict] = []

    def requires_level3(self) -> bool:
        return self._requires_level3

    def is_level3_available(self) -> bool:
        return self.level3_available

    def collect_evidence(self, names_in_chunk=None, current_chunk=None):
        self.calls.append(
            {
                "method": "collect_evidence",
                "names_in_chunk": list(names_in_chunk or []),
                "current_chunk": current_chunk,
            }
        )
        return self.bundle

    async def collect_evidence_with_level3(
        self,
        names_in_chunk=None,
        current_chunk=None,
        context_text=None,
        exclude_chunk_ids=None,
    ):
        self.calls.append(
            {
                "method": "collect_evidence_with_level3",
                "names_in_chunk": list(names_in_chunk or []),
                "current_chunk": current_chunk,
                "context_text": context_text,
                "exclude_chunk_ids": list(exclude_chunk_ids or []),
            }
        )
        return self.bundle


@pytest.mark.asyncio
async def test_retry_disambig_passes_existing_names_to_client() -> None:
    client = _FakeDisambigClient()

    with patch("src.workflows.annotate_helpers.disambiguation.pipeline.record_model_interaction"):
        await disambig_mod._retry_disambig(
            client=client,
            candidates=_candidates("masked_person"),
            context_sentences={"masked_person": "identity reveal in scene"},
            existing_names=["bai_zhi", "hou_fei_bai"],
            stage_name="incremental disambiguation",
            run_id="run-1",
            prompt_context=DisambiguationPromptContext(existing_character_hint="anchor hint"),
        )

    assert client.received_existing_names == ["bai_zhi", "hou_fei_bai"]
    assert client.received_prompt_context is not None
    assert client.received_prompt_context.existing_character_hint == "anchor hint"


def test_validate_confidence_with_evidence_promotes_unique_marker_merge() -> None:
    context = (
        "【前文总结】贺伯安为救同伴被火焰吞噬昏迷\n赵兰英想起贺伯安脊椎处的白金火焰符号，怀里的婴孩脊椎处也有同样印记"
    )
    result = ExtendedDisambigResult(
        canonical_decisions={"婴儿": "婴儿"},
        entity_types={"婴儿": "character"},
        entity_relations=[],
        alias_confidence={"婴儿": "medium"},
        evidence_profiles={"婴儿": build_evidence_profile(context)},
    )

    validated = disambig_mod.validate_confidence_with_evidence(result, ["贺伯安"], {"婴儿": context})

    assert validated.canonical_decisions["婴儿"] == "贺伯安"
    assert validated.alias_confidence["婴儿"] == "high"


def test_validate_confidence_with_evidence_does_not_merge_on_suffix_only_anchor_match() -> None:
    context = "王伯安肩头旧伤发作，额间冷汗密布"
    result = ExtendedDisambigResult(
        canonical_decisions={"灰衣公子": "灰衣公子"},
        entity_types={"灰衣公子": "character"},
        entity_relations=[],
        alias_confidence={"灰衣公子": "medium"},
        evidence_profiles={"灰衣公子": build_evidence_profile(context)},
    )

    validated = disambig_mod.validate_confidence_with_evidence(result, ["贺伯安"], {"灰衣公子": context})

    assert validated.canonical_decisions["灰衣公子"] == "灰衣公子"
    assert validated.alias_confidence["灰衣公子"] == "medium"


def test_collect_final_disambiguation_candidates_prefers_state_snapshot() -> None:
    snapshot = {
        "bai_zhi": {"state": "resolved", "confidence": "high", "canonical": "bai_zhi"},
        "lin_li_guo": {"state": "review", "confidence": "medium", "canonical": "bai_zhi"},
        "masked_person": {"state": "unresolved", "confidence": "low", "canonical": "bai_zhi"},
    }
    candidates = disambig_mod._collect_final_disambiguation_candidates(
        all_names=_candidates("bai_zhi", "lin_li_guo", "masked_person"),
        alias_map={"bai_zhi": "bai_zhi"},
        state_snapshot=snapshot,
    )
    assert set(candidates) == {"lin_li_guo", "masked_person"}


def test_collect_final_disambiguation_candidates_rereviews_self_resolved_extension_name() -> None:
    snapshot = {
        "伯安": {"state": "resolved", "confidence": "high", "canonical": "伯安"},
        "贺伯安": {"state": "resolved", "confidence": "high", "canonical": "贺伯安"},
    }
    candidates = disambig_mod._collect_final_disambiguation_candidates(
        all_names=[
            {"name": "伯安", "count": 33},
            {"name": "贺伯安", "count": 8},
        ],
        alias_map={"伯安": "伯安", "贺伯安": "贺伯安"},
        state_snapshot=snapshot,
    )
    assert candidates == ["贺伯安"]


@pytest.mark.asyncio
async def test_record_model_interaction_with_disambiguation() -> None:
    client = _FakeDisambigClient()

    with patch("src.workflows.annotate_helpers.disambiguation.pipeline.record_model_interaction") as mock_record:
        await disambig_mod._retry_disambig(
            client=client,
            candidates=_candidates("masked_person"),
            context_sentences={"masked_person": "scene"},
            existing_names=["bai_zhi"],
            stage_name="final disambiguation",
            run_id="run-1",
            prompt_context=DisambiguationPromptContext(existing_character_hint="anchor hint"),
        )

    mock_record.assert_called_once()
    call_kwargs = mock_record.call_args.kwargs
    assert call_kwargs["model_name"] == "test-model"
    assert call_kwargs["interaction_type"] == "disambiguate"


@pytest.mark.asyncio
async def test_incremental_pipeline_builds_shared_evidence_prompt_context() -> None:
    client = _FakeDisambigClient()
    state = DisambiguationState.empty().with_updates(known_canonical_names=frozenset({"白芷"}))
    rag_retriever = _FakeRagRetriever(
        EvidenceBundle(
            local_evidence=[
                EvidenceItem(
                    evidence_type="active_entity",
                    source="level2",
                    content="白芷",
                    metadata={"name": "白芷"},
                )
            ],
            semantic_evidence=[
                EvidenceItem(
                    evidence_type="semantic_recall",
                    source="chunk_embeddings",
                    content="灰衣人抬手露出袖中银针。",
                    metadata={"chunk_id": 5, "text": "灰衣人抬手露出袖中银针。", "similarity": 0.92},
                )
            ],
            requested_names=["灰衣人"],
        )
    )

    with (
        patch(
            "src.workflows.annotate_helpers.disambiguation.pipeline.extract_new_names_from_db",
            return_value=[{"name": "灰衣人", "count": 3}],
        ),
        patch(
            "src.workflows.annotate_helpers.disambiguation.pipeline.build_context_sentences",
            return_value={"灰衣人": "【身份线索】她自称白芷"},
        ),
        patch(
            "src.workflows.annotate_helpers.disambiguation.pipeline.filter_candidates_by_class",
            return_value=([], [{"name": "灰衣人", "count": 3}], []),
        ),
        patch(
            "src.workflows.annotate_helpers.disambiguation.pipeline._build_existing_character_hint_from_db",
            return_value=DisambiguationPromptContext(
                existing_character_hint="【已存在角色锚点】\n- 白芷",
                graph_hint="【图谱已确认的关系】\n- 白芷 ←盟友→ 侯飞白",
            ),
        ),
        patch(
            "src.workflows.annotate_helpers.disambiguation.pipeline._fetch_current_relations",
            return_value=[],
        ),
        patch(
            "src.workflows.annotate_helpers.disambiguation.pipeline.validate_confidence_with_evidence",
            side_effect=lambda result, *_: result,
        ),
        patch(
            "src.workflows.annotate_helpers.disambiguation.pipeline.align_canonical_by_frequency",
            side_effect=lambda result, *_args, **_kwargs: result,
        ),
        patch(
            "src.workflows.annotate_helpers.disambiguation.pipeline.apply_disambiguation_decisions",
            return_value=state,
        ),
        patch(
            "src.workflows.annotate_helpers.disambiguation.pipeline._generate_and_save_stage_summary",
            new=AsyncMock(),
        ),
        patch("src.workflows.annotate_helpers.disambiguation.pipeline.record_model_interaction") as mock_record,
    ):
        new_state = await disambig_mod._run_incremental_disambiguation_with_state(
            conn=MagicMock(),
            state=state,
            incremental_disambig_client=client,
            alias_keywords=["号"],
            novel_id="novel-1",
            run_id="run-1",
            chunk_id=12,
            current_idx=2,
            disambig_interval=3,
            rag_retriever=rag_retriever,
        )

    assert new_state is state
    assert client.received_prompt_context is not None
    assert client.received_prompt_context.shared_evidence_context is not None
    assert "<Disambig_Candidates>" in client.received_prompt_context.shared_evidence_context
    assert "<Vector_Evidence>" in client.received_prompt_context.shared_evidence_context
    assert rag_retriever.calls[0]["method"] == "collect_evidence_with_level3"
    assert rag_retriever.calls[0]["current_chunk"] == 12
    assert rag_retriever.calls[0]["exclude_chunk_ids"] == [12]

    user_content = mock_record.call_args.kwargs["messages"][-1]["content"]
    assert "【已存在角色锚点】" in user_content
    assert "【图谱已确认的关系】" in user_content
    assert "<Disambig_Candidates>" in user_content
    assert "<Vector_Evidence>" in user_content


@pytest.mark.asyncio
async def test_final_pipeline_builds_shared_evidence_prompt_context() -> None:
    client = _FakeDisambigClient()
    state = DisambiguationState.empty().with_updates(known_canonical_names=frozenset({"白芷"}))
    rag_retriever = _FakeRagRetriever(
        EvidenceBundle(
            semantic_evidence=[
                EvidenceItem(
                    evidence_type="semantic_recall",
                    source="chunk_embeddings",
                    content="灰衣人忽然压低声音。",
                    metadata={"chunk_id": 9, "text": "灰衣人忽然压低声音。", "similarity": 0.91},
                )
            ],
            requested_names=["灰衣人"],
        )
    )

    with (
        patch(
            "src.workflows.annotate_helpers.disambiguation.pipeline.fetch_all_character_names",
            return_value=[{"name": "灰衣人", "count": 3}],
        ),
        patch(
            "src.workflows.annotate_helpers.disambiguation.pipeline._collect_final_disambiguation_candidates",
            return_value=["灰衣人"],
        ),
        patch(
            "src.workflows.annotate_helpers.disambiguation.pipeline.build_context_sentences",
            return_value={"灰衣人": "【身份线索】她望向白芷"},
        ),
        patch(
            "src.workflows.annotate_helpers.disambiguation.pipeline.filter_candidates_by_class",
            return_value=([], [{"name": "灰衣人", "count": 3}], []),
        ),
        patch(
            "src.workflows.annotate_helpers.disambiguation.pipeline._build_existing_character_hint_from_db",
            return_value=DisambiguationPromptContext(
                existing_character_hint="【已存在角色锚点】\n- 白芷",
                graph_hint="【图谱已确认的关系】\n- 白芷 ←盟友→ 侯飞白",
            ),
        ),
        patch(
            "src.workflows.annotate_helpers.disambiguation.pipeline._fetch_current_relations",
            return_value=[],
        ),
        patch(
            "src.workflows.annotate_helpers.disambiguation.pipeline.validate_confidence_with_evidence",
            side_effect=lambda result, *_: result,
        ),
        patch(
            "src.workflows.annotate_helpers.disambiguation.pipeline.align_canonical_by_frequency",
            side_effect=lambda result, *_args, **_kwargs: result,
        ),
        patch(
            "src.workflows.annotate_helpers.disambiguation.pipeline.apply_disambiguation_decisions",
            return_value=state,
        ),
        patch(
            "src.workflows.annotate_helpers.disambiguation.pipeline.AnnotationRepository"
        ) as mock_repo_cls,
        patch("src.workflows.annotate_helpers.disambiguation.pipeline._save_disambig_checkpoint"),
        patch("src.workflows.annotate_helpers.disambiguation.pipeline.record_model_interaction") as mock_record,
    ):
        mock_repo = MagicMock()
        mock_repo_cls.return_value = mock_repo

        new_state = await disambig_mod._run_final_disambiguation_with_state(
            conn=MagicMock(),
            state=state,
            full_disambig_client=client,
            alias_keywords=["号"],
            novel_id="novel-1",
            run_id="run-1",
            rag_retriever=rag_retriever,
        )

    assert new_state.known_canonical_names == state.known_canonical_names
    assert client.received_prompt_context is not None
    assert client.received_prompt_context.shared_evidence_context is not None
    assert "<Vector_Evidence>" in client.received_prompt_context.shared_evidence_context
    assert rag_retriever.calls[0]["method"] == "collect_evidence_with_level3"
    assert rag_retriever.calls[0]["current_chunk"] is None

    user_content = mock_record.call_args.kwargs["messages"][-1]["content"]
    assert "【已存在角色锚点】" in user_content
    assert "【图谱已确认的关系】" in user_content
    assert "<Vector_Evidence>" in user_content


@pytest.mark.asyncio
async def test_build_prompt_context_with_shared_evidence_falls_back_to_level12_when_required_level3_unavailable() -> None:
    rag_retriever = _FakeRagRetriever(
        EvidenceBundle(
            local_evidence=[
                EvidenceItem(
                    evidence_type="active_entity",
                    source="level2",
                    content="白芷",
                    metadata={"name": "白芷"},
                )
            ],
            requested_names=["灰衣人"],
        ),
        level3_available=False,
        requires_level3=True,
    )

    with patch("src.workflows.annotate_helpers.disambiguation.pipeline.logger.warning") as mock_warning:
        prompt_context = await pipeline_mod._build_prompt_context_with_shared_evidence(
            DisambiguationPromptContext(existing_character_hint="【已存在角色锚点】\n- 白芷"),
            rag_retriever,
            [{"name": "灰衣人", "count": 3}],
            {"灰衣人": "【身份线索】她自称白芷"},
            current_chunk=12,
            active_entity_fallback_names={"灰衣人"},
        )

    assert prompt_context is not None
    assert prompt_context.shared_evidence_context is not None
    assert "<Disambig_Candidates>" in prompt_context.shared_evidence_context
    assert rag_retriever.calls[0]["method"] == "collect_evidence"
    mock_warning.assert_called_once()


@pytest.mark.asyncio
async def test_incremental_pipeline_skips_active_entity_fallback_for_review_candidates() -> None:
    client = _FakeDisambigClient()
    state = DisambiguationState.empty().with_updates(known_canonical_names=frozenset({"白芷"}))
    rag_retriever = _FakeRagRetriever(
        EvidenceBundle(
            local_evidence=[
                EvidenceItem(
                    evidence_type="active_entity",
                    source="level2",
                    content="白芷",
                    metadata={"name": "白芷"},
                )
            ],
            semantic_evidence=[
                EvidenceItem(
                    evidence_type="semantic_recall",
                    source="chunk_embeddings",
                    content="旧别名在早期章节里提过白芷。",
                    metadata={"chunk_id": 3, "text": "旧别名在早期章节里提过白芷。", "similarity": 0.88},
                )
            ],
            requested_names=["旧别名"],
        )
    )

    with (
        patch(
            "src.workflows.annotate_helpers.disambiguation.pipeline.extract_new_names_from_db",
            return_value=[],
        ),
        patch(
            "src.workflows.annotate_helpers.disambiguation.pipeline._collect_review_candidates",
            return_value=[{"name": "旧别名", "count": 1}],
        ),
        patch(
            "src.workflows.annotate_helpers.disambiguation.pipeline.build_context_sentences",
            return_value={"旧别名": "【身份线索】她曾被叫作白姑娘"},
        ),
        patch(
            "src.workflows.annotate_helpers.disambiguation.pipeline.filter_candidates_by_class",
            return_value=([], [{"name": "旧别名", "count": 1}], []),
        ),
        patch(
            "src.workflows.annotate_helpers.disambiguation.pipeline._build_existing_character_hint_from_db",
            return_value=DisambiguationPromptContext(
                existing_character_hint="【已存在角色锚点】\n- 白芷",
            ),
        ),
        patch(
            "src.workflows.annotate_helpers.disambiguation.pipeline._fetch_current_relations",
            return_value=[],
        ),
        patch(
            "src.workflows.annotate_helpers.disambiguation.pipeline.validate_confidence_with_evidence",
            side_effect=lambda result, *_: result,
        ),
        patch(
            "src.workflows.annotate_helpers.disambiguation.pipeline.align_canonical_by_frequency",
            side_effect=lambda result, *_args, **_kwargs: result,
        ),
        patch(
            "src.workflows.annotate_helpers.disambiguation.pipeline.apply_disambiguation_decisions",
            return_value=state,
        ),
        patch(
            "src.workflows.annotate_helpers.disambiguation.pipeline._generate_and_save_stage_summary",
            new=AsyncMock(),
        ),
        patch("src.workflows.annotate_helpers.disambiguation.pipeline.record_model_interaction"),
    ):
        new_state = await disambig_mod._run_incremental_disambiguation_with_state(
            conn=MagicMock(),
            state=state,
            incremental_disambig_client=client,
            alias_keywords=["号"],
            novel_id="novel-1",
            run_id="run-1",
            chunk_id=12,
            current_idx=2,
            disambig_interval=3,
            rag_retriever=rag_retriever,
        )

    assert new_state is state
    assert client.received_prompt_context is not None
    assert client.received_prompt_context.shared_evidence_context is not None
    assert "<Vector_Evidence>" in client.received_prompt_context.shared_evidence_context
    assert "<Disambig_Candidates>" not in client.received_prompt_context.shared_evidence_context
