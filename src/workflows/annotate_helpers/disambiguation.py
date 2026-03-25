"""
标注辅助函数模块 - 消歧处理

创建时间: 2026-03-13
创建者: TraeAI
任务: 项目文件结构整理与拆解

修改历史:
- 2026-03-14: 从 cli.annotate_helpers 迁移，解决循环依赖
- 2026-03-14: 添加 run_id 参数，使用 Repository 模式
- 2026-03-15: 移除向后兼容代码，只使用 Repository 模式
- 2026-03-16: 增量消歧只维护内存 alias_map，添加 checkpoint 机制

修改时间: 2026-03-20
修改者: TraeAI
任务: fix-hardcoded-relation-types
修改内容: 移除硬编码的 VALID_HIERARCHICAL_RELATION_TYPES，改为从配置动态读取

说明: 本模块包含人名消歧相关的辅助函数。
"""

from __future__ import annotations

import json
import time
from collections import defaultdict
from typing import Any

from loguru import logger
from sqlalchemy import text

from src.config import settings
from src.models.interfaces import DisambiguationLike
from src.models.local.disambiguation import ExtendedDisambigResult
from src.storage.repositories import AnnotationRepository
from src.storage.repositories.annotation.characters import fetch_all_character_names

from .sentence import build_context_sentences

DISAMBIG_CONFIDENCE_LOW = "low"
DISAMBIG_CONFIDENCE_MEDIUM = "medium"
DISAMBIG_CONFIDENCE_HIGH = "high"
VALID_DISAMBIG_CONFIDENCE = {
    DISAMBIG_CONFIDENCE_LOW,
    DISAMBIG_CONFIDENCE_MEDIUM,
    DISAMBIG_CONFIDENCE_HIGH,
}

DISAMBIG_STATE_RESOLVED = "resolved"
DISAMBIG_STATE_REVIEW = "review"
DISAMBIG_STATE_UNRESOLVED = "unresolved"

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


def _dedupe_relations(relations: list[dict[str, str]] | None) -> list[dict[str, str]]:
    """按 (from, to, type) 去重关系并保留顺序。"""
    if not relations:
        return []
    seen: set[tuple[str, str, str]] = set()
    deduped: list[dict[str, str]] = []
    for rel in relations:
        from_name = rel.get("from")
        to_name = rel.get("to")
        rel_type = rel.get("type")
        if not from_name or not to_name or not rel_type:
            continue
        key = (from_name, to_name, rel_type)
        if key in seen:
            continue
        seen.add(key)
        deduped.append({"from": from_name, "to": to_name, "type": rel_type})
    return deduped


def _normalize_relations_with_alias_map(
    relations: list[dict[str, str]] | None,
    alias_map: dict[str, str],
) -> list[dict[str, str]]:
    """按 alias_map 归一关系实体名后去重。"""
    if not relations:
        return []
    normalized: list[dict[str, str]] = []
    for rel in relations:
        from_name = rel.get("from")
        to_name = rel.get("to")
        rel_type = rel.get("type")
        if not from_name or not to_name or not rel_type:
            continue
        normalized.append(
            {
                "from": alias_map.get(from_name, from_name),
                "to": alias_map.get(to_name, to_name),
                "type": rel_type,
            }
        )
    return _dedupe_relations(normalized)


def _merge_relations(
    first: list[dict[str, str]] | None,
    second: list[dict[str, str]] | None,
) -> list[dict[str, str]]:
    """合并两批关系并去重。"""
    return _dedupe_relations((first or []) + (second or []))

def _extract_retryable_relations(skipped_relations: list[dict[str, Any]] | None) -> list[dict[str, str]]:
    """Extract retryable relations from skipped results for checkpoint recovery."""
    if not skipped_relations:
        return []

    retryable: list[dict[str, str]] = []
    retryable_reasons = {"from_entity_not_found", "to_entity_not_found"}

    for item in skipped_relations:
        reason = item.get("reason")
        relation = item.get("relation")

        if not isinstance(relation, dict):
            continue

        if reason in retryable_reasons or (isinstance(reason, str) and reason.startswith("insert_error:")):
            retryable.append(relation)

    return _dedupe_relations(retryable)


