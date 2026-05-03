"""
核心标注工作流

Extracted from CLI to workflows to reduce coupling


"""

from __future__ import annotations

import time
from collections.abc import Awaitable, Callable

from loguru import logger
from sqlalchemy.orm import Session

from src.api.models.events import StreamEvent
from src.config import settings
from src.config.analysis_logger import AnalysisLogger
from src.models.interfaces import AnnotationLike, DisambiguationLike
from src.storage.repositories import AnnotationRepository, ChunkRepository


async def run_annotate(
    run_id: str,
    session: Session,
    resume: bool = False,
    analysis_logger: AnalysisLogger | None = None,
    novel_id: str = "default",
    novel_title: str | None = None,
    use_context_enhancement: bool = True,
    use_rag: bool = True,
    annotate_client: AnnotationLike | None = None,
    incremental_disambig_client: DisambiguationLike | None = None,
    full_disambig_client: DisambiguationLike | None = None,
    is_cancelled: Callable[[], bool] | None = None,
    emitter: Callable[[StreamEvent], Awaitable[None]] | None = None,
) -> tuple[int, int, int]:
    """
    执行小说标注流程









    Args:
        run_id: 运行ID
        session: 数据库连接
        resume: 是否恢复模式
        analysis_logger: 分析日志器
        novel_id: 小说ID
        novel_title: 小说标题
        use_context_enhancement: 是否使用上下文增强
        use_rag: 是否使用 RAG
        annotate_client: 标注客户端
        incremental_disambig_client: 增量消歧客户端
        full_disambig_client: 完整消歧客户端

    Returns:
        Tuple[int, int, int]: (成功数量, 0, 总块数)
    """
    from src.workflows.annotate_helpers.graph_projection import project_graph_tables
    from src.workflows.annotate_helpers.phase import (
        _init_annotation_phase,
        _process_chunks_phase,
        _run_disambiguation_phase,
    )

    start_time = time.time()

    chunk_repo = ChunkRepository(session)
    all_chunks = chunk_repo.fetch_chunk_texts(run_id)

    total_chunks = len(all_chunks)

    if total_chunks == 0:
        logger.warning("no chunks found in db")
        return 0, 0, 0

    annotated_ids: set[int] = set()
    if resume:
        ann_repo = AnnotationRepository(session)
        annotated_ids = ann_repo.fetch_annotated_chunk_ids(run_id)
        logger.info(f"resume mode: {len(annotated_ids)} chunks already annotated")

    phase_result = await _init_annotation_phase(
        session,
        all_chunks,
        novel_id,
        novel_title,
        use_context_enhancement,
        use_rag,
        resume,
        analysis_logger,
        annotate_client,
        incremental_disambig_client=incremental_disambig_client,
        full_disambig_client=full_disambig_client,
        run_id=run_id,
        emitter=emitter,
    )

    incremental_interval = settings.analysis.incremental_disambig_interval
    success_count, state = await _process_chunks_phase(
        session,
        all_chunks,
        annotated_ids,
        phase_result,
        use_context_enhancement,
        incremental_interval,
        run_id=run_id,
        novel_id=novel_id,
        resume=resume,
        emitter=emitter,
        is_cancelled=is_cancelled,
    )

    state = await _run_disambiguation_phase(session, state, phase_result, novel_id, use_rag, run_id=run_id)

    # 最终消歧可能改变别名归一化规则，强制重建 graph_* 以避免旧投影残留
    if all_chunks:
        final_chunk_id = all_chunks[-1][0]
        project_graph_tables(
            run_id,
            from_chunk=0,
            to_chunk=final_chunk_id,
            session=session,
            rebuild=True,
        )

    elapsed = time.time() - start_time
    logger.info(f"annotate completed success={success_count} time={elapsed:.2f}s")
    logger.info("\n=== Annotate Statistics ===")
    logger.info(f"Total chunks: {total_chunks}")
    logger.info(f"Annotated: {success_count}")
    logger.info(f"Processing time: {elapsed:.2f}s")
    return success_count, 0, total_chunks
