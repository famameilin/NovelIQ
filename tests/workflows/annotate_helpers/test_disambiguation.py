from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.models.local.disambiguation import (
    DisambiguationPromptContext,
    DisambiguationState,
    ExtendedDisambigResult,
    NameReviewState,
    build_evidence_profile,
)
from src.rag import EvidenceBundle, EvidenceItem
from src.workflows.annotate_helpers import disambiguation as disambig_mod
from src.workflows.annotate_helpers.client_init import _NoopDisambiguationClient
from src.workflows.annotate_helpers.disambiguation import pipeline as pipeline_mod
from src.workflows.annotate_helpers.disambiguation.candidates import (
    DisambigStateSnapshot,
    DisambigStateSnapshotEntry,
)
from tests.support.disambiguation_fakes import (
    FakeDisambigClient as _FakeDisambigClient,
)
from tests.support.disambiguation_fakes import (
    FakeRagRetriever as _FakeRagRetriever,
)
from tests.support.disambiguation_fakes import (
    candidates as _candidates,
)


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


def test_validate_confidence_with_evidence_blocks_protected_merge_without_strong_evidence() -> None:
    """
    创建时间: 2026-04-20
    创建者: Codex
    任务: enforce-protected-disambig-gate
    说明: `受保护-默认不合并` 不能只靠 prompt 约束；若没有强证据，后端也必须回退为自映射。
    """
    context = "【受保护-默认不合并】侍卫一直守在伯安身旁，替他拦下门外闲人"
    result = ExtendedDisambigResult(
        canonical_decisions={"侍卫": "伯安"},
        entity_types={"伯安": "character"},
        entity_relations=[],
        alias_confidence={"侍卫": "high"},
        evidence_profiles={"侍卫": build_evidence_profile(context)},
    )
    validated = disambig_mod.validate_confidence_with_evidence(result, ["伯安"], {"侍卫": context})
    assert validated.canonical_decisions["侍卫"] == "侍卫"
    assert validated.alias_confidence["侍卫"] == "medium"


def test_collect_final_disambiguation_candidates_prefers_state_snapshot() -> None:
    snapshot = DisambigStateSnapshot(
        entries={
            "bai_zhi": DisambigStateSnapshotEntry(state="resolved", confidence="high", canonical="bai_zhi"),
            "lin_li_guo": DisambigStateSnapshotEntry(state="review", confidence="medium", canonical="bai_zhi"),
            "masked_person": DisambigStateSnapshotEntry(
                state="unresolved",
                confidence="low",
                canonical="bai_zhi",
            ),
        }
    )
    candidates = disambig_mod._collect_final_disambiguation_candidates(
        all_names=_candidates("bai_zhi", "lin_li_guo", "masked_person"),
        alias_map={"bai_zhi": "bai_zhi"},
        state_snapshot=snapshot,
    )
    assert set(candidates) == {"lin_li_guo", "masked_person"}


def test_collect_final_disambiguation_candidates_rereviews_self_resolved_extension_name() -> None:
    snapshot = DisambigStateSnapshot(
        entries={
            "伯安": DisambigStateSnapshotEntry(state="resolved", confidence="high", canonical="伯安"),
            "贺伯安": DisambigStateSnapshotEntry(state="resolved", confidence="high", canonical="贺伯安"),
        }
    )
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
    assert call_kwargs["reasoning_tokens"] == 17
    assert call_kwargs["requested_thinking"] is True


