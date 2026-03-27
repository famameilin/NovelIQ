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
import time
from typing import Any

from loguru import logger

from src.config.constants import MAX_DISAMBIG_RETRIES
from src.models.disambiguation_types import NameCountCandidate
from src.models.interactions import record_model_interaction
from src.models.interfaces import DisambiguationLike
from src.models.local.disambiguation import (
    DisambiguationState,
    ExtendedDisambigResult,
    build_disambiguate_messages,
)
from src.storage.repositories import AnnotationRepository
from src.storage.repositories.annotation.characters import fetch_all_character_names

from ..sentence import build_context_sentences
from .candidates import (
    _build_candidate_payload_by_names,
    _build_existing_character_hint_from_db,
    _collect_final_disambiguation_candidates,
    _ensure_state_snapshot_has_known_names,
    extract_new_names_from_db,
)
from .checkpoint import _save_disambig_checkpoint_state
from .relations import (
    _extract_retryable_relations,
    _merge_relations,
    _normalize_relations_with_alias_map,
    _process_entity_relations,
)
from .state_logic import (
    apply_disambiguation_decisions,
    validate_confidence_with_evidence,
)

DisambigStateSnapshot = dict[str, dict[str, str]]


class DisambiguationMaxRetriesExceededError(Exception):
    """
    消歧重试次数耗尽异常

    创建时间: 2026-03-19
    创建者: TraeAI
    任务: 修复导入错误
    说明: 从 phase.py 移动到 disambiguation.py，与消歧逻辑放在一起
    """

    pass


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
    return json.dumps(response_dict, ensure_ascii=False)


def _retry_disambig(
    client: DisambiguationLike,
    candidates: list[NameCountCandidate],
    context_sentences: dict[str, str],
    existing_names: list[str],
    stage_name: str,
    run_id: str | None = None,
    rag_hint: str | None = None,
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
    max_retries = MAX_DISAMBIG_RETRIES
    last_exception = None

    for attempt in range(1, max_retries + 1):
        start_time = time.time()
        try:
            result = client.disambiguate_characters(
                candidates=candidates,
                context_sentences=context_sentences,
                existing_names=existing_names if existing_names else None,
                rag_hint=rag_hint,
            )
            duration_ms = int((time.time() - start_time) * 1000)

            messages = build_disambiguate_messages(candidates, context_sentences, existing_names, rag_hint)
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

            messages = build_disambiguate_messages(candidates, context_sentences, existing_names, rag_hint)

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


def _run_incremental_disambiguation_with_state(
    conn,
    state: DisambiguationState,
    incremental_disambig_client: DisambiguationLike,
    alias_keywords: list[str],
    novel_id: str,
    run_id: str,
    chunk_id: int,
    current_idx: int,
    checkpoint_interval: int,
) -> DisambiguationState:
    """
    执行增量消歧（使用新的三层状态）
    
    创建时间: 2026-03-27
    创建者: TraeAI
    任务: disambiguation-state-three-layer
    说明: 使用 DisambiguationState 替代 alias_map
    
    流程：
    1. 从 DB 抓候选名
    2. 用 discovered_names 判断哪些是真新名字
    3. 调模型得到 canonical_decisions
    4. 走 evidence validation
    5. state = apply_disambiguation_decisions(state, result)
    6. 保存 checkpoint
    """
    if (current_idx + 1) % checkpoint_interval != 0:
        return state
    
    alias_map_dict = state.get_alias_merges_dict()
    new_names = extract_new_names_from_db(conn, alias_map_dict, run_id, current_chunk_id=chunk_id)
    
    truly_new_names: list[NameCountCandidate] = [
        name for name in new_names if name["name"] not in state.discovered_names
    ]
    
    if not truly_new_names:
        return state
    
    context_sentences = build_context_sentences(conn, truly_new_names, alias_keywords, run_id=run_id)
    existing_names = list(state.known_canonical_names)
    
    result = _retry_disambig(
        incremental_disambig_client,
        truly_new_names,
        context_sentences,
        existing_names,
        stage_name="incremental disambiguation",
        run_id=run_id,
    )
    
    result = validate_confidence_with_evidence(result, existing_names, context_sentences)
    
    new_state = apply_disambiguation_decisions(state, result)
    
    if new_state != state:
        logger.debug(
            f"DisambiguationState updated: "
            f"{len(new_state.discovered_names)} discovered, "
            f"{len(new_state.known_canonical_names)} canonicals, "
            f"{len(new_state.alias_merges)} merges"
        )
        
        new_relations = _normalize_relations_with_alias_map(
            result.entity_relations, new_state.get_alias_merges_dict()
        )
        merged_relations = _merge_relations(list(new_state.pending_relations), new_relations)
        
        new_state = new_state.with_updates(pending_relations=tuple(merged_relations))
        
        _save_disambig_checkpoint_state(conn, run_id, new_state)
    
    return new_state


def _run_final_disambiguation_with_state(
    conn,
    state: DisambiguationState,
    full_disambig_client: DisambiguationLike,
    alias_keywords: list[str],
    novel_id: str,
    run_id: str,
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
        rag_hint = _build_existing_character_hint_from_db(conn, all_names, existing_names, alias_keywords, run_id)
        result = _retry_disambig(
            full_disambig_client,
            candidate_payload,
            context_sentences,
            existing_names,
            stage_name="final disambiguation",
            run_id=run_id,
            rag_hint=rag_hint,
        )
        result = validate_confidence_with_evidence(result, existing_names, context_sentences)
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
    
    if new_state != state:
        logger.info(
            f"Final disambiguation completed: "
            f"{len(new_state.discovered_names)} discovered, "
            f"{len(new_state.known_canonical_names)} canonicals, "
            f"{len(new_state.alias_merges)} merges"
        )
    
    ann_repo = AnnotationRepository(conn)
    canonical_to_entity_id = ann_repo.ensure_canonical_entities(
        run_id,
        new_state.known_canonical_names,
        novel_id=novel_id,
    )
    ann_repo.apply_alias_merges(run_id, new_state.get_alias_merges_dict())
    ann_repo.create_entity_alias_rows(
        run_id,
        new_state.get_alias_merges_dict(),
        novel_id=novel_id,
        canonical_to_entity_id=canonical_to_entity_id,
    )
    logger.info(
        "Stateful final disambiguation persisted: {} canonicals, {} merges",
        len(new_state.known_canonical_names),
        len(new_state.alias_merges),
    )
    
    final_relations = _normalize_relations_with_alias_map(
        result.entity_relations, new_state.get_alias_merges_dict()
    )
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
    _save_disambig_checkpoint_state(conn, run_id, new_state)
    
    return new_state
