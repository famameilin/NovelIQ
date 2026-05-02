"""
消歧流程阶段拆分辅助模块

将增量消歧与最终消歧中“计划、prompt 组装、状态应用、checkpoint 持久化”阶段显式拆开
"""

from __future__ import annotations

import time
from collections.abc import Iterable
from dataclasses import dataclass
from typing import TYPE_CHECKING

from loguru import logger
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from src.config import settings
from src.models.disambiguation_types import NameCountCandidate
from src.models.interactions import record_model_interaction
from src.models.interfaces import DisambiguationLike
from src.models.local.character_reference_policy import (
    filter_global_character_names,
    is_global_character_surface_name,
)
from src.models.local.disambiguation import (
    DisambiguationPromptContext,
    DisambiguationState,
    ExtendedDisambigResult,
    NameReviewState,
    build_disambiguation_prompt_context,
    render_disambig_prompt_context,
)
from src.models.local.disambiguation.constants import PROTECTED_CONTEXT_PREFIX
from src.models.local.prompts import STAGE_SUMMARY_SYSTEM_PROMPT, STAGE_SUMMARY_USER_TEMPLATE
from src.rag import EvidenceRequest
from src.storage.models import Chunk as ChunkModel
from src.storage.repositories import AnnotationRepository
from src.storage.repositories.stats import fetch_chunk_summaries_by_range, insert_stage_summary

from .candidate_filter import CandidateClassification
from .candidates import (
    DisambigStateSnapshot,
    DisambigStateSnapshotEntry,
    _build_candidate_payload_by_names,
    _build_existing_character_hint_from_db,
    _build_name_count_lookup,
    _collect_final_disambiguation_candidates,
    _ensure_state_snapshot_has_known_names,
    build_candidate_context_sentences,
    extract_new_names_from_db,
    fetch_reference_aware_disambiguation_candidates,
    filter_candidates_by_class,
)
from .checkpoint import _save_disambig_checkpoint
from .relations import (
    _extract_retryable_relations,
    _merge_relations,
    _normalize_relations_with_alias_map,
    _prepare_entity_relations_for_projection,
)
from .state_logic import (
    DISAMBIG_STATE_RESOLVED,
    DISAMBIG_STATE_UNRESOLVED,
    apply_disambiguation_decisions,
    validate_confidence_with_evidence,
)
from .state_logic import reselect_cluster_canonicals as _legacy_reselect_cluster_canonicals

# 修改时间: 2026-05-02
# 任务: fix-graph-projection-relations
# 修改原因: pipeline_stages 原先直接暴露 build_context_sentences 给测试替身和调用方，
#           这里保留同名别名，但实际实现切到会补关系端点上下文的新入口。
build_context_sentences = build_candidate_context_sentences

# 修改时间: 2026-05-02
# 任务: final-only-canonical-reselect
# 修改原因: 增量主路径已不再调用本地 heuristic 重选，但保留旧名字是为了兼容现有测试替身，
#           避免 patch 目标直接失效造成假回归。
reselect_cluster_canonicals = _legacy_reselect_cluster_canonicals

# 修改时间: 2026-05-02
# 任务: fix-graph-projection-relations
# 修改原因: final candidate collection 的真实实现已经换成“角色候选 + relation-only endpoint”
#           的组合入口；保留旧名字是为了兼容现有测试替身和调用方，不让内部 helper 改名造成假回归。
fetch_reference_aware_character_names = fetch_reference_aware_disambiguation_candidates

if TYPE_CHECKING:
    from src.rag import NarrativeEvidenceService
    from src.storage.repositories.graph import CurrentRelationRow


@dataclass(frozen=True)
class IncrementalDisambiguationPlan:
    """
    增量消歧计划

    显式承接“候选计划”和“prompt 组装”产物，便于主流程按阶段推进
    """

    state_after_deferred: DisambiguationState
    candidate_payload: list[NameCountCandidate]
    context_sentences: dict[str, str]
    existing_names: list[str]
    prompt_context: DisambiguationPromptContext | None
    new_names: list[NameCountCandidate]