def _save_disambig_checkpoint(
    conn,
    run_id: str,
    alias_map: dict[str, str],
    entity_relations: list[dict[str, str]] | None = None,
    disambig_states: DisambigStateSnapshot | None = None,
) -> None:
    """
    保存消歧检查点

    修改时间: 2026-03-20
    修改者: TraeAI
    任务: fix-postgresql-transaction-error
    修改内容: 简化代码，依赖正确的表结构
    """
    try:
        params = {
            "run_id": run_id,
            "alias_map": json.dumps(alias_map),
            "updated_at": time.time(),
            "entity_relations": json.dumps(entity_relations) if entity_relations else None,
            "disambig_states": json.dumps(disambig_states) if disambig_states else None,
        }
        conn.execute(
            text("""
            INSERT INTO disambig_checkpoint (run_id, alias_map, updated_at, entity_relations, disambig_states)
            VALUES (:run_id, :alias_map, :updated_at, :entity_relations, :disambig_states)
            ON CONFLICT (run_id) DO UPDATE SET
                alias_map = EXCLUDED.alias_map,
                updated_at = EXCLUDED.updated_at,
                entity_relations = EXCLUDED.entity_relations,
                disambig_states = EXCLUDED.disambig_states
        """),
            params,
        )
        conn.commit()
        logger.debug(f"disambig checkpoint saved: {len(alias_map)} entries")
    except Exception as e:
        logger.error(f"failed to save disambig checkpoint: {e}")
        raise


def _load_disambig_checkpoint(conn, run_id: str) -> tuple[dict[str, str] | None, list[dict[str, str]] | None]:
    """
    加载消歧检查点

    修改时间: 2026-03-20
    修改者: TraeAI
    任务: fix-postgresql-transaction-error
    修改内容: 简化代码，依赖正确的表结构

    Returns:
        (alias_map, entity_relations): 别名映射和关系数据
    """
    try:
        result = conn.execute(
            text("SELECT alias_map, entity_relations FROM disambig_checkpoint WHERE run_id = :run_id"),
            {"run_id": run_id},
        ).fetchone()

        if result:
            alias_map = json.loads(result[0]) if result[0] else {}
            entity_relations = json.loads(result[1]) if result[1] else None
            logger.info(f"disambig checkpoint loaded: {len(alias_map)} entries, relations={len(entity_relations) if entity_relations else 0}")
            return alias_map, entity_relations
    except Exception as e:
        logger.warning(f"failed to load disambig checkpoint: {e}")

    return None, None


def _load_disambig_states(conn, run_id: str) -> DisambigStateSnapshot | None:
    """Load optional disambiguation state snapshot from checkpoint."""
    try:
        result = conn.execute(
            text("SELECT disambig_states FROM disambig_checkpoint WHERE run_id = :run_id"),
            {"run_id": run_id},
        ).fetchone()
        if not result or not result[0]:
            return None

        loaded = json.loads(result[0])
        if not isinstance(loaded, dict):
            return None

        normalized: DisambigStateSnapshot = {}
        for name, payload in loaded.items():
            if not isinstance(name, str) or not isinstance(payload, dict):
                continue
            state = str(payload.get("state", DISAMBIG_STATE_UNRESOLVED))
            confidence = _normalize_disambig_confidence(payload.get("confidence"))
            canonical = str(payload.get("canonical", name))
            normalized[name] = {
                "state": state,
                "confidence": confidence,
                "canonical": canonical,
            }
        return normalized
    except Exception as e:
        logger.error(f"failed to load disambig states: {e}")
        raise


