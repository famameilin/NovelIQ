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

import json
import subprocess
import time
from typing import TYPE_CHECKING, Any

from loguru import logger
from sqlalchemy.orm import Session

from src.config import settings
from src.models.disambiguation_types import NameCountCandidate
from src.models.interactions import record_model_interaction
from src.models.interfaces import DisambiguationLike
from src.models.local.disambiguation import (
    DisambiguationPromptContext,
    DisambiguationState,
    ExtendedDisambigResult,
    NameReviewState,
    build_disambiguate_messages,
    build_disambiguation_prompt_context,
    render_disambig_prompt_context,
)
from src.models.local.disambiguation.result_builder import align_canonical_by_frequency
from src.models.local.prompts import STAGE_SUMMARY_SYSTEM_PROMPT, STAGE_SUMMARY_USER_TEMPLATE
from src.storage.repositories import AnnotationRepository
from src.storage.repositories.annotation.characters import fetch_all_character_names
from src.storage.repositories.stats import fetch_chunk_summaries_by_range, insert_stage_summary

from ..sentence import build_context_sentences
from .candidate_filter import CandidateClassification
from .candidates import (
    _build_candidate_payload_by_names,
    _build_existing_character_hint_from_db,
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
    validate_confidence_with_evidence,
)

if TYPE_CHECKING:
    from src.rag import DisambigContextProvider

DisambigStateSnapshot = dict[str, dict[str, str]]


def _fetch_current_relations(conn: Session, run_id: str) -> list[dict]:
    """从 graph_repo 获取当前活跃关系。"""
    from src.storage.repositories import GraphRepository

    graph_repo = GraphRepository(conn)
    return graph_repo.fetch_current_relations(run_id, active_only=True)


async def _generate_and_save_stage_summary(
    conn: Session,
    run_id: str,
    current_chunk_id: int,
    disambig_interval: int,
    client: DisambiguationLike,
) -> None:
    """
    生成并保存阶段性摘要

    创建时间: 2026-04-08
    创建者: GLM-5
    任务: summary-full-chain-refactor
    说明: 在增量消歧时，获取最近N个chunk的summary，生成100字阶段性摘要

    Args:
        conn: 数据库会话
        run_id: 运行ID
        current_chunk_id: 当前chunk_id
        disambig_interval: 消歧间隔（也是摘要区间大小）
        client: 消歧客户端（用于调用LLM生成摘要）
    """
    start_chunk_id = current_chunk_id - disambig_interval + 1
    if start_chunk_id < 0:
        start_chunk_id = 0

    summaries = fetch_chunk_summaries_by_range(conn, run_id, start_chunk_id, current_chunk_id)
    if not summaries:
        logger.debug(f"No chunk summaries found for range {start_chunk_id}-{current_chunk_id}")
        return

    summaries_text = "\n".join([f"[{cid}] {s}" for cid, s in summaries])
    user_content = STAGE_SUMMARY_USER_TEMPLATE.format(
        count=len(summaries),
        summaries=summaries_text,
    )
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
        logger.info(f"Generated stage summary for chunks {start_chunk_id}-{current_chunk_id}: {stage_summary[:50]}...")

        record_model_interaction(
            run_id=run_id,
            chunk_id=None,
            interaction_type="stage_summary",
            phase="incremental",
            attempt_number=1,
            messages=messages,
            response_text=stage_summary,
            thinking_content=None,
            duration_ms=duration_ms,
            model_name=client._config.model,
            model_provider="cloud" if client.is_cloud_api() else "local",
            session=None,
        )
    except Exception as e:
        logger.warning(f"Failed to generate stage summary: {e}")


def _inject_category_into_context(
    classifications: list[CandidateClassification],
    context_sentences: dict[str, str],
) -> None:
    """将 protected 候选的分类标签注入到上下文字符串前缀。"""
    for cls in classifications:
        if cls.category == "protected" and cls.name in context_sentences:
            ctx = context_sentences[cls.name]
            context_sentences[cls.name] = f"【受保护-默认不合并】{ctx}"