@dataclass(frozen=True)
class FinalDisambiguationPlan:
    """
    最终消歧计划

    将终消歧的候选收集、prompt 组装和后续落库需要的上下文统一封装
    """

    state_before_apply: DisambiguationState
    pending_relations: list[dict[str, str]]
    existing_names: list[str]
    all_names: list[NameCountCandidate]
    final_global_freq: dict[str, int]
    candidate_payload: list[NameCountCandidate]
    context_sentences: dict[str, str]
    prompt_context: DisambiguationPromptContext | None


def fetch_current_relations(conn: Session, run_id: str) -> list[CurrentRelationRow]:
    """
    从 graph repository 获取当前活跃关系

    """
    from src.storage.repositories import GraphRepository

    graph_repo = GraphRepository(conn)
    return graph_repo.fetch_current_relations(run_id, active_only=True)


async def generate_and_save_stage_summary(
    conn: Session,
    run_id: str,
    current_chunk_id: int,
    disambig_interval: int,
    client: DisambiguationLike,
) -> None:
    """
    生成并保存阶段性摘要

    """
    start_chunk_id = max(0, current_chunk_id - disambig_interval + 1)
    summaries = fetch_chunk_summaries_by_range(conn, run_id, start_chunk_id, current_chunk_id)
    if not summaries:
        logger.debug("No chunk summaries found for range {}-{}", start_chunk_id, current_chunk_id)
        return

    summaries_text = "\n".join([f"[{cid}] {summary}" for cid, summary in summaries])
    user_content = STAGE_SUMMARY_USER_TEMPLATE.format(count=len(summaries), summaries=summaries_text)
    messages = [
        {"role": "system", "content": STAGE_SUMMARY_SYSTEM_PROMPT},
        {"role": "user", "content": user_content},
    ]

    try:
        start_time = time.time()
        stage_summary = await client.generate_summary(messages, max_tokens=150)
        duration_ms = int((time.time() - start_time) * 1000)
        if len(stage_summary) > 120:
            stage_summary = stage_summary[:117] + "..."

        insert_stage_summary(conn, run_id, start_chunk_id, current_chunk_id, stage_summary)
        logger.info(
            "Generated stage summary for chunks {}-{}: {}...",
            start_chunk_id,
            current_chunk_id,
            stage_summary[:50],
        )
        record_model_interaction(
            run_id=run_id,
            chunk_id=None,
            interaction_type="stage_summary",
            phase="incremental",
            attempt_number=1,
            messages=messages,
            response_text=stage_summary,
            thinking_content=None,
            requested_thinking=False,
            duration_ms=duration_ms,
            model_name=getattr(getattr(client, "_config", None), "model", "unknown"),
            model_provider="cloud" if client.is_cloud_api() else "local",
            session=None,
        )
    except Exception as exc:
        logger.warning("Failed to generate stage summary: {}", exc)


def resolve_incremental_batch_window(current_chunk_id: int, disambig_interval: int) -> tuple[int, int]:
    """
    解析增量消歧批次窗口

    """
    batch_start_chunk_id = max(0, current_chunk_id - disambig_interval + 1)
    return batch_start_chunk_id, current_chunk_id


def inject_category_into_context(
    classifications: list[CandidateClassification],
    context_sentences: dict[str, str],
) -> None:
    """
    将 protected 候选的分类标签注入到上下文字符串前缀

    """
    for cls in classifications:
        if cls.category == "protected" and cls.name in context_sentences:
            context_sentences[cls.name] = f"{PROTECTED_CONTEXT_PREFIX}{context_sentences[cls.name]}"


