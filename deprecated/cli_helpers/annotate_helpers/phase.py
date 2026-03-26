"""
创建时间: 2026-03-13
创建者: TraeAI
任务: 项目文件结构整理与拆解 - 标注辅助函数模块

本模块包含阶段管理相关的数据类和函数。
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Tuple

from loguru import logger

from src.config.analysis_logger import AnalysisLogger
from src.models.local.unified_client import UnifiedModelClient

if TYPE_CHECKING:
    import networkx as nx
    from src.rag import RAGRetriever


class AnnotationPhaseResult:
    """
    标注阶段结果数据类

    创建时间: 2026-03-13
    创建者: TraeAI
    任务: refactor-cli-layer-functions
    """

    def __init__(
        self,
        annotation_client: UnifiedModelClient,
        cloud_annotation_client: UnifiedModelClient | None,
        incremental_disambig_client: UnifiedModelClient,
        full_disambig_client: UnifiedModelClient,
        rag_retriever: "RAGRetriever | None",
        character_graph: "nx.Graph | None",
        alias_keywords: list[str],
        global_context_str: str | None,
        alias_map: dict[str, str],
    ) -> None:
        self.annotation_client = annotation_client
        self.cloud_annotation_client = cloud_annotation_client
        self.incremental_disambig_client = incremental_disambig_client
        self.full_disambig_client = full_disambig_client
        self.rag_retriever = rag_retriever
        self.character_graph = character_graph
        self.alias_keywords = alias_keywords
        self.global_context_str = global_context_str
        self.alias_map = alias_map


def _init_annotation_phase(
    conn,
    all_chunks: list,
    novel_id: str,
    novel_title: str | None,
    use_context_enhancement: bool,
    use_rag: bool,
    resume: bool,
    analysis_logger: AnalysisLogger | None,
    annotate_client: UnifiedModelClient | None,
) -> AnnotationPhaseResult:
    """
    初始化标注阶段

    创建时间: 2026-03-13
    创建者: TraeAI
    任务: refactor-cli-layer-functions
    说明: 从 run_annotate 中提取，负责初始化所有标注相关资源和客户端

    Returns:
        AnnotationPhaseResult: 包含所有初始化后的资源
    """
    from .client_init import _init_annotation_clients, _setup_token_usage_callback
    from .context import _init_rag_retriever
    from .sentence import _load_alias_keywords, _extract_and_save_global_context

    (annotation_client, cloud_annotation_client, incremental_disambig_client, full_disambig_client) = (
        _init_annotation_clients(analysis_logger, annotate_client)
    )

    clients = [annotation_client, cloud_annotation_client, incremental_disambig_client, full_disambig_client]
    _setup_token_usage_callback(conn, clients, novel_id, annotation_client)

    alias_keywords = _load_alias_keywords()
    rag_retriever, character_graph, _ = _init_rag_retriever(
        conn, novel_id, use_rag, resume, annotation_client._token_usage_callback
    )

    global_context_str = _extract_and_save_global_context(
        conn, all_chunks, novel_id, novel_title, use_context_enhancement, resume, annotation_client
    )

    return AnnotationPhaseResult(
        annotation_client=annotation_client,
        cloud_annotation_client=cloud_annotation_client,
        incremental_disambig_client=incremental_disambig_client,
        full_disambig_client=full_disambig_client,
        rag_retriever=rag_retriever,
        character_graph=character_graph,
        alias_keywords=alias_keywords,
        global_context_str=global_context_str,
        alias_map={},
    )


def _process_single_chunk(
    conn,
    chunk_id: int,
    chunk_text: str,
    idx: int,
    total_chunks: int,
    phase_result: AnnotationPhaseResult,
    alias_map: dict[str, str],
    use_context_enhancement: bool,
    incremental_interval: int,
) -> dict[str, str]:
    """
    处理单个chunk

    创建时间: 2026-03-13
    创建者: TraeAI
    任务: refactor-cli-layer-functions
    说明: 从 run_annotate 中提取，负责处理单个chunk的标注和增量消歧

    Returns:
        dict[str, str]: 更新后的 alias_map
    """
    from src.cli.annotate import _retry_annotate_chunk
    from .context import _prepare_chunk_context
    from .disambiguation import _run_incremental_disambiguation
    from .storage import _store_annotation_results

    logger.info(f"Annotating chunk {idx + 1}/{total_chunks}")

    ctx = _prepare_chunk_context(
        conn, chunk_id, chunk_text, alias_map, use_context_enhancement, phase_result.rag_retriever
    )

    annotation = _retry_annotate_chunk(
        phase_result.annotation_client,
        chunk_text,
        None,
        alias_map=alias_map if alias_map else None,
        chunk_id=chunk_id,
        global_context=phase_result.global_context_str,
        prev_tail_text=ctx.prev_tail_text,
        active_entities=ctx.active_entities_str,
        rag_evidence=ctx.rag_evidence_str,
        known_aliases=ctx.known_aliases_str,
        next_preview=ctx.next_text,
        cloud_client=phase_result.cloud_annotation_client,
    )
    _store_annotation_results(conn, chunk_id, annotation, chunk_text, use_context_enhancement)
    logger.debug(f"annotated chunk_id={chunk_id}")

    alias_map = _run_incremental_disambiguation(
        conn,
        chunk_id,
        alias_map,
        phase_result.incremental_disambig_client,
        phase_result.rag_retriever,
        phase_result.character_graph,
        phase_result.alias_keywords,
        incremental_interval,
        idx,
    )

    return alias_map


def _process_chunks_phase(
    conn,
    all_chunks: list,
    annotated_ids: set[int],
    phase_result: AnnotationPhaseResult,
    use_context_enhancement: bool,
    incremental_interval: int,
) -> Tuple[int, dict[str, str]]:
    """
    处理所有chunks阶段

    创建时间: 2026-03-13
    创建者: TraeAI
    任务: refactor-cli-layer-functions
    说明: 从 run_annotate 中提取，负责循环处理所有chunks

    Returns:
        Tuple[int, dict[str, str]]: (成功数量, alias_map)
    """
    from src.cli.annotate import (
        ChunkAnnotationMaxRetriesExceededError,
        DisambiguationMaxRetriesExceededError,
    )

    success_count = 0
    alias_map: dict[str, str] = {}
    total_chunks = len(all_chunks)

    for idx, (chunk_id, chunk_text) in enumerate(all_chunks):
        if chunk_id in annotated_ids:
            logger.debug(f"skipping already annotated chunk_id={chunk_id}")
            continue

        try:
            alias_map = _process_single_chunk(
                conn,
                chunk_id,
                chunk_text,
                idx,
                total_chunks,
                phase_result,
                alias_map,
                use_context_enhancement,
                incremental_interval,
            )
            success_count += 1
        except ChunkAnnotationMaxRetriesExceededError as e:
            logger.error(f"chunk annotation max retries exceeded for chunk_id={chunk_id}: {str(e)}")
            raise
        except DisambiguationMaxRetriesExceededError as e:
            logger.error(f"disambiguation max retries exceeded for chunk_id={chunk_id}: {str(e)}")
            raise

    return success_count, alias_map


def _run_disambiguation_phase(
    conn,
    alias_map: dict[str, str],
    phase_result: AnnotationPhaseResult,
    novel_id: str,
    use_rag: bool,
) -> dict[str, str]:
    """
    执行消歧阶段

    创建时间: 2026-03-13
    创建者: TraeAI
    任务: refactor-cli-layer-functions
    说明: 从 run_annotate 中提取，负责执行最终消歧、匿名消歧和知识图谱构建

    Returns:
        dict[str, str]: 最终的 alias_map
    """
    from .disambiguation import (
        _run_anonymous_disambiguation,
        _run_final_disambiguation,
        _build_character_knowledge_graph,
    )

    alias_map = _run_final_disambiguation(
        conn, alias_map, phase_result.full_disambig_client, phase_result.alias_keywords, novel_id
    )

    alias_map = _run_anonymous_disambiguation(
        conn, alias_map, phase_result.full_disambig_client, phase_result.alias_keywords, novel_id
    )

    _build_character_knowledge_graph(conn, novel_id, use_rag)

    return alias_map
