"""
Disambiguation helpers for the annotate workflow.

修改历史:
- 2026-03-14: 添加 run_id 参数支持，使用 Repository 模式
- 2026-03-15: 使用 SQLAlchemy text() 包装 SQL 语句
- 2026-03-16: 增量消歧只维护内存 alias_map，添加 checkpoint 机制

修改时间: 2026-03-18
修改者: TraeAI
任务: entity-type-relation-extraction
修改内容:
- _retry_disambig 返回 ExtendedDisambigResult
- 新增 _process_entity_relations 处理层级关系
- 新增 _detect_cycle_in_relations 循环依赖检测
"""

from __future__ import annotations

import json
import re
import time
from collections import defaultdict
from typing import TYPE_CHECKING, Any

from loguru import logger
from sqlalchemy import text

from src.config import settings
from src.config.schemas import ANNOTATION_CONFIG
from src.models.local.disambiguation import ExtendedDisambigResult
from src.models.local.unified_client import UnifiedModelClient
from src.workflows.retry_utils import MaxRetriesExceededError, RetryableOperation

from .sentence import build_context_sentences, extract_new_names_from_db

if TYPE_CHECKING:
    import networkx as nx
    from src.rag import RAGRetriever

DISAMBIG_MAX_RETRIES = ANNOTATION_CONFIG.disambig_max_retries
# 使用 settings.analysis 中的配置，允许从 settings.json 自定义
VALID_HIERARCHICAL_RELATION_TYPES = settings.analysis.valid_hierarchical_relation_types
VALID_ENTITY_TYPES = ANNOTATION_CONFIG.valid_entity_types


def _save_disambig_checkpoint(conn, run_id: str, alias_map: dict[str, str]) -> None:
    """保存消歧 checkpoint 到数据库"""
    conn.execute(
        text("""
            INSERT INTO disambig_checkpoint (run_id, alias_map, updated_at)
            VALUES (:run_id, :alias_map, :updated_at)
            ON CONFLICT (run_id) DO UPDATE SET
                alias_map = EXCLUDED.alias_map,
                updated_at = EXCLUDED.updated_at
        """),
        {"run_id": run_id, "alias_map": json.dumps(alias_map), "updated_at": time.time()},
    )
    conn.commit()
    logger.debug(f"disambig checkpoint saved for run_id={run_id}")


def _load_disambig_checkpoint(conn, run_id: str) -> dict[str, str] | None:
    """从数据库加载消歧 checkpoint"""
    row = conn.execute(
        text("SELECT alias_map FROM disambig_checkpoint WHERE run_id = :run_id"),
        {"run_id": run_id},
    ).fetchone()

    if row:
        logger.info(f"disambig checkpoint loaded for run_id={run_id}")
        return json.loads(row[0])
    return None


class DisambiguationMaxRetriesExceededError(Exception):
    """消歧重试次数耗尽异常"""
    pass