def merge_deferred_candidates_into_state(
    state: DisambiguationState,
    deferred_candidates: list[NameCountCandidate],
) -> DisambiguationState:
    """
    将延后处理的候选写回状态

    """
    if not deferred_candidates:
        return state

    new_discovered = set(state.discovered_names)
    new_review_status = dict(state.review_status)
    recorded_names: list[str] = []
    current_time = time.time()

    for candidate in deferred_candidates:
        name = str(candidate.get("name", "")).strip()
        if not name:
            continue
        new_discovered.add(name)
        if name in state.known_canonical_names:
            continue
        old_review = new_review_status.get(name)
        if old_review is not None and old_review.status == DISAMBIG_STATE_RESOLVED:
            continue
        if old_review is not None and old_review.status != DISAMBIG_STATE_UNRESOLVED:
            continue
        new_review_status[name] = NameReviewState(
            status=DISAMBIG_STATE_UNRESOLVED,
            confidence="low",
            proposed_canonical=None,
            evidence_strength=None,
            decision_source="candidate_filter",
            decision_timestamp=current_time,
        )
        recorded_names.append(name)

    if not recorded_names:
        if new_discovered != state.discovered_names:
            return state.with_updates(discovered_names=frozenset(new_discovered))
        return state

    logger.info("Deferred {} candidates for later disambiguation: {}", len(recorded_names), recorded_names)
    return state.with_updates(
        discovered_names=frozenset(new_discovered),
        review_status=tuple(new_review_status.items()),
    )


def collect_review_candidates(state: DisambiguationState) -> list[NameCountCandidate]:
    """
    收集需要复审的已判决名字

    """
    review_dict = state.get_review_status_dict()
    candidates: list[NameCountCandidate] = []
    for name, review in review_dict.items():
        if review.status == "resolved":
            continue
        if review.confidence != "low":
            continue
        candidates.append({"name": name, "count": 0})
    return candidates


def build_shared_evidence_query_text(
    candidates: list[NameCountCandidate],
    context_sentences: dict[str, str],
) -> str | None:
    """
    将候选名字的例句上下文拼成共享取证查询文本

    """
    parts: list[str] = []
    for item in candidates:
        name = str(item.get("name", "")).strip()
        if not name:
            continue
        context = context_sentences.get(name, "").strip()
        if context:
            parts.append(f"{name}: {context}")
    return "\n".join(parts) if parts else None


def _build_shared_evidence_request(
    *,
    names_in_chunk: list[str],
    background_entities: list[str],
    query_text: str,
    current_chunk: int | None,
) -> EvidenceRequest:
    """
    shared evidence 统一走 identity objective；seed_entities 只来自当前待消歧候选，
          已知 canonical 背景继续留在 existing_character_hint / graph_hint，不再反向污染 requested_names

    修改时间: 2026-04-29
    任务: 角色引用分层重构
    修改原因: EvidenceRequest 的 requested_names/seed_entities 只能携带 global-character，代词留在 query_text 上下文。

    修改时间: 2026-04-30
    任务: level3-query-exampler-mainline
    修改原因: shared-evidence 继续只把 global-character 准入候选写入 seed/request，
              背景 canonical 仅留在 background_entities 供渲染层使用，不回流 consumer target。
    """
    seed_entities: list[str] = []
    for normalized in filter_global_character_names([str(name).strip() for name in names_in_chunk]):
        if normalized not in seed_entities:
            seed_entities.append(normalized)
    # 背景名字只保留给 prompt renderer 的 existing_character_hint / graph_hint，
    # 不能反向扩大当前 shared-evidence request 的 consumer target。
    requested_names = list(seed_entities)
    filtered_background_entities = filter_global_character_names(
        [str(name).strip() for name in background_entities]
    )

    return EvidenceRequest(
        consumer="incremental_disambiguation" if current_chunk is not None else "final_disambiguation",
        objective="identity",
        query_text=query_text,
        requested_names=requested_names,
        seed_entities=seed_entities,
        background_entities=filtered_background_entities,
        current_chunk=current_chunk,
        max_chunk_id=current_chunk,
        exclude_chunk_ids=[current_chunk] if current_chunk is not None else [],
        need_level1=True,
        need_level2=True,
        # 只有真正留下了 global-character 候选时，shared-evidence 才允许继续打开 Level3；
        # pure reference batch 仍保留 Level1/2 fallback，但不再靠 pronoun-only query_text 重开 Level3。
        need_level3=bool(query_text.strip()) and bool(requested_names),
        allow_llm_query_expansion=True,
        top_k=settings.rag.level3_top_k,
        max_queries=settings.rag.level3_max_queries,
        model_rerank_query_max_chars=settings.rag.level3_model_rerank_query_max_chars,
    )