def _resolve_incremental_batch_window(current_chunk_id: int, disambig_interval: int) -> tuple[int, int]:
    """
    解析增量消歧批次窗口。

    创建时间: 2026-04-21
    创建者: Codex
    任务: align-incremental-disambig-batch-window
    说明: 增量消歧的触发语义是“对前 N 个尚未触发增量消歧的 chunk 做一轮消歧”，
         因此上下文窗口也必须显式对齐到同一个批次区间，不能再隐式依赖 prev_chunks。
    """
    batch_start_chunk_id = max(0, current_chunk_id - disambig_interval + 1)
    return batch_start_chunk_id, current_chunk_id


def _merge_deferred_candidates_into_state(
    state: DisambiguationState,
    deferred_candidates: list[NameCountCandidate],
) -> DisambiguationState:
    """
    将延后处理的候选写回状态，避免低频正式名在候选阶段蒸发。

    创建时间: 2026-04-20
    创建者: Codex
    任务: preserve-deferred-disambig-candidates
    说明: deferred 候选本轮不送模型，但仍要进入 discovered_names，并在 review_status
    中留下 unresolved 记录，供后续增量复审和终消歧重新评估。
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

    logger.info(
        "Deferred {} candidates for later disambiguation: {}",
        len(recorded_names),
        recorded_names,
    )
    return state.with_updates(
        discovered_names=frozenset(new_discovered),
        review_status=tuple(new_review_status.items()),
    )


def _collect_review_candidates(
    state: DisambiguationState,
) -> list[NameCountCandidate]:
    """收集需要复审的已判决名字。

    条件（严格，避免推翻已有正确决策）：
    1. status != resolved
    2. confidence == low（medium 的不再复审，已有合并决策的不动）

    说明:
    - 这里也会把 candidate_filter 标成 unresolved 的 deferred 名字重新带回主链路；
      如果后续 chunk 补出了上下文，它们就能重新进入模型。
    """
    review_dict = state.get_review_status_dict()
    candidates: list[NameCountCandidate] = []
    for name, review in review_dict.items():
        if review.status == "resolved":
            continue
        if review.confidence != "low":
            continue
        candidates.append({"name": name, "count": 0})  # count 仅作占位，真正是否可送模型由上下文和分类器决定
    return candidates


class DisambiguationMaxRetriesExceededError(Exception):
    """
    消歧重试次数耗尽异常

    创建时间: 2026-03-19
    创建者: TraeAI
    任务: 修复导入错误
    说明: 从 phase.py 移动到 disambiguation.py，与消歧逻辑放在一起
    """

    pass


def _get_git_audit_info() -> dict[str, str]:
    """获取 git 审计信息（模块加载时缓存，避免每次消歧调用 fork 进程）。"""
    if not hasattr(_get_git_audit_info, "_cache"):
        info: dict[str, str] = {}
        try:
            info["branch"] = (
                subprocess.check_output(
                    ["git", "rev-parse", "--abbrev-ref", "HEAD"],
                    stderr=subprocess.DEVNULL,
                    timeout=5,
                )
                .decode()
                .strip()
            )
            info["commit"] = (
                subprocess.check_output(
                    ["git", "rev-parse", "--short", "HEAD"],
                    stderr=subprocess.DEVNULL,
                    timeout=5,
                )
                .decode()
                .strip()
            )
        except Exception:
            pass
        _get_git_audit_info._cache = info  # type: ignore[attr-defined]
    return _get_git_audit_info._cache  # type: ignore[attr-defined]


def _build_disambig_response_text(result: Any) -> str:
    """
    构建消歧响应文本

    创建时间: 2026-03-27
    创建者: TraeAI
    任务: 创建统一的模型交互记录接口
    说明: 将消歧结果序列化为 JSON 字符串
    """
    if isinstance(result, ExtendedDisambigResult):
        response_dict = {
            "canonical_decisions": result.canonical_decisions,
            "alias_confidence": result.alias_confidence if hasattr(result, "alias_confidence") else {},
            "entity_types": result.entity_types if hasattr(result, "entity_types") else {},
            "entity_relations": result.entity_relations if hasattr(result, "entity_relations") else [],
            "evidence_profiles": {
                name: {
                    "has_original_sentence": profile.has_original_sentence,
                    "has_identity_clue": profile.has_identity_clue,
                    "has_summary": profile.has_summary,
                    "strong_signals": list(profile.strong_signals),
                    "strength": profile.strength,
                }
                for name, profile in getattr(result, "evidence_profiles", {}).items()
            },
        }
    elif isinstance(result, dict):
        response_dict = {
            "canonical_decisions": result,
            "alias_confidence": {},
            "entity_types": {},
            "entity_relations": [],
            "evidence_profiles": {},
        }
    else:
        response_dict = {
            "canonical_decisions": {},
            "alias_confidence": {},
            "entity_types": {},
            "entity_relations": [],
            "evidence_profiles": {},
        }

    response_dict["audit"] = _get_git_audit_info()

    return json.dumps(response_dict, ensure_ascii=False)


def _build_shared_evidence_query_text(
    candidates: list[NameCountCandidate],
    context_sentences: dict[str, str],
) -> str | None:
    """将候选名字的例句上下文拼成共享取证查询文本。"""

    parts: list[str] = []
    for item in candidates:
        name = str(item.get("name", "")).strip()
        if not name:
            continue
        context = context_sentences.get(name, "").strip()
        if context:
            parts.append(f"{name}: {context}")

    return "\n".join(parts) if parts else None


async def _build_prompt_context_with_shared_evidence(
    prompt_context: DisambiguationPromptContext | None,
    evidence_provider: DisambigContextProvider | None,
    candidates: list[NameCountCandidate],
    context_sentences: dict[str, str],
    *,
    current_chunk: int | None = None,
    active_entity_fallback_names: set[str] | None = None,
) -> DisambiguationPromptContext | None:
    """把共享 evidence renderer 输出补入消歧 prompt_context。"""

    if evidence_provider is None or not candidates:
        return prompt_context

    names_in_chunk = [str(item.get("name", "")).strip() for item in candidates if str(item.get("name", "")).strip()]
    if not names_in_chunk:
        return prompt_context

    query_text = _build_shared_evidence_query_text(candidates, context_sentences)
    if evidence_provider.requires_level3():
        if not evidence_provider.is_level3_available():
            # 中文注释：这里是“补充 shared evidence prompt_context”的辅助链路，
            # 不应在 final-only / resume 场景里替代 annotation 主流程的 readiness gate。
            # Level 3 暂不可用时，退回 Level 1 / Level 2 证据，避免把已有 prompt_context 直接变成硬失败。
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
            )
    elif evidence_provider.is_level3_available():
        evidence_bundle = await evidence_provider.collect_evidence_with_level3(
            names_in_chunk=names_in_chunk,
            current_chunk=current_chunk,
            context_text=query_text,
            exclude_chunk_ids=[current_chunk] if current_chunk is not None else None,
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
    """
    max_retries = settings.runtime.disambiguation.max_retries
    last_exception = None

    for attempt in range(1, max_retries + 1):
        start_time = time.time()
        try:
            result = await client.disambiguate_characters(
                candidates=candidates,
                context_sentences=context_sentences,
                existing_names=existing_names if existing_names else None,
                prompt_context=prompt_context,
            )
            duration_ms = int((time.time() - start_time) * 1000)

            messages = build_disambiguate_messages(
                candidates,
                context_sentences,
                existing_names,
                prompt_context=prompt_context,
            )
            response_text = _build_disambig_response_text(result)
            thinking_content = getattr(result, "_thinking_content", None)

            record_model_interaction(
                run_id=run_id,
                chunk_id=None,
                interaction_type="disambiguate",
                phase=stage_name.replace(" ", "_"),
                attempt_number=attempt,
                messages=messages,
                response_text=response_text,
                thinking_content=thinking_content,
                duration_ms=duration_ms,
                model_name=client._config.model,
                model_provider="cloud" if client.is_cloud_api() else "local",
                session=None,
            )

            return result
        except Exception as e:
            last_exception = e
            duration_ms = int((time.time() - start_time) * 1000)

            messages = build_disambiguate_messages(
                candidates,
                context_sentences,
                existing_names,
                prompt_context=prompt_context,
            )

            record_model_interaction(
                run_id=run_id,
                chunk_id=None,
                interaction_type="disambiguate",
                phase=stage_name.replace(" ", "_"),
                attempt_number=attempt,
                messages=messages,
                response_text=json.dumps({"error": str(e)}, ensure_ascii=False),
                thinking_content=None,
                duration_ms=duration_ms,
                model_name=client._config.model,
                model_provider="cloud" if client.is_cloud_api() else "local",
                session=None,
            )

            if attempt < max_retries:
                logger.warning(f"{stage_name} failed (attempt {attempt}), retrying: {e}")
                time.sleep(1)
            else:
                logger.error(f"{stage_name} failed after {max_retries} attempts: {e}")
                raise last_exception from None


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
    6. 保存 checkpoint
    """
    if (current_idx + 1) % disambig_interval != 0:
        return state

    batch_start_chunk_id, batch_end_chunk_id = _resolve_incremental_batch_window(chunk_id, disambig_interval)

    alias_map_dict = state.get_alias_merges_dict()
    new_names = extract_new_names_from_db(conn, alias_map_dict, run_id, current_chunk_id=chunk_id)

    truly_new_names: list[NameCountCandidate] = [
        name for name in new_names if name["name"] not in state.discovered_names
    ]

    # Collect review candidates: previously decided names that need re-evaluation
    review_candidates = _collect_review_candidates(state)

    all_disambig_candidates = truly_new_names + review_candidates

    if not all_disambig_candidates:
        return state

    # 增量消歧只能读取当前 chunk 及之前的例句，避免 future-chunk 线索提前泄漏。
    context_sentences = build_context_sentences(
        conn,
        all_disambig_candidates,
        alias_keywords,
        run_id=run_id,
        max_chunk_id=chunk_id,
        chunk_start_id=batch_start_chunk_id,
        chunk_end_id=batch_end_chunk_id,
    )
    _, deferred_candidates, all_disambig_candidates, classifications = filter_candidates_by_class(
        all_disambig_candidates,
        context_sentences,
    )
    state_after_deferred = _merge_deferred_candidates_into_state(state, deferred_candidates)
    if not all_disambig_candidates:
        if state_after_deferred != state:
            _save_disambig_checkpoint(conn, run_id, state_after_deferred)
        logger.info("incremental disambiguation skipped: no remaining candidates after filtering")
        return state_after_deferred
    # Rebuild context for filtered candidates only
    context_sentences = build_context_sentences(
        conn,
        all_disambig_candidates,
        alias_keywords,
        run_id=run_id,
        max_chunk_id=chunk_id,
        chunk_start_id=batch_start_chunk_id,
        chunk_end_id=batch_end_chunk_id,
    )
    # Inject protected category labels into context for prompt
    _inject_category_into_context(classifications, context_sentences)
    existing_names = list(state_after_deferred.known_canonical_names)
    alias_map = state_after_deferred.get_alias_merges_dict()
    relations = _fetch_current_relations(conn, run_id)
    prompt_context = _build_existing_character_hint_from_db(
        conn,
        [str(item.get("name", "")).strip() for item in all_disambig_candidates if str(item.get("name", "")).strip()],
        existing_names,
        alias_keywords,
        run_id,
        alias_map,
        relations,
        current_chunk_id=chunk_id,
        chunk_start_id=batch_start_chunk_id,
        chunk_end_id=batch_end_chunk_id,
    )
    new_candidate_names = {
        str(item.get("name", "")).strip()
        for item in truly_new_names
        if str(item.get("name", "")).strip()
    }
    active_entity_fallback_names = {
        str(item.get("name", "")).strip()
        for item in all_disambig_candidates
        if str(item.get("name", "")).strip() in new_candidate_names
    }
    prompt_context = await _build_prompt_context_with_shared_evidence(
        prompt_context,
        evidence_provider,
        all_disambig_candidates,
        context_sentences,
        current_chunk=chunk_id,
        active_entity_fallback_names=active_entity_fallback_names,
    )

    result = await _retry_disambig(
        incremental_disambig_client,
        all_disambig_candidates,
        context_sentences,
        existing_names,
        stage_name="incremental disambiguation",
        run_id=run_id,
        prompt_context=prompt_context,
    )

    result = validate_confidence_with_evidence(result, existing_names, context_sentences)
    incremental_global_freq = {str(n["name"]): int(n.get("count", 0)) for n in new_names}
    result = align_canonical_by_frequency(result, all_disambig_candidates, global_freq=incremental_global_freq)

    new_state = apply_disambiguation_decisions(state_after_deferred, result)

    # Accumulate entity_types from LLM output into state
    if result.entity_types:
        valid_names = new_state.discovered_names | new_state.known_canonical_names
        filtered_types = {k: v for k, v in result.entity_types.items() if k in valid_names}
        if len(filtered_types) < len(result.entity_types):
            invalid_keys = set(result.entity_types.keys()) - set(filtered_types.keys())
            logger.warning(
                "Filtered %d invalid entity_type keys in incremental disambig: %s",
                len(result.entity_types) - len(filtered_types),
                invalid_keys,
            )
        merged_types = dict(state.entity_types)
        merged_types.update(filtered_types)
        new_state = new_state.with_updates(entity_types=tuple(merged_types.items()))

    if new_state != state:
        logger.debug(
            f"DisambiguationState updated: "
            f"{len(new_state.discovered_names)} discovered, "
            f"{len(new_state.known_canonical_names)} canonicals, "
            f"{len(new_state.alias_merges)} merges"
        )

        new_relations = _normalize_relations_with_alias_map(result.entity_relations, new_state.get_alias_merges_dict())
        merged_relations = _merge_relations(list(new_state.pending_relations), new_relations)

        new_state = new_state.with_updates(pending_relations=tuple(merged_relations))

        _save_disambig_checkpoint(conn, run_id, new_state)

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
    5. 落库：
       - 用 known_canonical_names 建实体
       - 用 alias_merges 执行名字修正
       - 用 pending_relations + alias_merges 归一化关系
    6. 保存最终 checkpoint
    """
    pending_relations = list(state.pending_relations)
    if pending_relations:
        logger.info(f"Found {len(pending_relations)} pending relations from checkpoint, will process them")

    existing_names = list(state.known_canonical_names)

    if not existing_names:
        return state

    raw_all_names = fetch_all_character_names(conn, run_id)
    all_names: list[NameCountCandidate] = []
    for item in raw_all_names:
        name = str(item.get("name", "")).strip()
        if not name:
            continue
        raw_count = item.get("count", 0)
        try:
            count = int(raw_count)
        except (TypeError, ValueError):
            count = 0
        all_names.append({"name": name, "count": count})

    review_status_dict = state.get_review_status_dict()
    alias_map_dict = state.get_alias_merges_dict()
    state_snapshot_for_candidates: DisambigStateSnapshot = {
        name: {
            "state": review.status,
            "confidence": review.confidence,
            "canonical": review.proposed_canonical or name,
        }
        for name, review in review_status_dict.items()
    }
    state_snapshot_for_candidates = _ensure_state_snapshot_has_known_names(
        alias_map_dict,
        state_snapshot_for_candidates,
        state.known_canonical_names,
    )
    candidates = _collect_final_disambiguation_candidates(all_names, alias_map_dict, state_snapshot_for_candidates)

    if candidates:
        candidate_payload = _build_candidate_payload_by_names(all_names, candidates)
        context_sentences = build_context_sentences(conn, candidate_payload, alias_keywords, run_id=run_id)
        _, deferred_candidates, candidate_payload, f_classifications = filter_candidates_by_class(
            candidate_payload,
            context_sentences,
        )
        state_with_deferred = _merge_deferred_candidates_into_state(state, deferred_candidates)
        if candidate_payload:
            context_sentences = build_context_sentences(conn, candidate_payload, alias_keywords, run_id=run_id)
            _inject_category_into_context(f_classifications, context_sentences)
            relations = _fetch_current_relations(conn, run_id)
            prompt_context = _build_existing_character_hint_from_db(
                conn,
                [str(item.get("name", "")).strip() for item in candidate_payload if str(item.get("name", "")).strip()],
                existing_names,
                alias_keywords,
                run_id,
                alias_map_dict,
                relations,
                current_chunk_id=None,
            )
            prompt_context = await _build_prompt_context_with_shared_evidence(
                prompt_context,
                evidence_provider,
                candidate_payload,
                context_sentences,
            )
            result = await _retry_disambig(
                full_disambig_client,
                candidate_payload,
                context_sentences,
                existing_names,
                stage_name="final disambiguation",
                run_id=run_id,
                prompt_context=prompt_context,
            )
            result = validate_confidence_with_evidence(result, existing_names, context_sentences)
            final_global_freq = {str(n["name"]): int(n.get("count", 0)) for n in all_names}
            result = align_canonical_by_frequency(result, candidate_payload, global_freq=final_global_freq)
        else:
            logger.info("final disambiguation skipped: no remaining candidates after filtering")
            result = ExtendedDisambigResult(
                canonical_decisions={},
                entity_types={},
                entity_relations=[],
                alias_confidence={},
            )
        state = state_with_deferred
    else:
        logger.info("final disambiguation skipped: no unresolved candidates")
        result = ExtendedDisambigResult(
            canonical_decisions={},
            entity_types={},
            entity_relations=[],
            alias_confidence={},
        )

    new_state = state
    if result.canonical_decisions:
        new_state = apply_disambiguation_decisions(state, result)

    # Merge final disambig entity_types into accumulated state
    if result.entity_types:
        valid_names = new_state.discovered_names | new_state.known_canonical_names
        filtered_types = {k: v for k, v in result.entity_types.items() if k in valid_names}
        if len(filtered_types) < len(result.entity_types):
            invalid_keys = set(result.entity_types.keys()) - set(filtered_types.keys())
            logger.warning(
                "Filtered %d invalid entity_type keys in final disambig: %s",
                len(result.entity_types) - len(filtered_types),
                invalid_keys,
            )
        merged_types = dict(new_state.entity_types)
        merged_types.update(filtered_types)
        new_state = new_state.with_updates(entity_types=tuple(merged_types.items()))

    # Promote review-status names with mixed/strong evidence to canonical.
    # These names were seen by the model but never reached high confidence;
    # promoting them ensures minor characters appear in graph_entities.
    review_dict = new_state.get_review_status_dict()
    alias_set = {a for a, _ in new_state.alias_merges}
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
        logger.info(f"Promoting {len(promoted_names)} review-status names to canonical: {promoted_names}")
        new_state = new_state.with_updates(
            known_canonical_names=new_state.known_canonical_names | frozenset(promoted_names),
        )

    if new_state != state:
        logger.info(
            f"Final disambiguation completed: "
            f"{len(new_state.discovered_names)} discovered, "
            f"{len(new_state.known_canonical_names)} canonicals, "
            f"{len(new_state.alias_merges)} merges"
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
            conn, novel_id, run_id, relations_to_process, result.entity_types, new_state.get_alias_merges_dict()
        )
        logger.info(f"Final disambig: processed {success_count} hierarchical relations")
        retryable_relations = _extract_retryable_relations(skipped)
        if retryable_relations:
            logger.warning(
                "Final disambig: {} relations left for retry, kept in checkpoint",
                len(retryable_relations),
            )

    new_state = new_state.with_updates(pending_relations=tuple(retryable_relations))
    _save_disambig_checkpoint(conn, run_id, new_state)

    return new_state