@pytest.mark.asyncio
async def test_retry_canonical_reselect_records_unknown_model_name_for_configless_client() -> None:
    """
    创建时间: 2026-04-22
    创建者: Codex
    任务: final-canonical-reselect-review-fix
    说明: 额外 canonical 重选的交互日志不能假定 `_config.model` 一定存在；
          轻量 fallback / 自定义 stub 至少应记录为 unknown，而不是在日志阶段直接报错。
    """

    class _ConfiglessReselectClient:
        def __init__(self) -> None:
            self._config = object()

        async def reselect_canonicals(
            self,
            candidates,
            clusters,
            context_sentences=None,
            review_states=None,
        ):
            return ExtendedDisambigResult(
                canonical_decisions={"灰衣人": "白芷", "白芷": "白芷"},
                entity_types={},
                entity_relations=[],
                alias_confidence={"灰衣人": "high", "白芷": "high"},
            )

        def is_cloud_api(self) -> bool:
            return False

    with patch("src.workflows.annotate_helpers.disambiguation.pipeline.record_model_interaction") as mock_record:
        result = await pipeline_mod._retry_canonical_reselect(
            client=_ConfiglessReselectClient(),
            candidates=[{"name": "灰衣人", "count": 2}, {"name": "白芷", "count": 7}],
            clusters=[["灰衣人", "白芷"]],
            context_sentences={"灰衣人": "她自称白芷", "白芷": "白芷"},
            review_states={},
            stage_name="final canonical reselect",
            run_id="run-1",
        )
    assert result.canonical_decisions == {"灰衣人": "白芷", "白芷": "白芷"}
    assert mock_record.call_args.kwargs["model_name"] == "unknown"


@pytest.mark.asyncio
async def test_run_final_canonical_reselect_falls_back_for_noop_client() -> None:
    """
    创建时间: 2026-04-22
    创建者: Codex
    任务: final-canonical-reselect-review-fix
    说明: 当 full disambig client 是 lightweight no-op fallback 时，终消歧后的额外
          代表名重选必须回退到既有 heuristic，不能因为不支持模型调用而把主流程打挂。
    """
    state = DisambiguationState(
        discovered_names=frozenset({"灰衣人", "白芷"}),
        known_canonical_names=frozenset({"灰衣人"}),
        alias_merges=frozenset({("白芷", "灰衣人")}),
        review_status=(
            (
                "灰衣人",
                NameReviewState(
                    status="resolved",
                    confidence="high",
                    proposed_canonical="灰衣人",
                    evidence_strength="strong",
                    decision_evidence_count=1,
                    decision_evidence_types=("identity_reveal",),
                ),
            ),
            (
                "白芷",
                NameReviewState(
                    status="resolved",
                    confidence="high",
                    proposed_canonical="灰衣人",
                    evidence_strength="strong",
                    decision_evidence_count=1,
                    decision_evidence_types=("naming_scene",),
                ),
            ),
        ),
    )
    new_state = await pipeline_mod._run_final_canonical_reselect(
        conn=object(),
        state=state,
        full_disambig_client=_NoopDisambiguationClient(config=object()),
        all_names=[{"name": "灰衣人", "count": 2}, {"name": "白芷", "count": 7}],
        alias_keywords=["号"],
        run_id="run-1",
    )
    assert new_state.known_canonical_names == frozenset({"白芷"})
    assert new_state.get_alias_merges_dict() == {"灰衣人": "白芷"}


