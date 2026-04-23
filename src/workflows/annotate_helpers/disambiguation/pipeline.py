"""
主流程编排

创建时间: 2026-03-27
创建者: TraeAI
任务: disambiguation-module-split
说明: 从 disambiguation.py 拆分，包含主流程编排相关函数

修改时间: 2026-03-27
修改者: TraeAI
任务: 创建统一的模型交互记录接口
修改内容: 使用 record_model_interaction 替代 _save_disambiguation_interaction 函数
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

from ..sentence import build_context_sentences
from . import pipeline_stages as pipeline_stages_mod
from .candidates import (
    _build_candidate_payload_by_names,
    _build_name_count_lookup,
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
    reselect_cluster_canonicals,
)

if TYPE_CHECKING:
    from src.rag import DisambigContextProvider


class DisambiguationMaxRetriesExceededError(Exception):
    """
    消歧重试次数耗尽异常

    创建时间: 2026-03-19
    创建者: TraeAI
    任务: 修复导入错误
    说明: 从 phase.py 移动到 disambiguation.py，与消歧逻辑放在一起
    """

    pass


_build_prompt_context_with_shared_evidence = pipeline_stages_mod.build_prompt_context_with_shared_evidence
_resolve_incremental_batch_window = pipeline_stages_mod.resolve_incremental_batch_window
_generate_and_save_stage_summary = pipeline_stages_mod.generate_and_save_stage_summary


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

    创建时间: 2026-03-16
    创建者: TraeAI
    任务: 添加消歧重试逻辑和交互记录保存

    修改时间: 2026-03-19
    修改者: TraeAI
    任务: 修复 disambiguate_characters 调用方式
    修改内容: 使用 client.disambiguate_characters() 方法调用

    修改时间: 2026-03-27
    修改者: TraeAI
    任务: 创建统一的模型交互记录接口
    修改内容: 使用 record_model_interaction 替代 _save_disambiguation_interaction

    修改时间: 2026-04-22
    修改者: Codex
    任务: final-canonical-reselect-review-fix
    修改内容: 模型名改为安全读取，避免轻量 fallback client 在交互日志阶段报错
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
    带重试的最终代表名重选调用。

    创建时间: 2026-04-22
    创建者: Codex
    任务: final-canonical-reselect
    说明: 终消歧后的额外重选必须继续走模型，而不是回退到本地 heuristic；
          这里复用统一的交互记录，但消息体按“已确认 cluster 的代表名选择”单独构造。

    修改时间: 2026-04-22
    修改者: Codex
    任务: final-canonical-reselect-review-fix
    修改内容: 交互日志改为安全读取模型名，避免 lightweight fallback client 直接崩溃
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
    在最终消歧后追加一次模型代表名重选。

    创建时间: 2026-04-22
    创建者: Codex
    任务: final-canonical-reselect
    说明: 第一轮终消歧继续允许“高频常用名做 canonical”来简化配对；
          但真正落库前，必须再让模型基于已确认 cluster 选择最终代表名，
          避免本地 heuristic 代替模型做这一步。

    修改时间: 2026-04-22
    修改者: Codex
    任务: final-canonical-reselect-review-fix
    修改内容: 对不支持额外重选的 fallback client 回退到本地 heuristic，
              并为异常空输出保留显式降级路径
    """
    alias_clusters = _collect_alias_clusters(state.get_alias_merges_dict())
    if not alias_clusters:
        return state

    name_counts = _build_name_count_lookup(all_names)
    if not supports_canonical_reselect(full_disambig_client):
        logger.warning("final canonical reselect skipped: client does not support model reselect, falling back")
        return reselect_cluster_canonicals(state, name_counts=name_counts)

    cluster_names = sorted({name for cluster in alias_clusters for name in cluster})
    candidate_payload = _build_candidate_payload_by_names(all_names, cluster_names)
    if not candidate_payload:
        logger.warning("final canonical reselect skipped: no candidate payload for alias clusters, falling back")
        return reselect_cluster_canonicals(state, name_counts=name_counts)

    context_sentences = build_context_sentences(conn, candidate_payload, alias_keywords, run_id=run_id)
    review_states = state.get_review_status_dict()
    cluster_list = [sorted(cluster) for cluster in alias_clusters]
    reselect_result = await _retry_canonical_reselect(
        full_disambig_client,
        candidate_payload,
        cluster_list,
        context_sentences,
        review_states,
        stage_name="final canonical reselect",
        run_id=run_id,
    )
    if not reselect_result.canonical_decisions:
        logger.warning("final canonical reselect returned empty decisions, falling back to heuristic reselect")
        return reselect_cluster_canonicals(state, name_counts=name_counts)

    # 中文注释：这里显式要求模型输出覆盖 cluster 内的所有名字；
    # 若缺项或跨组指向，直接抛错，避免静默退回 heuristic 后再次把最终图谱写偏。
    return apply_model_reselected_canonicals(
        state,
        reselect_result.canonical_decisions,
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
    evidence_provider: DisambigContextProvider | None = None,
) -> DisambiguationState:
    """
    执行增量消歧（使用新的三层状态）

    流程：
    1. 从 DB 抓候选名
    2. 用 discovered_names 判断哪些是真新名字
    3. 调模型得到 canonical_decisions
    4. 走 evidence validation
    5. state = apply_disambiguation_decisions(state, result)
    6. 按 alias cluster 重选 canonical，避免频次直接改写配对语义
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
        evidence_provider,
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
    evidence_provider: DisambigContextProvider | None = None,
) -> DisambiguationState:
    """
    执行最终消歧（使用新的三层状态）

    创建时间: 2026-03-27
    创建者: TraeAI
    任务: disambiguation-state-three-layer
    说明: 使用 DisambiguationState 替代 alias_map

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
    else:
        plan = await assemble_final_prompt_context(plan, evidence_provider)
        result = await _retry_disambig(
            full_disambig_client,
            plan.candidate_payload,
            plan.context_sentences,
            plan.existing_names,
            stage_name="final disambiguation",
            run_id=run_id,
            prompt_context=plan.prompt_context,
        )
        working_state = plan.state_before_apply

    new_state = apply_final_disambiguation_result(
        working_state,
        result,
        plan.final_global_freq,
        plan.context_sentences,
    )
    if new_state.alias_merges:
        # 中文注释：只有“本轮 final 确实拿到了新的模型 alias 决策”时，才追加一次模型代表名重选；
        # 如果这轮没有新决策，就沿用既有 state + 全量频次做本地纠偏，避免无意义查库和额外模型调用。
        if result.canonical_decisions:
            new_state = await _run_final_canonical_reselect(
                conn,
                new_state,
                full_disambig_client,
                plan.all_names,
                alias_keywords,
                run_id,
            )
    return persist_final_disambiguation(
        conn,
        novel_id,
        run_id,
        working_state,
        new_state,
        plan.pending_relations,
        result,
    )