def _save_disambiguation_interaction(
    client: DisambiguationLike,
    run_id: str | None,
    candidates: list,
    context_sentences: dict,
    existing_names: list[str] | None,
    result: Any,
    stage_name: str,
    attempt_number: int,
    duration_ms: int,
) -> None:
    """
    保存消歧阶段的模型交互记录

    创建时间: 2026-03-19
    创建者: TraeAI
    任务: 添加消歧阶段模型交互记录保存
    """
    if not run_id:
        return

    try:
        import json

        from src.models.local.disambiguation import build_disambiguate_messages
        from src.storage.db import get_session_factory
        from src.storage.repositories.model_interaction_repository import ModelInteractionRepository

        Session = get_session_factory()
        session = Session()
        try:
            repo = ModelInteractionRepository(session)

            # 构建消息
            messages = build_disambiguate_messages(candidates, context_sentences, existing_names, None)
            prompt_text = "\n\n".join([f"{msg['role']}: {msg['content']}" for msg in messages])

            # 构建响应内容
            if isinstance(result, ExtendedDisambigResult):
                # ExtendedDisambigResult
                response_dict = {
                    "alias_map": result.alias_map,
                    "alias_confidence": result.alias_confidence if hasattr(result, "alias_confidence") else {},
                    "entity_types": result.entity_types if hasattr(result, 'entity_types') else {},
                    "entity_relations": result.entity_relations if hasattr(result, 'entity_relations') else [],
                }
            elif isinstance(result, dict):
                response_dict = {"alias_map": result, "alias_confidence": {}, "entity_types": {}, "entity_relations": []}
            else:
                response_dict = {"alias_map": {}, "alias_confidence": {}, "entity_types": {}, "entity_relations": []}

            response_text = json.dumps(response_dict, ensure_ascii=False)

            # 提取 thinking_content（如果存在）
            thinking_content = getattr(result, "_thinking_content", None)
            thinking_chars = len(thinking_content) if thinking_content else 0
            has_thinking = bool(thinking_content and thinking_content.strip())

            # 判断是否是云端模型
            is_cloud = client.is_cloud_api()

            repo.save_interaction(
                run_id=run_id,
                chunk_id=None,  # 消歧阶段没有特定 chunk_id
                interaction_type="disambiguate",
                phase=stage_name.replace(" ", "_"),
                attempt_number=attempt_number,
                model_name=client._config.model,
                model_provider="cloud" if is_cloud else "local",
                prompt=prompt_text,
                response=response_text,
                thinking=thinking_content,
                response_chars=len(response_text),
                thinking_chars=thinking_chars,
                has_thinking=has_thinking,
                status="success",
                duration_ms=duration_ms,
            )
        finally:
            session.close()
    except Exception as e:
        # 检查是否是外键约束错误
        error_str = str(e).lower()
        if "foreignkeyviolation" in error_str or "外键约束" in error_str or "foreign key" in error_str:
            # 外键约束错误是因为 chunk 尚未提交到数据库
            # 这是预期的行为，在并行处理或新 session 中可能看不到主 session 未提交的数据
            logger.debug("Skipping disambiguation interaction save due to foreign key constraint")
        else:
            logger.warning(f"Failed to save disambiguation interaction: {e}")