@pytest.mark.asyncio
async def test_incremental_pipeline_builds_shared_evidence_prompt_context() -> None:
    client = _FakeDisambigClient()
    state = DisambiguationState.empty().with_updates(known_canonical_names=frozenset({"白芷"}))
    evidence_provider = _FakeRagRetriever(
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
            "src.workflows.annotate_helpers.disambiguation.pipeline_stages.extract_new_names_from_db",
            return_value=[{"name": "灰衣人", "count": 3}],
        ),
        patch(
            "src.workflows.annotate_helpers.disambiguation.pipeline_stages.build_context_sentences",
            return_value={"灰衣人": "【身份线索】她自称白芷"},
        ) as mock_build_context_sentences,
        patch(
            "src.workflows.annotate_helpers.disambiguation.pipeline_stages.filter_candidates_by_class",
            return_value=([], [], [{"name": "灰衣人", "count": 3}], []),
        ),
        patch(
            "src.workflows.annotate_helpers.disambiguation.pipeline_stages._build_existing_character_hint_from_db",
            return_value=DisambiguationPromptContext(
                existing_character_hint="【已存在角色锚点】\n- 白芷",
                graph_hint="【图谱已确认的关系】\n- 白芷 ←盟友→ 侯飞白",
            ),
        ) as mock_build_existing_hint,
        patch(
            "src.workflows.annotate_helpers.disambiguation.pipeline_stages.fetch_current_relations",
            return_value=[],
        ),
        patch(
            "src.workflows.annotate_helpers.disambiguation.pipeline_stages.validate_confidence_with_evidence",
            side_effect=lambda result, *_: result,
        ),
        patch(
            "src.workflows.annotate_helpers.disambiguation.pipeline_stages.reselect_cluster_canonicals",
            side_effect=lambda current_state, *_args, **_kwargs: current_state,
        ),
        patch(
            "src.workflows.annotate_helpers.disambiguation.pipeline_stages.apply_disambiguation_decisions",
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
            evidence_provider=evidence_provider,
        )
    assert new_state is state
    assert client.received_prompt_context is not None
    assert client.received_prompt_context.shared_evidence_context is not None
    assert "<Disambig_Candidates>" in client.received_prompt_context.shared_evidence_context
    assert "<Vector_Evidence>" in client.received_prompt_context.shared_evidence_context
    assert evidence_provider.calls[0]["method"] == "collect_evidence_with_level3"
    assert evidence_provider.calls[0]["current_chunk"] == 12
    assert evidence_provider.calls[0]["exclude_chunk_ids"] == [12]
    assert evidence_provider.calls[0]["max_chunk_id"] == 12
    assert mock_build_context_sentences.call_count == 2
    for call in mock_build_context_sentences.call_args_list:
        assert call.kwargs["max_chunk_id"] == 12
        assert call.kwargs["chunk_start_id"] == 10
        assert call.kwargs["chunk_end_id"] == 12
        assert call.kwargs["run_id"] == "run-1"
    build_hint_call = mock_build_existing_hint.call_args
    assert build_hint_call.kwargs["current_chunk_id"] == 12
    assert build_hint_call.kwargs["chunk_start_id"] == 10
    assert build_hint_call.kwargs["chunk_end_id"] == 12
    user_content = mock_record.call_args.kwargs["messages"][-1]["content"]
    assert "【已存在角色锚点】" in user_content
    assert "【图谱已确认的关系】" in user_content
    assert "<Disambig_Candidates>" in user_content
    assert "<Vector_Evidence>" in user_content


@pytest.mark.asyncio
async def test_final_pipeline_builds_shared_evidence_prompt_context() -> None:
    client = _FakeDisambigClient()
    state = DisambiguationState.empty().with_updates(known_canonical_names=frozenset({"白芷"}))
    evidence_provider = _FakeRagRetriever(
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
            "src.workflows.annotate_helpers.disambiguation.pipeline_stages.fetch_all_character_names",
            return_value=[{"name": "灰衣人", "count": 3}],
        ),
        patch(
            "src.workflows.annotate_helpers.disambiguation.pipeline_stages._collect_final_disambiguation_candidates",
            return_value=["灰衣人"],
        ),
        patch(
            "src.workflows.annotate_helpers.disambiguation.pipeline_stages.build_context_sentences",
            return_value={"灰衣人": "【身份线索】她望向白芷"},
        ),
        patch(
            "src.workflows.annotate_helpers.disambiguation.pipeline_stages.filter_candidates_by_class",
            return_value=([], [], [{"name": "灰衣人", "count": 3}], []),
        ),
        patch(
            "src.workflows.annotate_helpers.disambiguation.pipeline_stages._build_existing_character_hint_from_db",
            return_value=DisambiguationPromptContext(
                existing_character_hint="【已存在角色锚点】\n- 白芷",
                graph_hint="【图谱已确认的关系】\n- 白芷 ←盟友→ 侯飞白",
            ),
        ) as mock_build_existing_hint,
        patch(
            "src.workflows.annotate_helpers.disambiguation.pipeline_stages.fetch_current_relations",
            return_value=[],
        ),
        patch(
            "src.workflows.annotate_helpers.disambiguation.pipeline_stages.validate_confidence_with_evidence",
            side_effect=lambda result, *_: result,
        ),
        patch(
            "src.workflows.annotate_helpers.disambiguation.pipeline_stages.reselect_cluster_canonicals",
            side_effect=lambda current_state, *_args, **_kwargs: current_state,
        ),
        patch(
            "src.workflows.annotate_helpers.disambiguation.pipeline_stages.apply_disambiguation_decisions",
            return_value=state,
        ),
        patch("src.workflows.annotate_helpers.disambiguation.pipeline_stages.AnnotationRepository") as mock_repo_cls,
        patch("src.workflows.annotate_helpers.disambiguation.pipeline_stages._save_disambig_checkpoint"),
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
            evidence_provider=evidence_provider,
        )
    assert new_state.known_canonical_names == state.known_canonical_names
    assert client.received_prompt_context is not None
    assert client.received_prompt_context.shared_evidence_context is not None
    assert "<Vector_Evidence>" in client.received_prompt_context.shared_evidence_context
    assert evidence_provider.calls[0]["method"] == "collect_evidence_with_level3"
    assert evidence_provider.calls[0]["current_chunk"] is None
    assert evidence_provider.calls[0]["max_chunk_id"] is None
    build_hint_call = mock_build_existing_hint.call_args
    assert build_hint_call.kwargs["current_chunk_id"] is None
    user_content = mock_record.call_args.kwargs["messages"][-1]["content"]
    assert "【已存在角色锚点】" in user_content
    assert "【图谱已确认的关系】" in user_content
    assert "<Vector_Evidence>" in user_content


