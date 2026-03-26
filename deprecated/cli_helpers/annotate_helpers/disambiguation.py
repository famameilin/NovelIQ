"""
创建时间: 2026-03-13
创建者: TraeAI
任务: 项目文件结构整理与拆解 - 标注辅助函数模块

本模块包含消歧相关的函数。
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from loguru import logger

from src.config import settings
from src.models.local.unified_client import UnifiedModelClient

if TYPE_CHECKING:
    import networkx as nx
    from src.rag import RAGRetriever


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
) -> dict[str, str]:
    """
    执行增量消歧

    创建时间: 2026-03-13
    创建者: TraeAI
    任务: refactor-analysis-layer-functions
    说明: 从 run_annotate 中提取，负责执行增量人名消歧
    """
    from src.cli.annotate import (
        _retry_disambig,
        build_context_sentences,
        extract_new_names_from_db,
    )
    from src.storage.operations import update_character_names
    from src.knowledge.graph import get_active_nodes_in_range

    if (current_idx + 1) % incremental_interval != 0:
        return alias_map

    new_names = extract_new_names_from_db(conn, alias_map)
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
            rag_hint = f"<Known_Alias_Candidates>{'、'.join(candidate_names)}</Known_Alias_Candidates>"
        if settings.rag.level2_enabled and character_graph:
            candidates = get_active_nodes_in_range(character_graph, max(0, chunk_id - 10), chunk_id)
            if candidates:
                rag_hint = f"<Alias_Candidates>{'、'.join(candidates[:5])}</Alias_Candidates>"

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
        update_character_names(conn, new_aliases, novel_id="")
        logger.debug(f"alias_map updated and saved: {len(alias_map)} entries")

    return alias_map


def _run_final_disambiguation(
    conn,
    alias_map: dict[str, str],
    full_disambig_client: UnifiedModelClient,
    alias_keywords: list[str],
    novel_id: str,
) -> dict[str, str]:
    """
    执行最终消歧

    创建时间: 2026-03-13
    创建者: TraeAI
    任务: refactor-analysis-layer-functions
    说明: 从 run_annotate 中提取，负责执行最终人名消歧
    """
    from src.cli.annotate import _retry_disambig, build_context_sentences
    from src.storage.operations import fetch_all_character_names, update_character_names

    logger.info("collecting all character names for final disambiguation")
    all_names = fetch_all_character_names(conn)

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
        update_character_names(conn, alias_map, novel_id=novel_id)
        logger.info(f"applied alias_map with {len(alias_map)} entries to database")

    return alias_map


def _run_anonymous_disambiguation(
    conn,
    alias_map: dict[str, str],
    full_disambig_client: UnifiedModelClient,
    alias_keywords: list[str],
    novel_id: str,
) -> dict[str, str]:
    """
    执行匿名消歧

    创建时间: 2026-03-13
    创建者: TraeAI
    任务: refactor-analysis-layer-functions
    说明: 从 run_annotate 中提取，负责执行匿名占位名消歧
    """
    from src.cli.annotate import _retry_disambig_anonymous, build_anonymous_contexts, build_context_sentences
    from src.storage.operations import update_character_names

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
        update_character_names(conn, anonymous_alias_map, novel_id=novel_id)
        logger.info(f"anonymous disambiguation completed: {len(anonymous_alias_map)} names processed")

    return alias_map


def _build_character_knowledge_graph(
    conn,
    novel_id: str,
    use_rag: bool,
) -> bool:
    """
    构建角色知识图谱

    创建时间: 2026-03-13
    创建者: TraeAI
    任务: refactor-analysis-layer-functions
    说明: 从 run_annotate 中提取，负责构建并保存角色知识图谱

    Returns:
        bool: 是否成功构建图谱
    """
    if not use_rag or not settings.rag.enabled:
        return False

    from src.knowledge import build_character_graph, save_graph_to_db

    logger.info("building character knowledge graph")
    character_graph = build_character_graph(conn, novel_id)
    save_graph_to_db(conn, character_graph, "character_graph")
    logger.info(f"saved graph: {character_graph.number_of_nodes()} nodes, {character_graph.number_of_edges()} edges")

    return True
