"""
分析阶段执行服务

说明: 负责执行分析的各个阶段（预处理、标注、聚合、主题建模、诊断）
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from pathlib import Path

from sqlalchemy.orm import Session

from src.api.models.events import StreamEvent
from src.config import settings
from src.config.analysis_logger import AnalysisLogger


class StageExecutor:
    """分析阶段执行服务"""

    async def run_preprocess(
        self,
        source_path: Path,
        run_id: str,
        session: Session,
        emitter: Callable[[StreamEvent], Awaitable[None]] | None = None,
    ) -> None:
        """执行预处理阶段"""
        from src.workflows import run_preprocess

        await run_preprocess(
            source_path=source_path,
            run_id=run_id,
            session=session,
            emitter=emitter,
        )

    async def run_annotate(
        self,
        run_id: str,
        session: Session,
        novel_id: str,
        analysis_logger: AnalysisLogger | None,
        novel_title: str | None = None,
        emitter: Callable[[StreamEvent], Awaitable[None]] | None = None,
        is_cancelled: Callable[[], bool] | None = None,
    ) -> None:
        """执行标注阶段（LangGraph 标注 Agent）"""
        from src.workflows import run_annotate

        await run_annotate(
            run_id=run_id,
            session=session,
            resume=True,
            analysis_logger=analysis_logger,
            novel_id=novel_id,
            novel_title=novel_title,
            emitter=emitter,
            is_cancelled=is_cancelled,
        )

    async def run_aggregate(
        self,
        run_id: str,
        session: Session,
        emitter: Callable[[StreamEvent], Awaitable[None]] | None = None,
    ) -> None:
        """执行聚合阶段"""
        from src.workflows import run_aggregate

        await run_aggregate(run_id=run_id, session=session, emitter=emitter)

    async def run_topic_model(
        self,
        run_id: str,
        session: Session,
        num_topics: int | None = None,
        emitter: Callable[[StreamEvent], Awaitable[None]] | None = None,
    ) -> None:
        """执行主题建模阶段"""
        from src.workflows import run_topic_model

        if num_topics is None:
            num_topics = settings.topic_model.num_topics
        await run_topic_model(run_id=run_id, session=session, num_topics=num_topics, emitter=emitter)

    async def run_diagnose(
        self,
        run_id: str,
        session: Session,
        analysis_logger: AnalysisLogger | None,
        emitter: Callable[[StreamEvent], Awaitable[None]] | None = None,
    ) -> None:
        """
        执行诊断阶段（LangGraph 诊断 Agent）
        """
        from src.workflows import run_diagnose

        await run_diagnose(
            run_id=run_id,
            session=session,
            analysis_logger=analysis_logger,
            emitter=emitter,
        )
