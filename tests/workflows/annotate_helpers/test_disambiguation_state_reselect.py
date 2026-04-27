from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.models.local.disambiguation import DisambiguationState, ExtendedDisambigResult, NameReviewState
from src.workflows.annotate_helpers import disambiguation as disambig_mod
from src.workflows.annotate_helpers.disambiguation import pipeline as pipeline_mod
from src.workflows.annotate_helpers.disambiguation import pipeline_stages as pipeline_stages_mod
from src.workflows.annotate_helpers.disambiguation.state_logic import (
    apply_model_reselected_canonicals,
    reselect_cluster_canonicals,
)
from tests.support.disambiguation_fakes import FakeDisambigClient as _FakeDisambigClient


def test_resolve_incremental_batch_window_aligns_with_disambig_interval() -> None:
    """
    创建时间: 2026-04-21
    创建者: Codex
    任务: align-incremental-disambig-batch-window
    说明: 增量消歧上下文窗口应与批次区间对齐，而不是由 sentence 层隐式按 prev_chunks 裁剪。
    """
    assert pipeline_mod._resolve_incremental_batch_window(9, 10) == (0, 9)
    assert pipeline_mod._resolve_incremental_batch_window(29, 10) == (20, 29)


def test_reselect_cluster_canonicals_prefers_real_name_over_descriptor_alias() -> None:
    """
    创建时间: 2026-04-21
    创建者: Codex
    任务: reselect-disambig-cluster-canonical
    说明: 即便历史状态已经被旧的频次翻转污染成 `白芷 -> 灰衣人`，
          cluster 级 canonical 重选也应能把 canonical 纠回真实名字 `白芷`。
    """
    polluted_state = DisambiguationState(
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

    corrected_state = reselect_cluster_canonicals(
        polluted_state,
        name_counts={"白芷": 7, "灰衣人": 2},
    )

    assert corrected_state.known_canonical_names == frozenset({"白芷"})
    assert corrected_state.get_alias_merges_dict() == {"灰衣人": "白芷"}
    corrected_review = corrected_state.get_review_status_dict()
    assert corrected_review["灰衣人"].proposed_canonical == "白芷"
    assert corrected_review["白芷"].proposed_canonical == "白芷"


def test_apply_model_reselected_canonicals_rewrites_cluster_to_model_selected_name() -> None:
    """
    创建时间: 2026-04-22
    创建者: Codex
    任务: final-canonical-reselect
    说明: 最终额外调用给出新的代表名后，状态机应严格按 cluster 内模型结果重写
          alias_merges / known_canonical_names / proposed_canonical。
    """
    state = DisambiguationState(
        discovered_names=frozenset({"铁爷", "贺铮"}),
        known_canonical_names=frozenset({"铁爷"}),
        alias_merges=frozenset({("贺铮", "铁爷")}),
        review_status=(
            (
                "铁爷",
                NameReviewState(
                    status="resolved",
                    confidence="high",
                    proposed_canonical="铁爷",
                    evidence_strength="strong",
                    decision_evidence_count=2,
                    decision_evidence_types=("stable_title_or_rank", "original_sentence"),
                ),
            ),
            (
                "贺铮",
                NameReviewState(
                    status="resolved",
                    confidence="high",
                    proposed_canonical="铁爷",
                    evidence_strength="mixed",
                    decision_evidence_count=1,
                    decision_evidence_types=("original_sentence",),
                ),
            ),
        ),
    )

    new_state = apply_model_reselected_canonicals(
        state,
        {"铁爷": "贺铮", "贺铮": "贺铮"},
        clusters=[{"铁爷", "贺铮"}],
    )

    assert new_state.known_canonical_names == frozenset({"贺铮"})
    assert new_state.get_alias_merges_dict() == {"铁爷": "贺铮"}
    review_dict = new_state.get_review_status_dict()
    assert review_dict["铁爷"].proposed_canonical == "贺铮"
    assert review_dict["贺铮"].proposed_canonical == "贺铮"


def test_apply_model_reselected_canonicals_rejects_cross_cluster_target() -> None:
    """
    创建时间: 2026-04-22
    创建者: Codex
    任务: final-canonical-reselect
    说明: 额外重选调用只能在既有 cluster 内选代表名；跨 cluster 指向必须直接报错，
          不能静默回退到旧 heuristic。
    """
    state = DisambiguationState(
        discovered_names=frozenset({"铁爷", "贺铮", "算盘", "林立果"}),
        known_canonical_names=frozenset({"铁爷", "算盘"}),
        alias_merges=frozenset({("贺铮", "铁爷"), ("林立果", "算盘")}),
    )

    with pytest.raises(ValueError, match="Invalid canonical reselect targets"):
        apply_model_reselected_canonicals(
            state,
            {
                "铁爷": "贺铮",
                "贺铮": "林立果",
                "算盘": "算盘",
                "林立果": "算盘",
            },
            clusters=[{"铁爷", "贺铮"}, {"算盘", "林立果"}],
        )


@pytest.mark.asyncio
async def test_incremental_pipeline_preserves_deferred_low_frequency_names() -> None:
    """
    创建时间: 2026-04-20
    创建者: Codex
    任务: preserve-deferred-disambig-candidates
    说明: 低频且暂无上下文的正式候选不应在增量阶段蒸发，而应写入状态等待后续复审。
    """
    client = _FakeDisambigClient()

    with (
        patch(
            "src.workflows.annotate_helpers.disambiguation.pipeline_stages.extract_new_names_from_db",
            return_value=[{"name": "侯飞白", "count": 1}],
        ),
        patch(
            "src.workflows.annotate_helpers.disambiguation.pipeline_stages.build_context_sentences",
            return_value={},
        ),
        patch(
            "src.workflows.annotate_helpers.disambiguation.pipeline_stages._save_disambig_checkpoint",
        ) as mock_save_checkpoint,
        patch(
            "src.workflows.annotate_helpers.disambiguation.pipeline._generate_and_save_stage_summary",
            new=AsyncMock(),
        ) as mock_stage_summary,
    ):
        new_state = await disambig_mod._run_incremental_disambiguation_with_state(
            conn=MagicMock(),
            state=DisambiguationState.empty(),
            incremental_disambig_client=client,
            alias_keywords=["号"],
            novel_id="novel-1",
            run_id="run-1",
            chunk_id=12,
            current_idx=2,
            disambig_interval=3,
        )

    review = new_state.get_review_status_dict()["侯飞白"]
    assert "侯飞白" in new_state.discovered_names
    assert review.status == disambig_mod.DISAMBIG_STATE_UNRESOLVED
    assert review.confidence == "low"
    assert review.decision_source == "candidate_filter"
    assert client.received_prompt_context is None
    mock_save_checkpoint.assert_called_once()
    mock_stage_summary.assert_not_awaited()


@pytest.mark.asyncio
async def test_final_pipeline_preserves_deferred_names_without_model_call() -> None:
    """
    创建时间: 2026-04-20
    创建者: Codex
    任务: preserve-deferred-disambig-candidates
    说明: 终消歧阶段即便某个低频正式名仍然暂无上下文，也必须保留在状态里，不能在最终入口蒸发。

    修改时间: 2026-04-27
    任务: fix-final-disambig-reselect-tests
    修改内容: 去掉已被阶段拆分迁移走的过时 patch 目标，继续验证“无模型调用时保留 deferred 候选”的真实行为。
    """

    class _DummyAnnRepo:
        def __init__(self, _conn) -> None:
            pass

        def ensure_canonical_entities(self, run_id, known_canonical_names, novel_id=None, entity_types=None):
            return {name: index for index, name in enumerate(sorted(known_canonical_names), start=1)}

        def cleanup_self_loop_relations(self, run_id):
            return None

    class _DummyConn:
        def commit(self):
            pass

    state = DisambiguationState(
        discovered_names=frozenset({"猴子"}),
        known_canonical_names=frozenset({"猴子"}),
    )

    with (
        patch.object(pipeline_stages_mod, "AnnotationRepository", _DummyAnnRepo),
        patch.object(
            pipeline_stages_mod,
            "fetch_all_character_names",
            return_value=[{"name": "猴子", "count": 5}, {"name": "侯飞白", "count": 1}],
        ),
        patch.object(pipeline_stages_mod, "build_context_sentences", return_value={}),
        patch.object(pipeline_mod, "_retry_disambig") as retry_mock,
        patch.object(pipeline_stages_mod, "_replace_final_disambiguation_chunk_relations") as replace_relations_mock,
        patch.object(pipeline_stages_mod, "_save_disambig_checkpoint") as save_checkpoint_mock,
    ):
        new_state = await disambig_mod._run_final_disambiguation_with_state(
            conn=_DummyConn(),
            state=state,
            full_disambig_client=MagicMock(),
            alias_keywords=["号"],
            novel_id="novel-1",
            run_id="run-1",
        )

    review = new_state.get_review_status_dict()["侯飞白"]
    assert "侯飞白" in new_state.discovered_names
    assert review.status == disambig_mod.DISAMBIG_STATE_UNRESOLVED
    assert review.decision_source == "candidate_filter"
    retry_mock.assert_not_called()
    replace_relations_mock.assert_called_once()
    save_checkpoint_mock.assert_called_once()


@pytest.mark.asyncio
async def test_final_pipeline_reselects_existing_cluster_canonical_without_new_model_decision() -> None:
    """
    创建时间: 2026-04-21
    创建者: Codex
    任务: reselect-disambig-cluster-canonical
    说明: 终消歧阶段即便这轮模型没有重新输出 `灰衣人/白芷`，也要能基于已有 cluster
          和全量频次把被旧逻辑翻反的 canonical 纠正回来，且不应额外查库/调模型。

    修改时间: 2026-04-27
    任务: fix-final-disambig-reselect-tests
    修改内容: 去掉对旧 `_process_entity_relations` patch 的依赖，改为匹配现行 final persist 阶段实现。
    """

    class _DummyAnnRepo:
        def __init__(self, _conn) -> None:
            pass

        def ensure_canonical_entities(self, run_id, known_canonical_names, novel_id=None, entity_types=None):
            return {name: index for index, name in enumerate(sorted(known_canonical_names), start=1)}

        def cleanup_self_loop_relations(self, run_id):
            return None

    class _DummyConn:
        def commit(self):
            pass

    client = _FakeDisambigClient()
    client.reselect_result = ExtendedDisambigResult(
        canonical_decisions={"灰衣人": "白芷", "白芷": "白芷"},
        entity_types={},
        entity_relations=[],
        alias_confidence={"灰衣人": "high", "白芷": "high"},
    )

    polluted_state = DisambiguationState(
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

    with (
        patch.object(pipeline_stages_mod, "AnnotationRepository", _DummyAnnRepo),
        patch.object(
            pipeline_stages_mod,
            "fetch_all_character_names",
            return_value=[{"name": "灰衣人", "count": 2}, {"name": "白芷", "count": 7}],
        ),
        patch.object(pipeline_stages_mod, "_collect_final_disambiguation_candidates", return_value=[]),
        patch.object(pipeline_stages_mod, "build_context_sentences") as build_context_sentences_mock,
        patch.object(pipeline_mod, "_retry_canonical_reselect") as retry_reselect_mock,
        patch.object(pipeline_stages_mod, "_replace_final_disambiguation_chunk_relations") as replace_relations_mock,
        patch.object(pipeline_stages_mod, "_save_disambig_checkpoint") as save_checkpoint_mock,
    ):
        new_state = await disambig_mod._run_final_disambiguation_with_state(
            conn=_DummyConn(),
            state=polluted_state,
            full_disambig_client=client,
            alias_keywords=["号"],
            novel_id="novel-1",
            run_id="run-1",
        )

    assert new_state.known_canonical_names == frozenset({"白芷"})
    assert new_state.get_alias_merges_dict() == {"灰衣人": "白芷"}
    assert client.received_reselect_clusters is None
    build_context_sentences_mock.assert_not_called()
    retry_reselect_mock.assert_not_called()
    replace_relations_mock.assert_called_once()
    save_checkpoint_mock.assert_called_once()
