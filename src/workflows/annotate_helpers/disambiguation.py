"""
Disambiguation helpers for the annotate workflow.

修改时间: 2026-03-14
修改者: TraeAI
任务: workflows 使用 Repository 模式重构
修改内容: 添加 run_id 参数支持，使用 AnnotationRepository 替代直接调用 operations 函数

修改时间: 2026-03-15
修改者: TraeAI
任务: postgresql-migration
修改内容: 使用 SQLAlchemy text() 包装 SQL 语句，替换 ? 占位符为命名参数

修改时间: 2026-03-16
修改者: TraeAI
任务: fix-disambiguation-three-phase
修改内容: 
- 增量消歧只维护内存 alias_map，不写数据库
- 添加 checkpoint 保存/加载机制
"""

from __future__ import annotations

import json
import re
import time
from typing import TYPE_CHECKING

from loguru import logger
from sqlalchemy import text

from src.config import settings
from src.models.local.unified_client import UnifiedModelClient
from src.workflows.retry_utils import MaxRetriesExceededError, RetryableOperation

from .sentence import build_context_sentences, extract_new_names_from_db

if TYPE_CHECKING:
    import networkx as nx
    from src.rag import RAGRetriever


DISAMBIG_MAX_RETRIES = 3


def _save_disambig_checkpoint(conn, run_id: str, alias_map: dict[str, str]) -> None:
    """
    保存消歧 checkpoint 到数据库

    创建时间: 2026-03-16
    创建者: TraeAI
    任务: fix-disambiguation-three-phase
    说明: 将当前 alias_map 保存到数据库，支持断点续传
    """
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
    """
    从数据库加载消歧 checkpoint

    创建时间: 2026-03-16
    创建者: TraeAI
    任务: fix-disambiguation-three-phase
    说明: 从数据库加载之前保存的 alias_map，用于断点续传

    Returns:
        之前保存的 alias_map，如果不存在则返回 None
    """
    row = conn.execute(
        text("SELECT alias_map FROM disambig_checkpoint WHERE run_id = :run_id"),
        {"run_id": run_id},
    ).fetchone()

    if row:
        logger.info(f"disambig checkpoint loaded for run_id={run_id}")
        return json.loads(row[0])
    return None


class DisambiguationMaxRetriesExceededError(Exception):
    """
    消歧重试次数耗尽异常
    """

    pass


def _retry_disambig(
    client: UnifiedModelClient,
    candidates: list[str] | list[dict],
    context_sentences: dict[str, str],
    existing_names: list[str] | None = None,
    rag_hint: str | None = None,
    stage_name: str = "disambiguation",
) -> dict[str, str]:
    """带重试的人名消歧函数。"""
    from src.models.local.parser import DisambiguationParseError

    operation = RetryableOperation(
        max_retries=DISAMBIG_MAX_RETRIES,
        retryable_exceptions=(ConnectionError, TimeoutError, DisambiguationParseError),
        operation_name=stage_name,
    )

    try:
        return operation.execute(
            client.disambiguate_characters,
            candidates,
            context_sentences=context_sentences,
            existing_names=existing_names,
            rag_hint=rag_hint,
        )
    except MaxRetriesExceededError as e:
        raise DisambiguationMaxRetriesExceededError(str(e))


def _retry_disambig_anonymous(
    client: UnifiedModelClient,
    anonymous_names: list[str],
    anonymous_contexts: dict[str, str],
    existing_names: list[str] | None = None,
    existing_contexts: dict[str, str] | None = None,
    stage_name: str = "anonymous disambiguation",
) -> dict[str, str]:
    """带重试的匿名消歧函数。"""
    from src.models.local.parser import DisambiguationParseError

    operation = RetryableOperation(
        max_retries=DISAMBIG_MAX_RETRIES,
        retryable_exceptions=(ConnectionError, TimeoutError, DisambiguationParseError),
        operation_name=stage_name,
    )

    try:
        return operation.execute(
            client.disambiguate_anonymous,
            anonymous_names,
            anonymous_contexts,
            existing_names=existing_names,
            existing_contexts=existing_contexts,
        )
    except MaxRetriesExceededError as e:
        raise DisambiguationMaxRetriesExceededError(str(e))


def build_anonymous_contexts(conn, anonymous_names: list[str]) -> dict[str, str]:
    """
    为匿名占位名构建完整上下文（前一段 + 当前段 + 后一段）

    修改时间: 2026-03-15
    修改者: TraeAI
    任务: postgresql-migration
    修改内容: 使用 SQLAlchemy text() 和命名参数替换 ? 占位符
    """
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
    checkpoint_interval: int = 50,
) -> dict[str, str]:
    """
    执行增量消歧

    修改时间: 2026-03-14
    修改者: TraeAI
    任务: workflows 使用 Repository 模式重构
    修改内容: 添加 run_id 参数，支持 Repository 模式

    修改时间: 2026-03-15
    修改者: TraeAI
    任务: storage-layer-decoupling
    修改内容: 移除向后兼容代码，只使用 Repository 模式

    修改时间: 2026-03-16
    修改者: TraeAI
    任务: fix-disambiguation-three-phase
    修改内容: 
    - 增量消歧只维护内存 alias_map，不写数据库
    - 添加 checkpoint 保存机制
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

    new_aliases = _retry_disambig(
        incremental_disambig_client,
        new_names,
        ctx,
        existing_names=existing_names,
        rag_hint=rag_hint,
        stage_name="incremental disambiguation",
    )

    if new_aliases:
        alias_map.update(new_aliases)
        logger.debug(f"alias_map updated in memory: {len(alias_map)} entries")

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

    修改时间: 2026-03-14
    修改者: TraeAI
    任务: workflows 使用 Repository 模式重构
    修改内容: 添加 run_id 参数，支持 Repository 模式

    修改时间: 2026-03-15
    修改者: TraeAI
    任务: storage-layer-decoupling
    修改内容: 移除向后兼容代码，只使用 Repository 模式

    修改时间: 2026-03-16
    修改者: TraeAI
    任务: fix-disambiguation-three-phase
    修改内容: 最终消歧后调用 apply_alias_corrections 批量修正数据
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

    final_alias_map = _retry_disambig(
        full_disambig_client,
        all_names,
        ctx,
        existing_names=existing_names,
        stage_name="final disambiguation",
    )

    alias_map.update(final_alias_map)
    logger.info("character names updated with alias map")

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
    """
    执行匿名消歧

    修改时间: 2026-03-14
    修改者: TraeAI
    任务: workflows 使用 Repository 模式重构
    修改内容: 添加 run_id 参数，支持 Repository 模式

    修改时间: 2026-03-15
    修改者: TraeAI
    任务: storage-layer-decoupling
    修改内容: 移除向后兼容代码，只使用 Repository 模式
    """
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

    修改时间: 2026-03-15
    修改者: TraeAI
    任务: storage-layer-decoupling
    修改内容: 移除向后兼容代码，run_id 改为必需参数
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