def _save_disambig_interaction(
    client: UnifiedModelClient,
    run_id: str | None,
    candidates: list,
    context_sentences: dict,
    existing_names: list[str] | None,
    rag_hint: str | None,
    result: ExtendedDisambigResult,
    stage_name: str,
    attempt_number: int,
    duration_ms: int,
) -> None:
    """
    保存消歧交互记录

    创建时间: 2026-03-19
    创建者: TraeAI
    任务: 添加消歧阶段模型交互记录保存
    """
    if not run_id:
        return

    try:
        from src.storage.db import get_session_factory
        from src.storage.repositories.model_interaction_repository import ModelInteractionRepository
        from src.models.local.disambiguation import build_disambiguate_messages

        Session = get_session_factory()
        session = Session()
        try:
            repo = ModelInteractionRepository(session)
            messages = build_disambiguate_messages(candidates, context_sentences, existing_names, rag_hint)
            prompt_text = "\n\n".join([f"{msg['role']}: {msg['content']}" for msg in messages])

            # 构建响应内容 - 处理 ExtendedDisambigResult 或 dict
            if isinstance(result, ExtendedDisambigResult):
                response_dict = {
                    "alias_map": result.alias_map,
                    "entity_types": result.entity_types,
                    "entity_relations": result.entity_relations if result.entity_relations else [],
                }
            elif isinstance(result, dict):
                response_dict = {"alias_map": result, "entity_types": {}, "entity_relations": []}
            else:
                response_dict = {"alias_map": {}, "entity_types": {}, "entity_relations": []}
            response_text = json.dumps(response_dict, ensure_ascii=False)

            is_cloud = hasattr(client, '_config') and hasattr(client._config, 'base_url') and 'cloud' in str(client._config.base_url).lower()

            repo.save_interaction(
                run_id=run_id,
                chunk_id=None,  # 消歧阶段没有特定 chunk_id
                interaction_type="disambiguate",
                phase=stage_name.replace(" ", "_"),
                attempt_number=attempt_number,
                model_name=client._config.model if hasattr(client, '_config') else None,
                model_provider="cloud" if is_cloud else "local",
                prompt=prompt_text,
                response=response_text,
                thinking=None,  # 消歧阶段通常没有 thinking
                response_chars=len(response_text),
                thinking_chars=0,
                has_thinking=False,
                status="success",
                duration_ms=duration_ms,
            )
        finally:
            session.close()
    except Exception as e:
        logger.warning(f"Failed to save disambiguation interaction: {e}")


def _retry_disambig(
    client: UnifiedModelClient,
    candidates: list[str] | list[dict],
    context_sentences: dict[str, str],
    existing_names: list[str] | None = None,
    rag_hint: str | None = None,
    stage_name: str = "disambiguation",
    run_id: str | None = None,
) -> ExtendedDisambigResult:
    """
    带重试的人名消歧函数。

    修改时间: 2026-03-18
    修改者: TraeAI
    任务: entity-type-relation-extraction
    修改内容: 返回 ExtendedDisambigResult 类型

    修改时间: 2026-03-19
    修改者: TraeAI
    任务: 添加消歧阶段模型交互记录保存
    修改内容: 添加 run_id 参数，保存交互记录
    """
    import time
    from src.models.local.parser import DisambiguationParseError

    start_time = time.time()

    operation = RetryableOperation(
        max_retries=DISAMBIG_MAX_RETRIES,
        retryable_exceptions=(ConnectionError, TimeoutError, DisambiguationParseError),
        operation_name=stage_name,
    )

    try:
        result = operation.execute(
            client.disambiguate_characters,
            candidates,
            context_sentences=context_sentences,
            existing_names=existing_names,
            rag_hint=rag_hint,
        )

        duration_ms = int((time.time() - start_time) * 1000)

        # 保存交互记录
        _save_disambig_interaction(
            client=client,
            run_id=run_id,
            candidates=candidates,
            context_sentences=context_sentences,
            existing_names=existing_names,
            rag_hint=rag_hint,
            result=result,
            stage_name=stage_name,
            attempt_number=1,  # 简化处理，记录总耗时
            duration_ms=duration_ms,
        )

        return result
    except MaxRetriesExceededError as e:
        raise DisambiguationMaxRetriesExceededError(str(e))


