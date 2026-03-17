"""
创建时间: 2026-03-13
创建者: TraeAI
任务: 项目文件结构整理与拆解 - 标注辅助函数模块
修改时间: 2026-03-14
修改者: TraeAI
修改内容: 从 cli.annotate_helpers 迁移到 workflows.annotate_helpers，解决循环依赖

说明: 本模块从 src.cli.annotate_helpers 迁移而来，用于解决 workflows 与 cli 之间的循环依赖问题。
      导入路径已更新: from src.cli.annotate import -> from src.workflows.annotate import

修改时间: 2026-03-14
修改者: TraeAI
任务: workflows 使用 Repository 模式重构
修改内容: 添加 run_id 参数支持，传递给下游函数

本模块包含阶段管理相关的数据类和函数。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Tuple

from loguru import logger

from src.config.analysis_logger import AnalysisLogger
from src.models.local.unified_client import UnifiedModelClient

if TYPE_CHECKING:
    import networkx as nx
    from src.rag import RAGRetriever
    from src.models.local.schema import TwoPhaseAnnotationResult


@dataclass
class AnnotationPhaseConfig:
    """
    标注阶段配置

    创建时间: 2026-03-17
    创建者: TraeAI
    任务: code-quality-refactor - 简化多参数函数
    说明: 封装_init_annotation_phase的多参数
    """

    conn: any
    all_chunks: list
    novel_id: str
    novel_title: str | None = None
    use_context_enhancement: bool = False
    use_rag: bool = False
    resume: bool = False
    analysis_logger: AnalysisLogger | None = None
    annotate_client: UnifiedModelClient | None = None
    incremental_disambig_client: UnifiedModelClient | None = None
    full_disambig_client: UnifiedModelClient | None = None
    run_id: str = ""


class ChunkAnnotationMaxRetriesExceededError(Exception):
    """
    Chunk标注重试次数耗尽异常

    修改时间: 2026-03-14
    修改者: TraeAI
    任务: 简化重试逻辑
    修改内容: 移除外层重试，只保留内层重试机制
    """

    pass


def _annotate_chunk(
    client: UnifiedModelClient,
    text: str,
    prev_summary: str | None = None,
    alias_map: dict[str, str] | None = None,
    chunk_id: int | None = None,
    global_context: str | None = None,
    prev_tail_text: str | None = None,
    active_entities: str | None = None,
    rag_evidence: str | None = None,
    known_aliases: str | None = None,
    next_preview: str | None = None,
    cloud_client: UnifiedModelClient | None = None,
) -> "TwoPhaseAnnotationResult":
    """
    Chunk 标注函数

    创建时间: 2026-03-14
    创建者: TraeAI
    任务: 简化重试逻辑
    说明: 直接调用 annotate_chunk，内层已有完整的 3次本地 + 1次云端 重试机制

    重试策略:
    - 内层: 本地模型最多3次（任何错误类型）
    - 内层: 本地失败后云端1次
    - 云端失败直接终止整个任务

    修改时间: 2026-03-17
    修改者: TraeAI
    任务: 修复foreshadowing数据丢失问题
    修改内容: 返回TwoPhaseAnnotationResult，包含foreshadowing数据
    """
    try:
        return client.annotate_chunk(
            text,
            prev_summary,
            alias_map=alias_map,
            chunk_id=chunk_id,
            global_context=global_context,
            prev_tail_text=prev_tail_text,
            active_entities=active_entities,
            rag_evidence=rag_evidence,
            known_aliases=known_aliases,
            next_preview=next_preview,
            cloud_client=cloud_client,
        )
    except Exception as e:
        logger.error(f"chunk annotation failed for chunk_id={chunk_id}: {str(e)}")
        raise ChunkAnnotationMaxRetriesExceededError(str(e))


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


def _init_annotation_phase_with_config(
    config: AnnotationPhaseConfig,
) -> AnnotationPhaseResult:
    """
    初始化标注阶段（使用配置对象）

    创建时间: 2026-03-17
    创建者: TraeAI
    任务: code-quality-refactor - 简化多参数函数
    说明: 使用 AnnotationPhaseConfig 替代多个参数
    """
    from .client_init import _init_annotation_clients, _setup_token_usage_callback
    from .context import _init_rag_retriever
    from .sentence import _load_alias_keywords, _extract_and_save_global_context

    if config.run_id is None:
        raise ValueError("run_id is required for annotation phase")

    (annotation_client, cloud_annotation_client, incremental_client, full_client) = (
        _init_annotation_clients(
            config.analysis_logger,
            config.annotate_client,
            config.incremental_disambig_client,
            config.full_disambig_client,
        )
    )

    clients = [
        annotation_client,
        cloud_annotation_client,
        config.incremental_disambig_client,
        config.full_disambig_client,
    ]
    _setup_token_usage_callback(
        config.conn, clients, config.novel_id, annotation_client, run_id=config.run_id
    )

    alias_keywords = _load_alias_keywords()
    rag_retriever, character_graph, _ = _init_rag_retriever(
        config.conn,
        config.novel_id,
        config.use_rag,
        config.resume,
        annotation_client._token_usage_callback,
        run_id=config.run_id,
    )

    global_context_str = _extract_and_save_global_context(
        config.conn,
        config.all_chunks,
        config.novel_id,
        config.novel_title,
        config.use_context_enhancement,
        config.resume,
        annotation_client,
        run_id=config.run_id,
    )

    return AnnotationPhaseResult(
        annotation_client=annotation_client,
        cloud_annotation_client=cloud_annotation_client,
        incremental_disambig_client=incremental_client,
        full_disambig_client=full_client,
        rag_retriever=rag_retriever,
        character_graph=character_graph,
        alias_keywords=alias_keywords,
        global_context_str=global_context_str,
        alias_map={},
    )


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
    incremental_disambig_client: UnifiedModelClient | None = None,
    full_disambig_client: UnifiedModelClient | None = None,
    run_id: str = "",
) -> AnnotationPhaseResult:
    """
    初始化标注阶段

    创建时间: 2026-03-13
    创建者: TraeAI
    任务: refactor-cli-layer-functions
    说明: 从 run_annotate 中提取，负责初始化所有标注相关资源和客户端

    修改时间: 2026-03-14
    修改者: TraeAI
    任务: workflows 使用 Repository 模式重构
    修改内容: 添加 run_id 参数

    修改时间: 2026-03-15
    修改者: TraeAI
    任务: storage-layer-decoupling
    修改内容: 添加 incremental_disambig_client 和 full_disambig_client 参数，支持测试注入 mock

    修改时间: 2026-03-17
    修改者: TraeAI
    任务: code-quality-refactor - 简化多参数函数
    修改内容: 改为调用 _init_annotation_phase_with_config，保持向后兼容

    Returns:
        AnnotationPhaseResult: 包含所有初始化后的资源
    """
    config = AnnotationPhaseConfig(
        conn=conn,
        all_chunks=all_chunks,
        novel_id=novel_id,
        novel_title=novel_title,
        use_context_enhancement=use_context_enhancement,
        use_rag=use_rag,
        resume=resume,
        analysis_logger=analysis_logger,
        annotate_client=annotate_client,
        incremental_disambig_client=incremental_disambig_client,
        full_disambig_client=full_disambig_client,
        run_id=run_id,
    )
    return _init_annotation_phase_with_config(config)


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
    run_id: str = "",
) -> dict[str, str]:
    """
    处理单个chunk

    创建时间: 2026-03-13
    创建者: TraeAI
    任务: refactor-cli-layer-functions
    说明: 从 run_annotate 中提取，负责处理单个chunk的标注和增量消歧

    修改时间: 2026-03-14
    修改者: TraeAI
    任务: workflows 使用 Repository 模式重构
    修改内容: 添加 run_id 参数

    Returns:
        dict[str, str]: 更新后的 alias_map
    """
    from .context import _prepare_chunk_context
    from .disambiguation import _run_incremental_disambiguation
    from .storage import _store_annotation_results

    logger.info(f"Annotating chunk {idx + 1}/{total_chunks}")

    ctx = _prepare_chunk_context(
        conn, chunk_id, chunk_text, alias_map, use_context_enhancement, phase_result.rag_retriever, run_id=run_id
    )

    annotation_result = _annotate_chunk(
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
    _store_annotation_results(conn, chunk_id, annotation_result.annotation, chunk_text, use_context_enhancement, run_id=run_id, foreshadowing=annotation_result.foreshadowing)
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
        run_id=run_id,
    )

    return alias_map


def _process_chunks_phase(
    conn,
    all_chunks: list,
    annotated_ids: set[int],
    phase_result: AnnotationPhaseResult,
    use_context_enhancement: bool,
    incremental_interval: int,
    run_id: str = "",
) -> Tuple[int, dict[str, str]]:
    """
    处理所有chunks阶段

    创建时间: 2026-03-13
    创建者: TraeAI
    任务: refactor-cli-layer-functions
    说明: 从 run_annotate 中提取，负责循环处理所有chunks

    修改时间: 2026-03-14
    修改者: TraeAI
    任务: workflows 使用 Repository 模式重构
    修改内容: 添加 run_id 参数

    Returns:
        Tuple[int, dict[str, str]]: (成功数量, alias_map)
    """
    from .disambiguation import DisambiguationMaxRetriesExceededError

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
                run_id=run_id,
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
    run_id: str = "",
) -> dict[str, str]:
    """
    执行消歧阶段

    创建时间: 2026-03-13
    创建者: TraeAI
    任务: refactor-cli-layer-functions
    说明: 从 run_annotate 中提取，负责执行最终消歧、匿名消歧和知识图谱构建

    修改时间: 2026-03-14
    修改者: TraeAI
    任务: workflows 使用 Repository 模式重构
    修改内容: 添加 run_id 参数

    Returns:
        dict[str, str]: 最终的 alias_map
    """
    from .disambiguation import (
        _run_anonymous_disambiguation,
        _run_final_disambiguation,
        _build_character_knowledge_graph,
    )

    alias_map = _run_final_disambiguation(
        conn, alias_map, phase_result.full_disambig_client, phase_result.alias_keywords, novel_id, run_id=run_id
    )

    alias_map = _run_anonymous_disambiguation(
        conn, alias_map, phase_result.full_disambig_client, phase_result.alias_keywords, novel_id, run_id=run_id
    )

    _build_character_knowledge_graph(conn, novel_id, use_rag, run_id=run_id)

    return alias_map
