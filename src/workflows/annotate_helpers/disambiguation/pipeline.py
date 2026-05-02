"""
主流程编排

从 disambiguation.py 拆分，包含主流程编排相关函数

"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from loguru import logger
from sqlalchemy.orm import Session

from src.models.disambiguation_types import NameCountCandidate
from src.models.interactions import record_model_interaction
from src.models.interfaces import DisambiguationLike
from src.models.local.disambiguation import (
    DisambiguationPromptContext,
    DisambiguationState,
    ExtendedDisambigResult,
    NameReviewState,
)

from . import pipeline_stages as pipeline_stages_mod
from .candidates import (
    _build_candidate_payload_by_names,
)
from .model_adapter import (
    build_canonical_reselect_call_spec,
    build_disambiguation_call_spec,
    call_with_recorded_retry,
    supports_canonical_reselect,
)
from .pipeline_stages import (
    apply_final_disambiguation_result,
    apply_incremental_disambiguation_result,
    assemble_final_prompt_context,
    persist_final_disambiguation,
    persist_incremental_checkpoint,
    plan_final_disambiguation,
    plan_incremental_disambiguation,
)
from .state_logic import (
    _collect_alias_clusters,
    apply_model_reselected_canonicals,
)

if TYPE_CHECKING:
    from src.rag import NarrativeEvidenceService


class DisambiguationMaxRetriesExceededError(Exception):
    """
    消歧重试次数耗尽异常

    从 phase.py 移动到 disambiguation.py，与消歧逻辑放在一起
    """

    pass


_build_prompt_context_with_shared_evidence = pipeline_stages_mod.build_prompt_context_with_shared_evidence
_resolve_incremental_batch_window = pipeline_stages_mod.resolve_incremental_batch_window
_generate_and_save_stage_summary = pipeline_stages_mod.generate_and_save_stage_summary

# 修改时间: 2026-05-02
# 任务: fix-final-canonical-reselect-mainline
# 修改原因: final canonical reselect 改成纯模型主导后，需要限制单次请求携带的 cluster 数，
#           避免大书场景把所有 alias clusters 一次性塞进一个 prompt。
FINAL_CANONICAL_RESELECT_MAX_CLUSTERS_PER_BATCH = 20


async def _retry_disambig(
    client: DisambiguationLike,
    candidates: list[NameCountCandidate],
    context_sentences: dict[str, str],
    existing_names: list[str],
    stage_name: str,
    run_id: str | None = None,
    prompt_context: DisambiguationPromptContext | None = None,
) -> Any:
    """
    带重试的消歧调用




    """
    call_spec = build_disambiguation_call_spec(
        client,
        candidates,
        context_sentences,
        existing_names,
        prompt_context,
        stage_name,
    )
    return await call_with_recorded_retry(
        client,
        call_spec,
        run_id=run_id,
        record_interaction=record_model_interaction,
    )


async def _retry_canonical_reselect(
    client: DisambiguationLike,
    candidates: list[NameCountCandidate],
    clusters: list[list[str]],
    context_sentences: dict[str, str],
    review_states: dict[str, NameReviewState],
    stage_name: str,
    run_id: str | None = None,
) -> Any:
    """
    带重试的最终代表名重选调用

    终消歧后的额外重选必须继续走模型，而不是回退到本地 heuristic；
          这里复用统一的交互记录，但消息体按“已确认 cluster 的代表名选择”单独构造

    """
    call_spec = build_canonical_reselect_call_spec(
        client,
        candidates,
        clusters,
        context_sentences,
        review_states,
        stage_name,
    )
    return await call_with_recorded_retry(
        client,
        call_spec,
        run_id=run_id,
        record_interaction=record_model_interaction,
    )


async def _run_final_canonical_reselect(
    conn: Session,
    state: DisambiguationState,
    full_disambig_client: DisambiguationLike,
    all_names: list[NameCountCandidate],
    alias_keywords: list[str],
    run_id: str,
) -> DisambiguationState:
    """
    在最终消歧后追加一次模型代表名重选

    修改时间: 2026-05-02
    任务: fix-final-canonical-reselect-mainline
    修改原因: canonical 主链改成“增量不选、final 只让 LLM 选”，
              因此这里需要按 cluster 分批调用模型，并在空返回/缺项时整体保留当前 state。

    第一轮终消歧的 canonical_decisions 只用于“并组/合并方向”；
          真正落库前，再让模型只在已确认 cluster 内选择最终代表名。
          若模型不可用、返回空、或缺项，则整体保留当前 state，不允许本地 heuristic 代选。

    """
    alias_clusters = _collect_alias_clusters(state.get_alias_merges_dict())
    if not alias_clusters:
        return state

    if not supports_canonical_reselect(full_disambig_client):
        logger.warning(
            "final canonical reselect skipped: client does not support model reselect, keeping current state"
        )
        return state

    sorted_clusters = sorted(
        ([*sorted(cluster)] for cluster in alias_clusters),
        key=lambda cluster: (cluster[0], len(cluster), tuple(cluster)),
    )
    cluster_batches = [
        sorted_clusters[index : index + FINAL_CANONICAL_RESELECT_MAX_CLUSTERS_PER_BATCH]
        for index in range(0, len(sorted_clusters), FINAL_CANONICAL_RESELECT_MAX_CLUSTERS_PER_BATCH)
    ]
    review_states = state.get_review_status_dict()
    aggregated_decisions: dict[str, str] = {}
    for batch_index, cluster_batch in enumerate(cluster_batches, start=1):
        cluster_names = sorted({name for cluster in cluster_batch for name in cluster})
        candidate_payload = _build_candidate_payload_by_names(all_names, cluster_names)
        if not candidate_payload:
            logger.warning(
                "final canonical reselect skipped batch {}/{}: no candidate payload, "
                "discarding all accumulated batch decisions and keeping original state",
                batch_index,
                len(cluster_batches),
            )
            return state

        context_sentences = pipeline_stages_mod.build_context_sentences(
            conn,
            candidate_payload,
            alias_keywords,
            run_id=run_id,
        )
        batch_review_states = {name: review_states[name] for name in cluster_names if name in review_states}
        reselect_result = await _retry_canonical_reselect(
            full_disambig_client,
            candidate_payload,
            cluster_batch,
            context_sentences,
            batch_review_states,
            stage_name="final canonical reselect",
            run_id=run_id,
        )
        if not reselect_result.canonical_decisions:
            logger.warning(
                "final canonical reselect returned empty decisions for batch {}/{}, keeping current state",
                batch_index,
                len(cluster_batches),
            )
            return state

        missing_names = sorted(set(cluster_names) - set(reselect_result.canonical_decisions))
        if missing_names:
            logger.warning(
                "final canonical reselect returned incomplete decisions for batch {}/{}: missing={}",
                batch_index,
                len(cluster_batches),
                missing_names,
            )
            return state

        for name in cluster_names:
            aggregated_decisions[name] = reselect_result.canonical_decisions[name]

    return apply_model_reselected_canonicals(
        state,
        aggregated_decisions,
        clusters=alias_clusters,
    )


async def _run_incremental_disambiguation_with_state(
    conn,
    state: DisambiguationState,
    incremental_disambig_client: DisambiguationLike,
    alias_keywords: list[str],
    novel_id: str,
    run_id: str,
    chunk_id: int,
    current_idx: int,
    disambig_interval: int,
    evidence_service: NarrativeEvidenceService | None = None,
) -> DisambiguationState:
    """
    执行增量消歧（使用新的三层状态）

    修改时间: 2026-05-02
    任务: fix-final-canonical-reselect-mainline
    修改原因: 增量阶段不再调用本地 heuristic canonical 选举，只保留同人判断与状态持久化。

    流程：
    1. 从 DB 抓候选名
    2. 用 discovered_names 判断哪些是真新名字
    3. 调模型得到 canonical_decisions
    4. 走 evidence validation
    5. state = apply_disambiguation_decisions(state, result)
    6. 增量阶段不做 canonical 选举，最终代表名只留给 final canonical reselect
    7. 保存 checkpoint
    """
    if (current_idx + 1) % disambig_interval != 0:
        return state

    plan = await plan_incremental_disambiguation(
        conn,
        state,
        alias_keywords,
        run_id,
        chunk_id,
        disambig_interval,
            evidence_service,
    )
    if plan is None:
        return state
    if not plan.candidate_payload:
        persist_incremental_checkpoint(conn, run_id, state, plan.state_after_deferred)
        logger.info("incremental disambiguation skipped: no remaining candidates after filtering")
        return plan.state_after_deferred

    result = await _retry_disambig(
        incremental_disambig_client,
        plan.candidate_payload,
        plan.context_sentences,
        plan.existing_names,
        stage_name="incremental disambiguation",
        run_id=run_id,
        prompt_context=plan.prompt_context,
    )
    new_state = apply_incremental_disambiguation_result(
        plan.state_after_deferred,
        result,
        plan.new_names,
        plan.context_sentences,
    )
    persist_incremental_checkpoint(conn, run_id, state, new_state)

    await _generate_and_save_stage_summary(
        conn,
        run_id,
        chunk_id,
        disambig_interval,
        incremental_disambig_client,
    )

    return new_state


async def _run_final_disambiguation_with_state(
    conn: Session,
    state: DisambiguationState,
    full_disambig_client: DisambiguationLike,
    alias_keywords: list[str],
    novel_id: str,
    run_id: str,
    evidence_service: NarrativeEvidenceService | None = None,
) -> DisambiguationState:
    """
    执行最终消歧（使用新的三层状态）

    修改时间: 2026-05-02
    任务: fix-final-canonical-reselect-mainline
    修改原因: final canonical 只由 LLM reselect 决定，即便本轮 final_disambiguation 没有
              新的 canonical_decisions，只要 alias clusters 已存在，也要继续跑最终重选。

    使用 DisambiguationState 替代 alias_map

    流程：
    1. 从 checkpoint 加载 state（已在外部完成）
    2. 用 review_status 决定复审候选
    3. 调模型
    4. state = apply_disambiguation_decisions(state, result)
    5. 对已确认 alias cluster 追加一次模型代表名重选，确定最终落库 canonical
    6. 落库：
       - 用 known_canonical_names 建实体
       - 用 alias_merges 执行名字修正
       - 用 pending_relations + alias_merges 归一化关系
    7. 保存最终 checkpoint
    """
    plan = plan_final_disambiguation(conn, state, alias_keywords, run_id)
    if plan is None:
        return state
    if plan.pending_relations:
        logger.info("Found {} pending relations from checkpoint, will process them", len(plan.pending_relations))

    if not plan.candidate_payload:
        logger.info("final disambiguation skipped: no unresolved candidates")
        result = ExtendedDisambigResult(
            canonical_decisions={},
            entity_types={},
            entity_relations=[],
            alias_confidence={},
        )
        working_state = plan.state_before_apply
        final_plan = plan
    else:
        enriched_plan = await assemble_final_prompt_context(plan, evidence_service)
        result = await _retry_disambig(
            full_disambig_client,
            enriched_plan.candidate_payload,
            enriched_plan.context_sentences,
            enriched_plan.existing_names,
            stage_name="final disambiguation",
            run_id=run_id,
            prompt_context=enriched_plan.prompt_context,
        )
        working_state = enriched_plan.state_before_apply
        final_plan = enriched_plan

    new_state = apply_final_disambiguation_result(
        working_state,
        result,
        final_plan.final_global_freq,
        final_plan.context_sentences,
    )
    if new_state.alias_merges:
        new_state = await _run_final_canonical_reselect(
            conn,
            new_state,
            full_disambig_client,
            final_plan.all_names,
            alias_keywords,
            run_id,
        )
    return persist_final_disambiguation(
        conn,
        novel_id,
        run_id,
        working_state,
        new_state,
        final_plan.pending_relations,
        result,
    )