def _save_anonymous_disambig_interaction(
    client: UnifiedModelClient,
    run_id: str | None,
    anonymous_names: list[str],
    anonymous_contexts: dict[str, str],
    existing_names: list[str] | None,
    existing_contexts: dict[str, str] | None,
    result: dict[str, str],
    stage_name: str,
    attempt_number: int,
    duration_ms: int,
) -> None:
    """
    保存匿名消歧交互记录

    创建时间: 2026-03-19
    创建者: TraeAI
    任务: 添加匿名消歧阶段模型交互记录保存
    """
    if not run_id:
        return

    try:
        from src.storage.db import get_session_factory
        from src.storage.repositories.model_interaction_repository import ModelInteractionRepository
        from src.models.local.disambiguation import build_anonymous_disambig_messages

        Session = get_session_factory()
        session = Session()
        try:
            repo = ModelInteractionRepository(session)
            messages = build_anonymous_disambig_messages(anonymous_names, anonymous_contexts, existing_names, existing_contexts)
            prompt_text = "\n\n".join([f"{msg['role']}: {msg['content']}" for msg in messages])

            # 构建响应内容
            response_text = json.dumps(result, ensure_ascii=False)

            is_cloud = hasattr(client, '_config') and hasattr(client._config, 'base_url') and 'cloud' in str(client._config.base_url).lower()

            repo.save_interaction(
                run_id=run_id,
                chunk_id=None,  # 消歧阶段没有特定 chunk_id
                interaction_type="disambiguate",
                phase=stage_name.replace(" ", "_"),
                attempt_number=attempt_number,
                model_name=client._config.model if hasattr(client, '_config') else None,
                model_provider="cloud" if is_cloud else "local",
                prompt=prompt_text,
                response=response_text,
                thinking=None,  # 消歧阶段通常没有 thinking
                response_chars=len(response_text),
                thinking_chars=0,
                has_thinking=False,
                status="success",
                duration_ms=duration_ms,
            )
        finally:
            session.close()
    except Exception as e:
        logger.warning(f"Failed to save anonymous disambiguation interaction: {e}")


def _retry_disambig_anonymous(
    client: UnifiedModelClient,
    anonymous_names: list[str],
    anonymous_contexts: dict[str, str],
    existing_names: list[str] | None = None,
    existing_contexts: dict[str, str] | None = None,
    stage_name: str = "anonymous disambiguation",
    run_id: str | None = None,
) -> dict[str, str]:
    """
    带重试的匿名消歧函数。

    修改时间: 2026-03-19
    修改者: TraeAI
    任务: 添加匿名消歧阶段模型交互记录保存
    修改内容: 添加 run_id 参数，保存交互记录
    """
    import time
    from src.models.local.parser import DisambiguationParseError

    start_time = time.time()

    operation = RetryableOperation(
        max_retries=DISAMBIG_MAX_RETRIES,
        retryable_exceptions=(ConnectionError, TimeoutError, DisambiguationParseError),
        operation_name=stage_name,
    )

    try:
        result = operation.execute(
            client.disambiguate_anonymous,
            anonymous_names,
            anonymous_contexts,
            existing_names=existing_names,
            existing_contexts=existing_contexts,
        )

        duration_ms = int((time.time() - start_time) * 1000)

        # 保存交互记录
        _save_anonymous_disambig_interaction(
            client=client,
            run_id=run_id,
            anonymous_names=anonymous_names,
            anonymous_contexts=anonymous_contexts,
            existing_names=existing_names,
            existing_contexts=existing_contexts,
            result=result,
            stage_name=stage_name,
            attempt_number=1,  # 简化处理，记录总耗时
            duration_ms=duration_ms,
        )

        return result
    except MaxRetriesExceededError as e:
        raise DisambiguationMaxRetriesExceededError(str(e))


def build_anonymous_contexts(conn, anonymous_names: list[str]) -> dict[str, str]:
    """为匿名占位名构建完整上下文（前一段 + 当前段 + 后一段）"""
    contexts = {}
    for name in anonymous_names:
        match = re.match(r"^匿名_C(\d+)_\d+$", name)
        if not match:
            continue
        chunk_id = int(match.group(1))

        row = conn.execute(
            text("SELECT text FROM chunks WHERE chunk_id = :chunk_id"),
            {"chunk_id": chunk_id},
        ).fetchone()
        if not row:
            continue
        current_text = row[0]

        prev_row = conn.execute(
            text("SELECT text FROM chunks WHERE chunk_id = :chunk_id"),
            {"chunk_id": chunk_id - 1},
        ).fetchone()
        prev_text = prev_row[0] if prev_row else ""

        next_row = conn.execute(
            text("SELECT text FROM chunks WHERE chunk_id = :chunk_id"),
            {"chunk_id": chunk_id + 1},
        ).fetchone()
        next_text = next_row[0] if next_row else ""

        context = f"[前文]\n{prev_text}\n\n[当前段落]\n{current_text}\n\n[后文]\n{next_text}"
        contexts[name] = context

    return contexts