@pytest.mark.asyncio
async def test_build_prompt_context_with_shared_evidence_falls_back_to_level12_when_required_level3_unavailable() -> (
    None
):
    evidence_provider = _FakeRagRetriever(
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
            evidence_provider,
            [{"name": "灰衣人", "count": 3}],
            {"灰衣人": "【身份线索】她自称白芷"},
            current_chunk=12,
            active_entity_fallback_names={"灰衣人"},
        )
    assert prompt_context is not None
    assert prompt_context.shared_evidence_context is not None
    assert "<Disambig_Candidates>" in prompt_context.shared_evidence_context
    assert evidence_provider.calls[0]["method"] == "collect_evidence"
    mock_warning.assert_called_once()


@pytest.mark.asyncio
async def test_incremental_pipeline_skips_active_entity_fallback_for_review_candidates() -> None:
    client = _FakeDisambigClient()
    state = DisambiguationState.empty().with_updates(known_canonical_names=frozenset({"白芷"}))
    evidence_provider = _FakeRagRetriever(
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
            "src.workflows.annotate_helpers.disambiguation.pipeline_stages.extract_new_names_from_db",
            return_value=[],
        ),
        patch(
            "src.workflows.annotate_helpers.disambiguation.pipeline_stages.collect_review_candidates",
            return_value=[{"name": "旧别名", "count": 1}],
        ),
        patch(
            "src.workflows.annotate_helpers.disambiguation.pipeline_stages.build_context_sentences",
            return_value={"旧别名": "【身份线索】她曾被叫作白姑娘"},
        ),
        patch(
            "src.workflows.annotate_helpers.disambiguation.pipeline_stages.filter_candidates_by_class",
            return_value=([], [], [{"name": "旧别名", "count": 1}], []),
        ),
        patch(
            "src.workflows.annotate_helpers.disambiguation.pipeline_stages._build_existing_character_hint_from_db",
            return_value=DisambiguationPromptContext(
                existing_character_hint="【已存在角色锚点】\n- 白芷",
            ),
        ),
        patch(
            "src.workflows.annotate_helpers.disambiguation.pipeline_stages.fetch_current_relations",
            return_value=[],
        ),
        patch(
            "src.workflows.annotate_helpers.disambiguation.pipeline_stages.validate_confidence_with_evidence",
            side_effect=lambda result, *_: result,
        ),
        patch(
            "src.workflows.annotate_helpers.disambiguation.pipeline_stages.reselect_cluster_canonicals",
            side_effect=lambda current_state, *_args, **_kwargs: current_state,
        ),
        patch(
            "src.workflows.annotate_helpers.disambiguation.pipeline_stages.apply_disambiguation_decisions",
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
            evidence_provider=evidence_provider,
        )
    assert new_state is state
    assert client.received_prompt_context is not None
    assert client.received_prompt_context.shared_evidence_context is not None
    assert "<Vector_Evidence>" in client.received_prompt_context.shared_evidence_context
    assert "<Disambig_Candidates>" not in client.received_prompt_context.shared_evidence_context