async def build_prompt_context_with_shared_evidence(
    prompt_context: DisambiguationPromptContext | None,
    evidence_service: NarrativeEvidenceService | None,
    candidates: list[NameCountCandidate],
    context_sentences: dict[str, str],
    *,
    current_chunk: int | None = None,
    background_entities: Iterable[str] | None = None,
    active_entity_fallback_names: Iterable[str] | None = None,
) -> DisambiguationPromptContext | None:
    """
    把共享 evidence renderer 输出补入消歧 prompt_context




    """
    if evidence_service is None or not candidates:
        return prompt_context

    names_in_chunk = [str(item.get("name", "")).strip() for item in candidates if str(item.get("name", "")).strip()]
    if not names_in_chunk:
        return prompt_context

    query_text = build_shared_evidence_query_text(candidates, context_sentences) or ""
    request = _build_shared_evidence_request(
        names_in_chunk=names_in_chunk,
        background_entities=sorted(background_entities or set()),
        query_text=query_text,
        current_chunk=current_chunk,
    )
    evidence_bundle = await evidence_service.collect(request)

    shared_evidence_context = render_disambig_prompt_context(
        evidence_bundle,
        fallback_requested_names=active_entity_fallback_names,
        priority_names=names_in_chunk,
    )
    if not shared_evidence_context:
        return prompt_context

    return build_disambiguation_prompt_context(
        existing_character_hint=prompt_context.existing_character_hint if prompt_context else None,
        graph_hint=prompt_context.graph_hint if prompt_context else None,
        shared_evidence_context=shared_evidence_context,
    )


async def plan_incremental_disambiguation(
    conn: Session,
    state: DisambiguationState,
    alias_keywords: list[str],
    run_id: str,
    chunk_id: int,
    disambig_interval: int,
    evidence_service: NarrativeEvidenceService | None,
) -> IncrementalDisambiguationPlan | None:
    """
    规划增量消歧候选与 prompt 输入

    显式对应“候选计划”和“prompt 组装”两个阶段，返回后续模型决策所需的完整输入
    """
    batch_start_chunk_id, batch_end_chunk_id = resolve_incremental_batch_window(chunk_id, disambig_interval)
    alias_map_dict = state.get_alias_merges_dict()
    new_names = extract_new_names_from_db(conn, alias_map_dict, run_id, current_chunk_id=chunk_id)
    truly_new_names = [item for item in new_names if item["name"] not in state.discovered_names]
    review_candidates = collect_review_candidates(state)
    all_disambig_candidates = truly_new_names + review_candidates
    if not all_disambig_candidates:
        return None

    context_sentences = build_context_sentences(
        conn,
        all_disambig_candidates,
        alias_keywords,
        run_id=run_id,
        max_chunk_id=chunk_id,
        chunk_start_id=batch_start_chunk_id,
        chunk_end_id=batch_end_chunk_id,
    )
    _, deferred_candidates, filtered_candidates, classifications = filter_candidates_by_class(
        all_disambig_candidates,
        context_sentences,
    )
    state_after_deferred = merge_deferred_candidates_into_state(state, deferred_candidates)
    if not filtered_candidates:
        return IncrementalDisambiguationPlan(
            state_after_deferred=state_after_deferred,
            candidate_payload=[],
            context_sentences={},
            existing_names=list(state_after_deferred.known_canonical_names),
            prompt_context=None,
            new_names=new_names,
        )

    context_sentences = build_context_sentences(
        conn,
        filtered_candidates,
        alias_keywords,
        run_id=run_id,
        max_chunk_id=chunk_id,
        chunk_start_id=batch_start_chunk_id,
        chunk_end_id=batch_end_chunk_id,
    )
    inject_category_into_context(classifications, context_sentences)
    existing_names = list(state_after_deferred.known_canonical_names)
    relations = fetch_current_relations(conn, run_id)
    prompt_context = _build_existing_character_hint_from_db(
        conn,
        [str(item.get("name", "")).strip() for item in filtered_candidates if str(item.get("name", "")).strip()],
        existing_names,
        alias_keywords,
        run_id,
        state_after_deferred.get_alias_merges_dict(),
        relations,
        current_chunk_id=chunk_id,
        chunk_start_id=batch_start_chunk_id,
        chunk_end_id=batch_end_chunk_id,
    )
    new_candidate_names = {
        str(item.get("name", "")).strip() for item in truly_new_names if str(item.get("name", "")).strip()
    }
    active_entity_fallback_names = {
        str(item.get("name", "")).strip()
        for item in filtered_candidates
        if str(item.get("name", "")).strip() in new_candidate_names
    }
    prompt_context = await build_prompt_context_with_shared_evidence(
        prompt_context,
        evidence_service,
        filtered_candidates,
        context_sentences,
        current_chunk=chunk_id,
        background_entities=state_after_deferred.known_canonical_names,
        active_entity_fallback_names=active_entity_fallback_names,
    )
    return IncrementalDisambiguationPlan(
        state_after_deferred=state_after_deferred,
        candidate_payload=filtered_candidates,
        context_sentences=context_sentences,
        existing_names=existing_names,
        prompt_context=prompt_context,
        new_names=new_names,
    )