def _run_incremental_disambiguation(
    conn,
    chunk_id: int,
    alias_map: dict[str, str],
    incremental_disambig_client: UnifiedModelClient,
    rag_retriever: "RAGRetriever | None",
    character_graph: "nx.Graph | None",
    alias_keywords: list[str],
    incremental_interval: int,
    current_idx: int,
    run_id: str,
    novel_id: str,
    checkpoint_interval: int = ANNOTATION_CONFIG.checkpoint_interval,
) -> dict[str, str]:
    """
    执行增量消歧

    修改时间: 2026-03-18
    修改者: TraeAI
    任务: entity-type-relation-extraction
    修改内容: 处理 ExtendedDisambigResult 返回格式，调用 _process_entity_relations
    """
    from src.knowledge.graph import get_active_nodes_in_range

    if (current_idx + 1) % incremental_interval != 0:
        return alias_map

    new_names = extract_new_names_from_db(conn, alias_map, current_chunk_id=chunk_id)
    if not new_names:
        return alias_map

    logger.info(f"incremental disambiguation for {len(new_names)} new names")
    ctx = build_context_sentences(conn, new_names, alias_keywords if alias_keywords else None)
    existing_names = list(set(alias_map.values())) if alias_map else None

    rag_hint: str | None = None
    if rag_retriever:
        all_aliases = rag_retriever.get_known_aliases()
        if all_aliases:
            candidate_names = list(set(all_aliases.values()))[:5]
            rag_hint = f"<Known_Alias_Candidates>{'。'.join(candidate_names)}</Known_Alias_Candidates>"
        if settings.rag.level2_enabled and character_graph:
            candidates = get_active_nodes_in_range(character_graph, max(0, chunk_id - 10), chunk_id)
            if candidates:
                rag_hint = f"<Alias_Candidates>{'。'.join(candidates[:5])}</Alias_Candidates>"

    result = _retry_disambig(
        incremental_disambig_client,
        new_names,
        ctx,
        existing_names=existing_names,
        rag_hint=rag_hint,
        stage_name="incremental disambiguation",
        run_id=run_id,
    )

    if result.alias_map:
        alias_map.update(result.alias_map)
        logger.debug(f"alias_map updated in memory: {len(alias_map)} entries")

        if result.entity_relations:
            success_count, skipped = _process_entity_relations(
                conn, novel_id, run_id, result.entity_relations, result.entity_types, result.alias_map
            )
            logger.info(f"incremental disambig: processed {success_count} hierarchical relations")

        if (current_idx + 1) % checkpoint_interval == 0:
            _save_disambig_checkpoint(conn, run_id, alias_map)

    return alias_map


def _run_final_disambiguation(
    conn,
    alias_map: dict[str, str],
    full_disambig_client: UnifiedModelClient,
    alias_keywords: list[str],
    novel_id: str,
    run_id: str,
) -> dict[str, str]:
    """
    执行最终消歧

    修改时间: 2026-03-18
    修改者: TraeAI
    任务: entity-type-relation-extraction
    修改内容: 处理 ExtendedDisambigResult 返回格式，调用 _process_entity_relations
    """
    from src.storage.repositories import AnnotationRepository

    logger.info("collecting all character names for final disambiguation")
    ann_repo = AnnotationRepository(conn)
    all_names = ann_repo.fetch_all_character_names(run_id)

    if not all_names:
        return alias_map

    logger.info(f"final disambiguation for {len(all_names)} character names")
    ctx = build_context_sentences(conn, all_names, alias_keywords if alias_keywords else None)
    existing_names = list(set(alias_map.values())) if alias_map else None

    result = _retry_disambig(
        full_disambig_client,
        all_names,
        ctx,
        existing_names=existing_names,
        stage_name="final disambiguation",
        run_id=run_id,
    )

    # 处理 ExtendedDisambigResult 或 dict 返回类型
    if isinstance(result, ExtendedDisambigResult):
        if result.alias_map:
            alias_map.update(result.alias_map)
        logger.info("character names updated with alias map")

        if result.entity_relations:
            success_count, skipped = _process_entity_relations(
                conn, novel_id, run_id, result.entity_relations, result.entity_types, result.alias_map
            )
            logger.info(f"final disambig: processed {success_count} hierarchical relations")
    elif isinstance(result, dict):
        # 处理 dict 返回类型（向后兼容）
        if result:
            alias_map.update(result)
        logger.info("character names updated with alias map (dict format)")

    if alias_map:
        ann_repo.update_character_names(run_id, alias_map, novel_id=novel_id)
        ann_repo.apply_alias_corrections(run_id, alias_map)
        logger.info(f"applied alias_map with {len(alias_map)} entries to database")

    return alias_map