def _retry_disambig(
    client: DisambiguationLike,
    candidates: list[str] | list[dict],
    context_sentences: dict[str, str],
    existing_names: list[str],
    stage_name: str,
    run_id: str | None = None,
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
    """
    max_retries = 3
    last_exception = None

    for attempt in range(1, max_retries + 1):
        start_time = time.time()
        try:
            result = client.disambiguate_characters(
                candidates=candidates,
                context_sentences=context_sentences,
                existing_names=existing_names if existing_names else None,
            )
            duration_ms = int((time.time() - start_time) * 1000)

            # 保存模型交互记录
            _save_disambiguation_interaction(
                client=client,
                run_id=run_id,
                candidates=candidates,
                context_sentences=context_sentences,
                existing_names=existing_names,
                result=result,
                stage_name=stage_name,
                attempt_number=attempt,
                duration_ms=duration_ms,
            )

            return result
        except Exception as e:
            last_exception = e
            duration_ms = int((time.time() - start_time) * 1000)

            # 保存失败的交互记录
            _save_disambiguation_interaction(
                client=client,
                run_id=run_id,
                candidates=candidates,
                context_sentences=context_sentences,
                existing_names=existing_names,
                result={"error": str(e)},
                stage_name=stage_name,
                attempt_number=attempt,
                duration_ms=duration_ms,
            )

            if attempt < max_retries:
                logger.warning(f"{stage_name} failed (attempt {attempt}), retrying: {e}")
                time.sleep(1)
            else:
                logger.error(f"{stage_name} failed after {max_retries} attempts: {e}")
                raise last_exception from None


def extract_new_names_from_db(
    conn,
    alias_map: dict[str, str],
    run_id: str,
    current_chunk_id: int | None = None,
) -> list[dict[str, int]]:
    """
    从数据库中提取新出现的人名（带频次）

    基于当前 chunk 及之前所有 chunk 的标注结果，提取不在 alias_map 中的新人物名。

    修改时间: 2026-03-19
    修改者: TraeAI
    任务: 修复增量消歧只提取当前chunk的问题
    修改内容: 从所有已标注的chunk中提取新名字，使用 fetch_chunk_characters_full

    修改时间: 2026-03-19
    修改者: TraeAI
    任务: 修复候选人名没有频次的问题
    修改内容: 返回带频次的字典列表 [{"name": "伯安", "count": 312}, ...]
    """
    existing_names = set(alias_map.keys()) | set(alias_map.values()) if alias_map else set()
    all_names = fetch_all_character_names(conn, run_id, max_chunk_id=current_chunk_id)

    candidates: list[dict[str, int]] = []
    for item in all_names:
        name = str(item.get("name", "")).strip()
        if not name or name in existing_names:
            continue
        raw_count = item.get("count", 0)
        try:
            count = int(raw_count)
        except (TypeError, ValueError):
            count = 0
        candidates.append({"name": name, "count": count})

    return candidates


def _normalize_disambig_confidence(confidence: Any) -> str:
    if isinstance(confidence, str):
        normalized = confidence.lower().strip()
        if normalized in VALID_DISAMBIG_CONFIDENCE:
            return normalized
    return DISAMBIG_CONFIDENCE_MEDIUM


def _ensure_state_snapshot_has_known_names(
    alias_map: dict[str, str],
    state_snapshot: DisambigStateSnapshot | None,
) -> DisambigStateSnapshot:
    snapshot: DisambigStateSnapshot = dict(state_snapshot or {})
    for alias, canonical in alias_map.items():
        snapshot.setdefault(
            alias,
            {
                "state": DISAMBIG_STATE_RESOLVED,
                "confidence": DISAMBIG_CONFIDENCE_HIGH,
                "canonical": canonical,
            },
        )
        snapshot.setdefault(
            canonical,
            {
                "state": DISAMBIG_STATE_RESOLVED,
                "confidence": DISAMBIG_CONFIDENCE_HIGH,
                "canonical": canonical,
            },
        )
    return snapshot


def _build_alias_and_state_updates(
    result: ExtendedDisambigResult,
    alias_map: dict[str, str],
    state_snapshot: DisambigStateSnapshot | None,
) -> tuple[dict[str, str], DisambigStateSnapshot]:
    merged_snapshot = _ensure_state_snapshot_has_known_names(alias_map, state_snapshot)
    alias_updates: dict[str, str] = {}
    state_updates: DisambigStateSnapshot = {}

    for name, canonical in result.alias_map.items():
        confidence = _normalize_disambig_confidence(result.alias_confidence.get(name))
        canonical_name = canonical or name

        previous_canonical = alias_map.get(name)
        has_existing_alias_resolution = previous_canonical is not None and previous_canonical != name
        resolved_conflict = (
            confidence == DISAMBIG_CONFIDENCE_HIGH
            and has_existing_alias_resolution
            and previous_canonical != canonical_name
        )

        if confidence == DISAMBIG_CONFIDENCE_HIGH and not resolved_conflict:
            state = DISAMBIG_STATE_RESOLVED
            alias_updates[name] = canonical_name
            state_updates[canonical_name] = {
                "state": DISAMBIG_STATE_RESOLVED,
                "confidence": DISAMBIG_CONFIDENCE_HIGH,
                "canonical": canonical_name,
            }
        elif confidence == DISAMBIG_CONFIDENCE_MEDIUM or resolved_conflict:
            state = DISAMBIG_STATE_REVIEW
            if not has_existing_alias_resolution:
                alias_updates[name] = name
        else:
            state = DISAMBIG_STATE_UNRESOLVED
            if not has_existing_alias_resolution:
                alias_updates[name] = name

        state_updates[name] = {
            "state": state,
            "confidence": confidence,
            "canonical": canonical_name,
        }

    merged_snapshot.update(state_updates)
    return alias_updates, merged_snapshot


def _extract_names_from_candidates(candidates: list[str] | list[dict[str, int]]) -> list[str]:
    names: list[str] = []
    if candidates and isinstance(candidates[0], dict):
        names = [str(item.get("name", "")) for item in candidates]
    else:
        names = [str(item) for item in candidates]
    return [name for name in names if name]


def _build_candidate_payload_by_names(
    all_names: list[str] | list[dict[str, int]],
    candidate_names: list[str],
) -> list[str] | list[dict[str, int]]:
    if all_names and isinstance(all_names[0], dict):
        names_set = set(candidate_names)
        payload: list[dict[str, int]] = []
        for item in all_names:
            name = str(item.get("name", ""))
            if name in names_set:
                payload.append(item)
        return payload
    return candidate_names


def _collect_final_disambiguation_candidates(
    all_names: list[str] | list[dict[str, int]],
    alias_map: dict[str, str],
    state_snapshot: DisambigStateSnapshot | None = None,
) -> list[str]:
    """
    Build unresolved candidates for final disambiguation.

    Prefer state-based filtering:
    - skip state=resolved
    - keep state=review/unresolved/unknown
    """
    names = _extract_names_from_candidates(all_names)
    candidates: list[str] = []
    seen: set[str] = set()

    if state_snapshot:
        for name in names:
            state = state_snapshot.get(name, {}).get("state")
            if state == DISAMBIG_STATE_RESOLVED or name in seen:
                continue
            candidates.append(name)
            seen.add(name)
        return candidates

    known_names = set(alias_map.keys()) | set(alias_map.values())
    for name in names:
        if name in known_names or name in seen:
            continue
        candidates.append(name)
        seen.add(name)
    return candidates


def _run_incremental_disambiguation(
    conn,
    alias_map: dict[str, str],
    incremental_disambig_client: DisambiguationLike,
    alias_keywords: list[str],
    novel_id: str,
    run_id: str,
    chunk_id: int,
    current_idx: int,
    checkpoint_interval: int,
) -> dict[str, str]:
    """
    执行增量消歧

    修改时间: 2026-03-19
    修改者: TraeAI
    任务: fix-entity-relations-not-saved
    修改内容: 移除关系保存逻辑，增量消歧阶段不保存关系（实体尚未创建）

    修改时间: 2026-03-19
    修改者: TraeAI
    任务: 修复增量消歧间隔逻辑
    修改内容: 只在 checkpoint_interval 间隔时才执行消歧操作

    修改时间: 2026-03-19
    修改者: TraeAI
    任务: 修复增量消歧缺少上下文问题
    修改内容: 构建并传递 context_sentences 给模型
    """
    if (current_idx + 1) % checkpoint_interval != 0:
        return alias_map

    new_names = extract_new_names_from_db(conn, alias_map, run_id, current_chunk_id=chunk_id)

    if not new_names:
        return alias_map

    candidates = new_names

    context_sentences = build_context_sentences(conn, candidates, alias_keywords, run_id=run_id)
    existing_names = list(set(alias_map.values())) if alias_map else []

    result = _retry_disambig(
        incremental_disambig_client,
        candidates,
        context_sentences,
        existing_names,
        stage_name="incremental disambiguation",
        run_id=run_id,
    )

    previous_alias_map = dict(alias_map)
    state_snapshot = _load_disambig_states(conn, run_id)
    alias_updates, merged_state_snapshot = _build_alias_and_state_updates(result, alias_map, state_snapshot)
    if alias_updates:
        alias_map.update(alias_updates)

    has_alias_update = alias_map != previous_alias_map
    has_relation_update = bool(result.entity_relations)
    if has_alias_update:
        logger.debug(f"alias_map updated in memory: {len(alias_map)} entries")

    _, pending_relations = _load_disambig_checkpoint(conn, run_id)
    new_relations = _normalize_relations_with_alias_map(result.entity_relations, alias_map)
    merged_relations = _merge_relations(pending_relations, new_relations)
    if new_relations:
        logger.debug(
            "incremental disambig: cached {} relations, pending total {}",
            len(new_relations),
            len(merged_relations),
        )
    if has_alias_update or has_relation_update or merged_state_snapshot:
        _save_disambig_checkpoint(
            conn,
            run_id,
            alias_map,
            merged_relations,
            disambig_states=merged_state_snapshot,
        )

    return alias_map


def _run_final_disambiguation(
    conn,
    alias_map: dict[str, str],
    full_disambig_client: DisambiguationLike,
    alias_keywords: list[str],
    novel_id: str,
    run_id: str,
) -> dict[str, str]:
    """
    执行最终消歧

    修改时间: 2026-03-19
    修改者: TraeAI
    任务: fix-entity-relations-not-saved
    修改内容: 调整执行顺序，先创建实体再保存关系；支持恢复时处理未保存的关系

    修改时间: 2026-03-25
    修改者: TraeAI
    任务: fix-final-disambig-missing-context
    修改内容: 修复最终消解丢失频次和例句的问题，与增量消解保持一致的 prompt 格式
    """
    # 检查是否有未保存的关系数据（系统意外停止后恢复）
    _, pending_relations = _load_disambig_checkpoint(conn, run_id)
    state_snapshot = _ensure_state_snapshot_has_known_names(alias_map, _load_disambig_states(conn, run_id))
    if pending_relations:
        logger.info(f"found {len(pending_relations)} pending relations from checkpoint, will process them")

    existing_names = list(set(alias_map.values())) if alias_map else []

    if not existing_names:
        return alias_map

    all_names = fetch_all_character_names(conn, run_id)
    candidates = _collect_final_disambiguation_candidates(all_names, alias_map, state_snapshot)

    if candidates:
        candidate_payload = _build_candidate_payload_by_names(all_names, candidates)
        context_sentences = build_context_sentences(conn, candidate_payload, alias_keywords, run_id=run_id)
        result = _retry_disambig(
            full_disambig_client,
            candidate_payload,
            context_sentences,
            existing_names,
            stage_name="final disambiguation",
            run_id=run_id,
        )
    else:
        logger.info("final disambiguation skipped: no unresolved candidates")
        result = ExtendedDisambigResult(alias_map={}, entity_types={}, entity_relations=[], alias_confidence={})

    previous_alias_map = dict(alias_map)
    if result.alias_map:
        alias_updates, state_snapshot = _build_alias_and_state_updates(result, alias_map, state_snapshot)
        alias_map.update(alias_updates)
    if alias_map != previous_alias_map:
        logger.info(f"final disambiguation completed: {len(alias_map)} entries")

    # 1. 先创建实体
    if alias_map:
        ann_repo = AnnotationRepository(conn)
        ann_repo.update_character_names(run_id, alias_map, novel_id=novel_id)
        logger.info(f"character names updated in annotations: {len(alias_map)} entries")

    # 2. 再保存关系（实体必须先创建）
    # 优先处理 checkpoint 中未保存的关系（恢复场景）
    final_relations = _normalize_relations_with_alias_map(result.entity_relations, alias_map)
    relations_to_process = _merge_relations(pending_relations, final_relations)
    retryable_relations: list[dict[str, str]] = []
    if relations_to_process:
        success_count, skipped = _process_entity_relations(
            conn, novel_id, run_id, relations_to_process, result.entity_types, alias_map
        )
        logger.info(f"final disambig: processed {success_count} hierarchical relations")
        retryable_relations = _extract_retryable_relations(skipped)
        if retryable_relations:
            logger.warning(
                "final disambig: {} relations left for retry, kept in checkpoint",
                len(retryable_relations),
            )

    # 保存 checkpoint，同时保存关系数据（用于系统意外停止后恢复）
    _save_disambig_checkpoint(
        conn,
        run_id,
        alias_map,
        retryable_relations or None,
        disambig_states=state_snapshot,
    )

    return alias_map


def detect_cycle_in_relations(
    relations: list[dict[str, str]],
) -> tuple[list[dict[str, str]], list[dict[str, str]], list[list[str]]]:
    """
    检测关系中的循环依赖

    使用 DFS 检测有向图中的循环。

    Args:
        relations: 关系列表，每个关系包含 from, to, type 字段

    Returns:
        (valid_relations, skipped_relations, cycle_paths):
            有效关系列表、被跳过的关系列表、完整的循环路径列表
    """
    if not relations:
        return [], [], []

    graph = defaultdict(list)
    for rel in relations:
        graph[rel["from"]].append(rel["to"])

    visited = set()
    rec_stack = set()
    cycle_nodes = set()
    cycle_paths: list[list[str]] = []

    def dfs(node: str, path: list[str]) -> bool:
        visited.add(node)
        rec_stack.add(node)

        for neighbor in graph[node]:
            if neighbor not in visited:
                if dfs(neighbor, path + [node]):
                    return True
            elif neighbor in rec_stack:
                cycle_start = path.index(neighbor) if neighbor in path else 0
                full_cycle = path[cycle_start:] + [node, neighbor]
                cycle_nodes.update(full_cycle)
                cycle_paths.append(full_cycle)
                return True

        rec_stack.remove(node)
        return False

    for node in list(graph.keys()):
        if node not in visited:
            dfs(node, [])

    valid_relations: list[dict[str, str]] = []
    skipped_relations: list[dict[str, str]] = []

    for rel in relations:
        if rel["from"] in cycle_nodes or rel["to"] in cycle_nodes:
            skipped_relations.append(rel)
        else:
            valid_relations.append(rel)

    return valid_relations, skipped_relations, cycle_paths


def _process_entity_relations(
    conn,
    novel_id: str,
    run_id: str,
    entity_relations: list[dict[str, str]],
    entity_types: dict[str, str],
    alias_map: dict[str, str],
) -> tuple[int, list[dict[str, Any]]]:
    """
    处理实体间的层级关系

    创建时间: 2026-03-18
    创建者: TraeAI
    任务: entity-type-relation-extraction
    说明: 将消歧结果中的关系写入数据库

    修改时间: 2026-03-20
    修改者: TraeAI
    任务: fix-hardcoded-relation-types
    修改内容: 从配置读取有效关系类型，而非硬编码

    Args:
        conn: 数据库连接
        novel_id: 小说ID
        run_id: 运行ID
        entity_relations: 关系列表
        entity_types: 实体类型映射
        alias_map: 别名映射

    Returns:
        (success_count, skipped_relations): 成功写入的关系数量、被跳过的关系列表
    """
    from src.storage.repositories import EntityRepository

    if not entity_relations:
        return 0, []

    entity_repo = EntityRepository(conn)

    valid_relations, cycle_skipped, cycle_paths = detect_cycle_in_relations(entity_relations)

    if cycle_paths:
        logger.warning(
            "检测到循环依赖关系",
            cycle_paths=cycle_paths,
            skipped_count=len(cycle_skipped),
        )

    success_count = 0
    skipped_relations: list[dict[str, Any]] = list(cycle_skipped)

    valid_relation_types = set(settings.analysis.valid_hierarchical_relation_types)

    for rel in valid_relations:
        raw_from_name = rel.get("from")
        raw_to_name = rel.get("to")
        rel_type = rel.get("type")
        from_name = alias_map.get(raw_from_name, raw_from_name) if raw_from_name else None
        to_name = alias_map.get(raw_to_name, raw_to_name) if raw_to_name else None

        if not from_name or not to_name or not rel_type:
            skipped_relations.append({
                "relation": rel,
                "reason": "missing_fields",
            })
            continue

        if rel_type not in valid_relation_types:
            logger.warning(f"无效的关系类型: {rel_type}, 跳过关系 {rel}")
            skipped_relations.append({
                "relation": rel,
                "reason": "invalid_relation_type",
            })
            continue

        from_entity_id = entity_repo.get_entity_id_by_name(novel_id, from_name, run_id)
        to_entity_id = entity_repo.get_entity_id_by_name(novel_id, to_name, run_id)

        if from_entity_id is None:
            skipped_relations.append({
                "relation": rel,
                "reason": "from_entity_not_found",
            })
            continue

        if to_entity_id is None:
            skipped_relations.append({
                "relation": rel,
                "reason": "to_entity_not_found",
            })
            continue

        try:
            entity_repo.insert_entity_relation(
                novel_id=novel_id,
                from_entity=from_entity_id,
                to_entity=to_entity_id,
                rel_type=rel_type,
                rel_category="hierarchical",
                run_id=run_id,
            )
            success_count += 1
        except Exception as e:
            logger.error(f"插入关系失败: {rel}, 错误: {e}")
            skipped_relations.append({
                "relation": rel,
                "reason": f"insert_error: {str(e)}",
            })

    if skipped_relations:
        logger.warning(
            f"关系处理完成: 成功 {success_count}, 跳过 {len(skipped_relations)}",
            skipped_relations=skipped_relations,
        )

    return success_count, skipped_relations