def apply_incremental_disambiguation_result(
    state: DisambiguationState,
    result: ExtendedDisambigResult,
    new_names: list[NameCountCandidate],
    context_sentences: dict[str, str],
) -> DisambiguationState:
    """
    应用增量消歧模型决策

    修改时间: 2026-05-02
    任务: fix-final-canonical-reselect-mainline
    修改原因: 增量阶段只负责判同人和引用解析，不再在主路径里调用本地 heuristic
              重选 canonical，避免局部上下文提前污染最终代表名。

    显式对应“模型决策后状态应用”阶段，隔离状态机细节
    """
    existing_names = list(state.known_canonical_names)
    validated_result = validate_confidence_with_evidence(result, existing_names, context_sentences)
    new_state = apply_disambiguation_decisions(state, validated_result)

    if validated_result.entity_types:
        valid_names = new_state.discovered_names | new_state.known_canonical_names
        filtered_types = {
            key: value
            for key, value in validated_result.entity_types.items()
            if key in valid_names and is_global_character_surface_name(key)
        }
        if len(filtered_types) < len(validated_result.entity_types):
            invalid_keys = set(validated_result.entity_types.keys()) - set(filtered_types.keys())
            logger.warning(
                "Filtered %d invalid entity_type keys in incremental disambig: %s",
                len(validated_result.entity_types) - len(filtered_types),
                invalid_keys,
            )
        merged_types = dict(state.entity_types)
        merged_types.update(filtered_types)
        new_state = new_state.with_updates(entity_types=tuple(merged_types.items()))

    new_relations = _normalize_relations_with_alias_map(
        validated_result.entity_relations,
        new_state.get_alias_merges_dict(),
    )
    merged_relations = _merge_relations(list(new_state.pending_relations), new_relations)
    merged_relations_tuple = tuple(merged_relations)
    if merged_relations_tuple == new_state.pending_relations:
        return new_state
    return new_state.with_updates(pending_relations=merged_relations_tuple)