def _run_anonymous_disambiguation(
    conn,
    alias_map: dict[str, str],
    full_disambig_client: UnifiedModelClient,
    alias_keywords: list[str],
    novel_id: str,
    run_id: str,
) -> dict[str, str]:
    """执行匿名消歧"""
    from src.storage.repositories import AnnotationRepository

    anonymous_names = [name for name in alias_map.values() if re.match(r"^匿名_C\d+_\d+$", name)]

    if not anonymous_names:
        return alias_map

    logger.info(f"anonymous disambiguation for {len(anonymous_names)} names")
    anonymous_contexts = build_anonymous_contexts(conn, anonymous_names)
    existing_names = list(set(alias_map.values()) - set(anonymous_names))
    existing_contexts = (
        build_context_sentences(conn, existing_names, alias_keywords if alias_keywords else None)
        if existing_names
        else None
    )

    anonymous_alias_map = _retry_disambig_anonymous(
        full_disambig_client,
        anonymous_names,
        anonymous_contexts,
        existing_names=existing_names if existing_names else None,
        existing_contexts=existing_contexts,
        stage_name="anonymous disambiguation",
        run_id=run_id,
    )

    if anonymous_alias_map:
        for anon_name, real_name in anonymous_alias_map.items():
            if real_name != anon_name:
                for alias, canonical in list(alias_map.items()):
                    if canonical == anon_name:
                        alias_map[alias] = real_name
        ann_repo = AnnotationRepository(conn)
        ann_repo.update_character_names(run_id, anonymous_alias_map, novel_id=novel_id)
        logger.info(f"anonymous disambiguation completed: {len(anonymous_alias_map)} names processed")

    return alias_map


def _build_character_knowledge_graph(
    conn,
    novel_id: str,
    use_rag: bool,
    run_id: str,
) -> bool:
    """
    构建角色知识图谱
    Returns:
        bool: 是否成功构建图谱
    """
    if not use_rag or not settings.rag.enabled:
        return False

    from src.knowledge import build_character_graph, save_graph_to_db
    from src.storage.repositories import EntityRepository, StatsRepository

    logger.info("building character knowledge graph")
    entity_repo = EntityRepository(conn)
    stats_repo = StatsRepository(conn)
    character_graph = build_character_graph(entity_repo, run_id, novel_id)
    save_graph_to_db(stats_repo, run_id, character_graph, "character_graph")
    logger.info(
        f"saved graph: {character_graph.number_of_nodes()} nodes, {character_graph.number_of_edges()} edges"
    )

    return True


def detect_cycle_in_relations(
    relations: list[dict[str, str]],
) -> tuple[list[dict[str, str]], list[dict[str, str]], list[list[str]]]:
    """
    检测关系列表中的循环依赖

    创建时间: 2026-03-18
    创建者: TraeAI
    任务: entity-type-relation-extraction
    说明: 使用 DFS 算法检测有向图中的环

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

    for rel in valid_relations:
        from_name = rel.get("from")
        to_name = rel.get("to")
        rel_type = rel.get("type")

        if not from_name or not to_name or not rel_type:
            skipped_relations.append({
                "relation": rel,
                "reason": "missing_fields",
            })
            continue

        if rel_type not in VALID_HIERARCHICAL_RELATION_TYPES:
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
