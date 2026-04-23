"""
消歧流程阶段拆分辅助模块

创建时间: 2026-04-23
任务: p1-disambiguation-pipeline-split
说明: 将增量消歧与最终消歧中“计划、prompt 组装、状态应用、checkpoint 持久化”阶段显式拆开。
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import TYPE_CHECKING

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
    build_disambiguation_prompt_context,
    render_disambig_prompt_context,
)
from src.models.local.disambiguation.constants import PROTECTED_CONTEXT_PREFIX
from src.models.local.prompts import STAGE_SUMMARY_SYSTEM_PROMPT, STAGE_SUMMARY_USER_TEMPLATE
from src.storage.repositories import AnnotationRepository
from src.storage.repositories.annotation.characters import fetch_all_character_names
from src.storage.repositories.stats import fetch_chunk_summaries_by_range, insert_stage_summary

from ..sentence import build_context_sentences
from .candidate_filter import CandidateClassification
from .candidates import (
    DisambigStateSnapshot,
    DisambigStateSnapshotEntry,
    _build_candidate_payload_by_names,
    _build_existing_character_hint_from_db,
    _build_name_count_lookup,
    _collect_final_disambiguation_candidates,
    _ensure_state_snapshot_has_known_names,
    extract_new_names_from_db,
    filter_candidates_by_class,
)
from .checkpoint import _save_disambig_checkpoint
from .relations import (
    _extract_retryable_relations,
    _merge_relations,
    _normalize_relations_with_alias_map,
    _process_entity_relations,
)
from .state_logic import (
    DISAMBIG_STATE_RESOLVED,
    DISAMBIG_STATE_UNRESOLVED,
    apply_disambiguation_decisions,
    reselect_cluster_canonicals,
    validate_confidence_with_evidence,
)

if TYPE_CHECKING:
    from src.rag import DisambigContextProvider
    from src.storage.repositories.graph import CurrentRelationRow


@dataclass(frozen=True)
class IncrementalDisambiguationPlan:
    """
    增量消歧计划。

    创建时间: 2026-04-23
    任务: p1-disambiguation-pipeline-split
    说明: 显式承接“候选计划”和“prompt 组装”产物，便于主流程按阶段推进。
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
    最终消歧计划。

    创建时间: 2026-04-23
    任务: p1-disambiguation-pipeline-split
    说明: 将终消歧的候选收集、prompt 组装和后续落库需要的上下文统一封装。
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
    从 graph repository 获取当前活跃关系。

    修改时间: 2026-04-23
    任务: p1-disambiguation-pipeline-split
    修改内容: 抽离为阶段辅助函数，供增量与最终 prompt 组装共用。
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
    生成并保存阶段性摘要。

    修改时间: 2026-04-23
    任务: p1-disambiguation-pipeline-split
    修改内容: 抽离出增量 checkpoint 后置步骤，主流程只负责调用阶段函数。
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
    解析增量消歧批次窗口。

    创建时间: 2026-04-21
    任务: align-incremental-disambig-batch-window
    修改时间: 2026-04-23
    修改原因: 抽离到阶段模块，供候选计划阶段单独复用。
    """
    batch_start_chunk_id = max(0, current_chunk_id - disambig_interval + 1)
    return batch_start_chunk_id, current_chunk_id


def inject_category_into_context(
    classifications: list[CandidateClassification],
    context_sentences: dict[str, str],
) -> None:
    """
    将 protected 候选的分类标签注入到上下文字符串前缀。

    修改时间: 2026-04-23
    任务: p1-disambiguation-pipeline-split
    修改内容: 抽离到阶段模块，统一由 prompt 组装阶段调用。
    """
    for cls in classifications:
        if cls.category == "protected" and cls.name in context_sentences:
            context_sentences[cls.name] = f"{PROTECTED_CONTEXT_PREFIX}{context_sentences[cls.name]}"


def merge_deferred_candidates_into_state(
    state: DisambiguationState,
    deferred_candidates: list[NameCountCandidate],
) -> DisambiguationState:
    """
    将延后处理的候选写回状态。

    修改时间: 2026-04-23
    任务: p1-disambiguation-pipeline-split
    修改内容: 抽离为候选计划阶段的专用步骤，避免主流程夹杂细节状态修补。
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
    收集需要复审的已判决名字。

    修改时间: 2026-04-23
    任务: p1-disambiguation-pipeline-split
    修改内容: 抽离到候选计划阶段，让主流程只编排阶段，不再遍历 review_status 细节。
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
    将候选名字的例句上下文拼成共享取证查询文本。

    修改时间: 2026-04-23
    任务: p1-disambiguation-pipeline-split
    修改内容: 抽离为 prompt 组装阶段的独立辅助函数。
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