def persist_incremental_checkpoint(
    conn: Session,
    run_id: str,
    old_state: DisambiguationState,
    new_state: DisambiguationState,
) -> None:
    """
    持久化增量消歧 checkpoint

    修改时间: 2026-04-29
    任务: 角色引用分层重构
    修改原因: reference_resolutions 一旦确认，必须同步下沉到 chunk_* 历史行，不能只停留在 checkpoint。

    显式对应增量流程的 checkpoint 阶段，避免主流程混杂持久化判断
    """
    if new_state == old_state:
        return

    if new_state.reference_resolutions != old_state.reference_resolutions:
        AnnotationRepository(conn).apply_reference_resolutions_to_history(
            run_id,
            new_state.get_reference_resolutions_dict(),
        )

    logger.debug(
        "DisambiguationState updated: {} discovered, {} canonicals, {} merges",
        len(new_state.discovered_names),
        len(new_state.known_canonical_names),
        len(new_state.alias_merges),
    )
    _save_disambig_checkpoint(conn, run_id, new_state)


def plan_final_disambiguation(
    conn: Session,
    state: DisambiguationState,
    alias_keywords: list[str],
    run_id: str,
) -> FinalDisambiguationPlan | None:
    """
    规划最终消歧的候选集合

    修改时间: 2026-04-29
    任务: 角色引用分层重构
    修改原因: final candidate collection 需要 reference-aware 入口，不能继续复用 global-only 名字出口。

    显式对应“候选收集”阶段，并把后续落库所需全量上下文一并准备好
    """
    pending_relations = list(state.pending_relations)
    existing_names = list(state.known_canonical_names)
    if not existing_names:
        return None

    all_names = fetch_reference_aware_character_names(conn, run_id)
    final_global_freq = _build_name_count_lookup(all_names)
    review_status_dict = state.get_review_status_dict()
    alias_map_dict = state.get_alias_merges_dict()
    state_snapshot_for_candidates = DisambigStateSnapshot(
        entries={
            name: DisambigStateSnapshotEntry(
                state=review.status,
                confidence=review.confidence,
                canonical=review.proposed_canonical or name,
            )
            for name, review in review_status_dict.items()
        }
    )
    state_snapshot_for_candidates = _ensure_state_snapshot_has_known_names(
        alias_map_dict,
        state_snapshot_for_candidates,
        state.known_canonical_names,
    )
    candidate_names = _collect_final_disambiguation_candidates(all_names, alias_map_dict, state_snapshot_for_candidates)
    if not candidate_names:
        return FinalDisambiguationPlan(
            state_before_apply=state,
            pending_relations=pending_relations,
            existing_names=existing_names,
            all_names=all_names,
            final_global_freq=final_global_freq,
            candidate_payload=[],
            context_sentences={},
            prompt_context=None,
        )

    candidate_payload = _build_candidate_payload_by_names(all_names, candidate_names)
    context_sentences = build_context_sentences(conn, candidate_payload, alias_keywords, run_id=run_id)
    _, deferred_candidates, candidate_payload, classifications = filter_candidates_by_class(
        candidate_payload,
        context_sentences,
    )
    state_with_deferred = merge_deferred_candidates_into_state(state, deferred_candidates)
    if not candidate_payload:
        return FinalDisambiguationPlan(
            state_before_apply=state_with_deferred,
            pending_relations=pending_relations,
            existing_names=existing_names,
            all_names=all_names,
            final_global_freq=final_global_freq,
            candidate_payload=[],
            context_sentences={},
            prompt_context=None,
        )

    context_sentences = build_context_sentences(conn, candidate_payload, alias_keywords, run_id=run_id)
    inject_category_into_context(classifications, context_sentences)
    relations = fetch_current_relations(conn, run_id)
    prompt_context = _build_existing_character_hint_from_db(
        conn,
        [str(item.get("name", "")).strip() for item in candidate_payload if str(item.get("name", "")).strip()],
        existing_names,
        alias_keywords,
        run_id,
        state.get_alias_merges_dict(),
        relations,
        current_chunk_id=None,
    )
    return FinalDisambiguationPlan(
        state_before_apply=state_with_deferred,
        pending_relations=pending_relations,
        existing_names=existing_names,
        all_names=all_names,
        final_global_freq=final_global_freq,
        candidate_payload=candidate_payload,
        context_sentences=context_sentences,
        prompt_context=prompt_context,
    )


