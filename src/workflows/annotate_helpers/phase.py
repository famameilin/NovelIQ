"""
标注辅助函数模块 - 阶段管理

创建时间: 2026-03-13
创建者: TraeAI
任务: 项目文件结构整理与拆解

修改历史:
- 2026-03-14: 从 cli.annotate_helpers 迁移，解决循环依赖
- 2026-03-14: 添加 run_id 参数支持 (workflows-repository-refactor)
- 2026-03-17: 使用 AnnotationPhaseConfig 简化多参数函数

说明: 本模块包含阶段管理相关的数据类和函数。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Tuple

from loguru import logger

from src.config.analysis_logger import AnalysisLogger
from src.models.local.unified_client import UnifiedModelClient

if TYPE_CHECKING:
    import networkx as nx
    from src.rag import RAGRetriever
    from src.models.local.annotation import MultiPhaseAnnotationResult


@dataclass
class AnnotationPhaseConfig:
    """标注阶段配置"""

    conn: Any
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
    """Chunk标注重试次数耗尽异常"""
    pass


def _annotate_chunk(
    client: UnifiedModelClient,
    text: str,
    prev_summary: str | None = None,
    alias_map: dict[str, str] | None = None,
    chunk_id: int | None = None,
    global_context: str | None = None,
    prev_chunk_text: str | None = None,
    active_entities: str | None = None,
    rag_evidence: str | None = None,
    known_aliases: str | None = None,
    next_chunk_text: str | None = None,
    cloud_client: UnifiedModelClient | None = None,
    run_id: str | None = None,
    character_appearances: list[dict] | None = None,
) -> "MultiPhaseAnnotationResult":
    """
    Chunk 标注函数

    修改时间: 2026-03-19
    修改者: TraeAI
    任务: 统一字段命名，添加 run_id 支持

    修改时间: 2026-03-21
    修改者: TraeAI
    任务: fix-validate-names-from-character-appearances
    修改内容: 增加 character_appearances 参数支持

    重试策略:
    - 内层: 本地模型最多3次（任何错误类型）
    - 内层: 本地失败后云端1次
    - 云端失败直接终止整个任务
    """
    try:
        return client.annotate_chunk(
            text,
            prev_summary,
            alias_map=alias_map,
            chunk_id=chunk_id,
            global_context=global_context,
            prev_chunk_text=prev_chunk_text,
            active_entities=active_entities,
            rag_evidence=rag_evidence,
            known_aliases=known_aliases,
            next_chunk_text=next_chunk_text,
            cloud_client=cloud_client,
            run_id=run_id,
            character_appearances=character_appearances,
        )
    except Exception as e:
        logger.error(f"chunk annotation failed for chunk_id={chunk_id}: {str(e)}")
        raise ChunkAnnotationMaxRetriesExceededError(str(e))


class AnnotationPhaseResult:
    """标注阶段结果数据类"""

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
    """初始化标注阶段（使用配置对象）"""
    from .client_init import _init_annotation_clients, _setup_token_usage_callback
    from .context import _init_rag_retriever
    from .sentence import _load_alias_keywords, _extract_and_save_global_context

    if not config.run_id:
        raise ValueError("run_id is required for annotation phase")

    (annotation_client, cloud_annotation_client, incremental_client, full_client) = (
        _init_annotation_clients(
            config.analysis_logger,
            config.annotate_client,
            config.incremental_disambig_client,
            config.full_disambig_client,
        )
    )

    # 设置 session 用于保存模型交互记录
    if config.conn is not None:
        annotation_client._annotation_client._session = config.conn
        if cloud_annotation_client:
            cloud_annotation_client._annotation_client._session = config.conn
        incremental_client._annotation_client._session = config.conn
        full_client._annotation_client._session = config.conn

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
    初始化标注阶段（向后兼容）

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
    novel_id: str = "",
) -> dict[str, str]:
    """处理单个chunk

    修改时间: 2026-03-18
    修改者: TraeAI
    任务: 修复 _run_incremental_disambiguation 缺少 novel_id 参数的错误
    修改内容: 添加 novel_id 参数并传递给 _run_incremental_disambiguation

    修改时间: 2026-03-20
    修改者: TraeAI
    任务: analyze-dialogue-length-zero
    修改内容: 传递 client 参数到 _store_annotation_results 以支持 LLM 对话归属判断

    修改时间: 2026-03-21
    修改者: TraeAI
    任务: fix-phase3-not-called
    修改内容: 在 _process_single_chunk 中调用 phase3 计算对话长度，而不是在 storage 中
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
        prev_chunk_text=ctx.prev_chunk_text,
        active_entities=ctx.active_entities_str,
        rag_evidence=ctx.rag_evidence_str,
        known_aliases=ctx.known_aliases_str,
        next_chunk_text=ctx.next_chunk_text,
        cloud_client=phase_result.cloud_annotation_client,
        run_id=run_id,
        character_appearances=ctx.character_appearances,
    )
    
    _store_annotation_results(
        conn,
        chunk_id,
        annotation_result.annotation,
        chunk_text,
        use_context_enhancement,
        run_id=run_id,
        foreshadowing=annotation_result.foreshadowing,
        alias_map=alias_map if alias_map else None,
        dialogue_lengths=annotation_result.dialogue_lengths,
        dialogue_speakers=annotation_result.dialogue_speakers,
    )
    logger.debug(f"annotated chunk_id={chunk_id}")

    alias_map = _run_incremental_disambiguation(
        conn,
        alias_map,
        phase_result.incremental_disambig_client,
        phase_result.alias_keywords,
        novel_id,
        run_id,
        chunk_id,
        idx,
        incremental_interval,
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
    novel_id: str = "",
    resume: bool = False,
) -> Tuple[int, dict[str, str]]:
    """处理所有chunks阶段

    修改时间: 2026-03-19
    修改者: TraeAI
    任务: fix-entity-relations-not-saved
    修改内容: 添加 resume 参数，支持从 checkpoint 恢复 alias_map
    """
    from .disambiguation import DisambiguationMaxRetriesExceededError, _load_disambig_checkpoint

    success_count = 0

    # 如果是恢复模式，尝试从 checkpoint 加载 alias_map
    alias_map: dict[str, str] = {}
    if resume and run_id:
        loaded_alias_map, _ = _load_disambig_checkpoint(conn, run_id)
        if loaded_alias_map:
            alias_map = loaded_alias_map
            logger.info(f"resumed from checkpoint: {len(alias_map)} alias entries")

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
                novel_id=novel_id,
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
    """执行消歧阶段"""
    from .disambiguation import _run_final_disambiguation

    alias_map = _run_final_disambiguation(
        conn, alias_map, phase_result.full_disambig_client, phase_result.alias_keywords, novel_id, run_id=run_id
    )

    return alias_map