async def build_prompt_context_with_shared_evidence(
    prompt_context: DisambiguationPromptContext | None,
    evidence_provider: DisambigContextProvider | None,
    candidates: list[NameCountCandidate],
    context_sentences: dict[str, str],
    *,
    current_chunk: int | None = None,
    active_entity_fallback_names: set[str] | None = None,
) -> DisambiguationPromptContext | None:
    """
    把共享 evidence renderer 输出补入消歧 prompt_context。

    修改时间: 2026-04-23
    任务: p1-disambiguation-pipeline-split
    修改内容: 从主流程中抽离，作为 prompt 组装阶段的统一步骤。

    修改时间: 2026-04-23
    任务: level3-history-cutoff
    修改内容: shared Level3 取证显式传入 max_chunk_id；增量阶段截止到当前批次结束 chunk，
              final 阶段用 None 表示允许全量历史。
    """
    if evidence_provider is None or not candidates:
        return prompt_context

    names_in_chunk = [str(item.get("name", "")).strip() for item in candidates if str(item.get("name", "")).strip()]
    if not names_in_chunk:
        return prompt_context

    query_text = build_shared_evidence_query_text(candidates, context_sentences)
    from src.rag.mention_extraction import extract_person_mentions
    from src.rag.mention_query import build_mention_evidence_queries

    # 中文注释：消歧共享 evidence 可从候选例句中抽 mention，但仍只影响 Level3 retrieval 上游。
    mention_queries = build_mention_evidence_queries(extract_person_mentions(query_text or ""))
    if evidence_provider.requires_level3():
        if not evidence_provider.is_level3_available():
            logger.warning(
                "shared evidence prompt_context fallback to Level1/2 only because Level3 is required but unavailable"
            )
            evidence_bundle = evidence_provider.collect_evidence(
                names_in_chunk=names_in_chunk,
                current_chunk=current_chunk,
            )
        else:
            evidence_bundle = await evidence_provider.collect_evidence_with_level3(
                names_in_chunk=names_in_chunk,
                current_chunk=current_chunk,
                context_text=query_text,
                exclude_chunk_ids=[current_chunk] if current_chunk is not None else None,
                max_chunk_id=current_chunk,
                mention_queries=mention_queries,
            )
    elif evidence_provider.is_level3_available():
        evidence_bundle = await evidence_provider.collect_evidence_with_level3(
            names_in_chunk=names_in_chunk,
            current_chunk=current_chunk,
            context_text=query_text,
            exclude_chunk_ids=[current_chunk] if current_chunk is not None else None,
            max_chunk_id=current_chunk,
            mention_queries=mention_queries,
        )
    else:
        evidence_bundle = evidence_provider.collect_evidence(
            names_in_chunk=names_in_chunk,
            current_chunk=current_chunk,
        )

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
    evidence_provider: DisambigContextProvider | None,
) -> IncrementalDisambiguationPlan | None:
    """
    规划增量消歧候选与 prompt 输入。

    创建时间: 2026-04-23
    任务: p1-disambiguation-pipeline-split
    说明: 显式对应“候选计划”和“prompt 组装”两个阶段，返回后续模型决策所需的完整输入。
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
        evidence_provider,
        filtered_candidates,
        context_sentences,
        current_chunk=chunk_id,
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
    应用增量消歧模型决策。

    创建时间: 2026-04-23
    任务: p1-disambiguation-pipeline-split
    说明: 显式对应“模型决策后状态应用”阶段，隔离状态机细节。
    """
    existing_names = list(state.known_canonical_names)
    validated_result = validate_confidence_with_evidence(result, existing_names, context_sentences)
    incremental_global_freq = {str(item["name"]): int(item.get("count", 0)) for item in new_names}
    new_state = apply_disambiguation_decisions(state, validated_result)
    if validated_result.canonical_decisions:
        affected_cluster_names = set(validated_result.canonical_decisions) | set(
            validated_result.canonical_decisions.values()
        )
        new_state = reselect_cluster_canonicals(
            new_state,
            name_counts=incremental_global_freq,
            affected_names=affected_cluster_names,
        )

    if validated_result.entity_types:
        valid_names = new_state.discovered_names | new_state.known_canonical_names
        filtered_types = {key: value for key, value in validated_result.entity_types.items() if key in valid_names}
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
    持久化增量消歧 checkpoint。

    创建时间: 2026-04-23
    任务: p1-disambiguation-pipeline-split
    说明: 显式对应增量流程的 checkpoint 阶段，避免主流程混杂持久化判断。
    """
    if new_state == old_state:
        return

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
    规划最终消歧的候选集合。

    创建时间: 2026-04-23
    任务: p1-disambiguation-pipeline-split
    说明: 显式对应“候选收集”阶段，并把后续落库所需全量上下文一并准备好。
    """
    pending_relations = list(state.pending_relations)
    existing_names = list(state.known_canonical_names)
    if not existing_names:
        return None

    raw_all_names = fetch_all_character_names(conn, run_id)
    all_names: list[NameCountCandidate] = []
    for item in raw_all_names:
        name = str(item.get("name", "")).strip()
        if not name:
            continue
        try:
            count = int(item.get("count", 0))
        except (TypeError, ValueError):
            count = 0
        all_names.append({"name": name, "count": count})

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
    evidence_provider: DisambigContextProvider | None,
) -> FinalDisambiguationPlan:
    """
    组装最终消歧 prompt 上下文。

    创建时间: 2026-04-23
    任务: p1-disambiguation-pipeline-split
    说明: 显式对应终消歧的 prompt/evidence 组装阶段。
    """
    if not plan.candidate_payload:
        return plan

    prompt_context = await build_prompt_context_with_shared_evidence(
        plan.prompt_context,
        evidence_provider,
        plan.candidate_payload,
        plan.context_sentences,
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
    应用最终消歧模型决策。

    创建时间: 2026-04-23
    任务: p1-disambiguation-pipeline-split
    说明: 显式对应“canonical reselect 前的状态应用”阶段。
    """
    existing_names = list(base_state.known_canonical_names)
    validated_result = validate_confidence_with_evidence(result, existing_names, context_sentences)
    new_state = base_state
    if validated_result.canonical_decisions:
        new_state = apply_disambiguation_decisions(base_state, validated_result)
    if new_state.alias_merges and not validated_result.canonical_decisions:
        new_state = reselect_cluster_canonicals(new_state, name_counts=final_global_freq)

    if validated_result.entity_types:
        valid_names = new_state.discovered_names | new_state.known_canonical_names
        filtered_types = {key: value for key, value in validated_result.entity_types.items() if key in valid_names}
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
    持久化最终消歧结果与 checkpoint。

    创建时间: 2026-04-23
    任务: p1-disambiguation-pipeline-split
    说明: 显式对应终消歧的“实体落库、关系投影、checkpoint 保存”阶段。
    """
    if new_state != previous_state:
        logger.info(
            "Final disambiguation completed: {} discovered, {} canonicals, {} merges",
            len(new_state.discovered_names),
            len(new_state.known_canonical_names),
            len(new_state.alias_merges),
        )

    ann_repo = AnnotationRepository(conn)
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
    if relations_to_process:
        success_count, skipped = _process_entity_relations(
            conn,
            novel_id,
            run_id,
            relations_to_process,
            result.entity_types,
            new_state.get_alias_merges_dict(),
        )
        logger.info("Final disambig: processed {} hierarchical relations", success_count)
        retryable_relations = _extract_retryable_relations(skipped)
        if retryable_relations:
            logger.warning("Final disambig: {} relations left for retry, kept in checkpoint", len(retryable_relations))

    persisted_state = new_state.with_updates(pending_relations=tuple(retryable_relations))
    _save_disambig_checkpoint(conn, run_id, persisted_state)
    return persisted_state