async def assemble_final_prompt_context(
    plan: FinalDisambiguationPlan,
    evidence_service: NarrativeEvidenceService | None,
) -> FinalDisambiguationPlan:
    """
    组装最终消歧 prompt 上下文

    显式对应终消歧的 prompt/evidence 组装阶段
    """
    if not plan.candidate_payload:
        return plan

    prompt_context = await build_prompt_context_with_shared_evidence(
        plan.prompt_context,
        evidence_service,
        plan.candidate_payload,
        plan.context_sentences,
        background_entities=plan.state_before_apply.known_canonical_names,
    )
    return FinalDisambiguationPlan(
        state_before_apply=plan.state_before_apply,
        pending_relations=plan.pending_relations,
        existing_names=plan.existing_names,
        all_names=plan.all_names,
        final_global_freq=plan.final_global_freq,
        candidate_payload=plan.candidate_payload,
        context_sentences=plan.context_sentences,
        prompt_context=prompt_context,
    )


def apply_final_disambiguation_result(
    base_state: DisambiguationState,
    result: ExtendedDisambigResult,
    final_global_freq: dict[str, int],
    context_sentences: dict[str, str],
) -> DisambiguationState:
    """
    应用最终消歧模型决策

    显式对应“canonical reselect 前的状态应用”阶段

    修改时间: 2026-05-02
    任务: fix-final-canonical-reselect-mainline
    修改原因: final review promotion 不能把未解析代词/局部引用提升为 known_canonical_names，
              且最终 canonical 选举应由 final LLM reselect 负责，这里不再做本地 heuristic 重选。
    """
    existing_names = list(base_state.known_canonical_names)
    validated_result = validate_confidence_with_evidence(result, existing_names, context_sentences)
    new_state = base_state
    if validated_result.canonical_decisions:
        new_state = apply_disambiguation_decisions(base_state, validated_result)
    if validated_result.entity_types:
        valid_names = new_state.discovered_names | new_state.known_canonical_names
        filtered_types = {
            key: value
            for key, value in validated_result.entity_types.items()
            if key in valid_names and is_global_character_surface_name(key)
        }
        if len(filtered_types) < len(validated_result.entity_types):
            invalid_keys = set(validated_result.entity_types.keys()) - set(filtered_types.keys())
            logger.warning(
                "Filtered %d invalid entity_type keys in final disambig: %s",
                len(validated_result.entity_types) - len(filtered_types),
                invalid_keys,
            )
        merged_types = dict(new_state.entity_types)
        merged_types.update(filtered_types)
        new_state = new_state.with_updates(entity_types=tuple(merged_types.items()))

    review_dict = new_state.get_review_status_dict()
    alias_set = {alias for alias, _ in new_state.alias_merges}
    promoted_names: list[str] = []
    for name, review in review_dict.items():
        if (
            review.status == "review"
            and review.evidence_strength in ("mixed", "strong")
            and name not in alias_set
            and name not in new_state.known_canonical_names
            and is_global_character_surface_name(name)
        ):
            promoted_names.append(name)
    if promoted_names:
        logger.info("Promoting {} review-status names to canonical: {}", len(promoted_names), promoted_names)
        new_state = new_state.with_updates(
            known_canonical_names=new_state.known_canonical_names | frozenset(promoted_names),
        )
    return new_state


def persist_final_disambiguation(
    conn: Session,
    novel_id: str,
    run_id: str,
    previous_state: DisambiguationState,
    new_state: DisambiguationState,
    pending_relations: list[dict[str, str]],
    result: ExtendedDisambigResult,
) -> DisambiguationState:
    """
    持久化最终消歧结果与 checkpoint

    修改时间: 2026-04-29
    任务: 角色引用分层重构
    修改原因: final 阶段确认的 reference_resolutions 需要立刻反写到历史 chunk_* 行，供后续 graph/results 消费。

    显式对应终消歧的“实体落库、关系投影、checkpoint 保存”阶段
    """
    if new_state != previous_state:
        logger.info(
            "Final disambiguation completed: {} discovered, {} canonicals, {} merges",
            len(new_state.discovered_names),
            len(new_state.known_canonical_names),
            len(new_state.alias_merges),
        )

    ann_repo = AnnotationRepository(conn)
    if new_state.reference_resolutions != previous_state.reference_resolutions:
        ann_repo.apply_reference_resolutions_to_history(
            run_id,
            new_state.get_reference_resolutions_dict(),
        )
    ann_repo.ensure_canonical_entities(
        run_id,
        new_state.known_canonical_names,
        novel_id=novel_id,
        entity_types=new_state.get_entity_types_dict() or None,
    )
    ann_repo.cleanup_self_loop_relations(run_id)
    conn.commit()
    logger.info(
        "Stateful final disambiguation persisted: {} canonicals, {} merges",
        len(new_state.known_canonical_names),
        len(new_state.alias_merges),
    )

    final_relations = _normalize_relations_with_alias_map(result.entity_relations, new_state.get_alias_merges_dict())
    relations_to_process = _merge_relations(pending_relations, final_relations)
    retryable_relations: list[dict[str, str]] = []
    prepared_relations, skipped = _prepare_entity_relations_for_projection(
        relations_to_process,
        alias_map=new_state.get_alias_merges_dict(),
    )
    _replace_final_disambiguation_chunk_relations(
        conn,
        run_id=run_id,
        prepared_relations=prepared_relations,
    )
    if prepared_relations:
        logger.info("Final disambig: staged {} hierarchical relations for graph rebuild", len(prepared_relations))
    retryable_relations = _extract_retryable_relations(skipped)
    if retryable_relations:
        logger.warning("Final disambig: {} relations left for retry, kept in checkpoint", len(retryable_relations))

    persisted_pending_relations = tuple(retryable_relations)
    if persisted_pending_relations == new_state.pending_relations:
        persisted_state = new_state
    else:
        # 修改时间: 2026-05-02
        # 任务: fix-final-canonical-reselect-mainline
        # 修改原因: final canonical 主链现在可能在“只重写代表名、不改 pending_relations”的情况下
        #           直接返回；这里避免为同值 pending_relations 再做一次 with_updates，平白刷新 updated_at。
        persisted_state = new_state.with_updates(pending_relations=persisted_pending_relations)
    _save_disambig_checkpoint(conn, run_id, persisted_state)
    return persisted_state


def _replace_final_disambiguation_chunk_relations(
    conn: Session,
    *,
    run_id: str,
    prepared_relations: list[dict[str, str]],
) -> None:
    """
    2026-04-27，任务：graph final-disambiguation rebuild fixes
    才能在 reset_graph_tables() 之后被统一重新投影出来
    """
    final_chunk_id = conn.execute(
        select(func.max(ChunkModel.chunk_id)).where(ChunkModel.run_id == run_id)
    ).scalar_one_or_none()
    if final_chunk_id is None:
        raise RuntimeError(f"cannot stage final disambiguation relations without chunks for run_id={run_id}")

    ann_repo = AnnotationRepository(conn)
    ann_repo.replace_chunk_relations_for_source_model(
        run_id,
        int(final_chunk_id),
        [
            {
                "from_name": relation["from"],
                "to_name": relation["to"],
                "type": relation["type"],
                "change": "新建",
                "evidence": "终消歧层级关系（最终阶段补写）",
                "confidence": 1.0,
                "directionality": "symmetric" if relation["type"] in {"spouse_of", "sibling_of"} else "directed",
                "projection_status": "pending",
            }
            for relation in prepared_relations
        ],
        source_model="final_disambiguation",
        commit=False,
    )
    conn.flush()
