"""
分析错误处理服务

创建时间: 2026-04-07
创建者: GLM-5
任务: AnalysisService 重构 - 提取错误处理职责
说明: 负责处理分析过程中的成功、失败和取消事件
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from loguru import logger
from sqlalchemy.orm import Session

from src.api.models.stream import StreamMessageType
from src.storage.repositories import RunRepository

if TYPE_CHECKING:
    from src.api.services.broadcast.progress_broadcaster import ProgressBroadcaster
    from src.api.services.novel_service import NovelService
    from src.api.services.task_manager import TaskManager
    from src.config.analysis_logger import AnalysisLogger


class AnalysisErrorHandler:
    """分析错误处理服务"""

    def __init__(
        self,
        broadcaster: ProgressBroadcaster,
        novel_service: NovelService,
        task_manager: TaskManager,
    ):
        self.broadcaster = broadcaster
        self.novel_service = novel_service
        self.task_manager = task_manager

    async def handle_success(
        self,
        task_id: str,
        novel_id: str,
        elapsed: float,
        analysis_logger: AnalysisLogger | None,
        session: Session,
        run_id: str,
        log_prefix: str = "Analysis",
    ) -> None:
        """处理分析成功"""
        if analysis_logger:
            analysis_logger.write_summary(
                {
                    "novel_id": novel_id,
                    "task_id": task_id,
                    "run_id": run_id,
                    "total_time": elapsed,
                    "status": "completed",
                }
            )
        self.novel_service.update_task_status(task_id, "completed")
        self.task_manager.complete_task(task_id, success=True)

        run_repo = RunRepository(session)
        run_repo.update_run_status(run_id, "completed")
        session.commit()

        await self.broadcaster.broadcast_progress(
            task_id, StreamMessageType.task_complete, percent=100.0, message="分析完成"
        )

        logger.info(f"{log_prefix} completed: {task_id}")

    async def handle_failure(
        self,
        task_id: str,
        novel_id: str,
        elapsed: float,
        error: Exception,
        analysis_logger: AnalysisLogger | None,
        session: Session,
        run_id: str,
        log_prefix: str = "Analysis",
    ) -> None:
        """处理分析失败"""
        if analysis_logger:
            analysis_logger.write_summary(
                {
                    "novel_id": novel_id,
                    "task_id": task_id,
                    "run_id": run_id,
                    "total_time": elapsed,
                    "status": "failed",
                    "error": str(error),
                }
            )
        self.novel_service.update_task_status(task_id, "failed")
        logger.error(f"{log_prefix} failed: {task_id} - {error}")
        self.task_manager.complete_task(task_id, success=False, error=str(error))

        run_repo = RunRepository(session)
        run_repo.update_run_status(run_id, "failed")
        session.commit()

        await self.broadcaster.broadcast_progress(
            task_id, StreamMessageType.task_error, message=str(error)
        )

    async def handle_cancel(
        self,
        task_id: str,
        novel_id: str,
        session: Session,
        run_id: str,
        analysis_logger: AnalysisLogger | None,
    ) -> None:
        """处理分析取消"""
        self.task_manager.cancel_completed_task(task_id, error="用户取消")
        self.novel_service.update_task_status(task_id, "cancelled")

        run_repo = RunRepository(session)
        run_repo.update_run_status(run_id, "cancelled")
        session.commit()

        await self.broadcaster.broadcast_progress(
            task_id, StreamMessageType.task_cancelled, message="任务已取消"
        )

        if analysis_logger:
            analysis_logger.write_summary(
                {
                    "novel_id": novel_id,
                    "task_id": task_id,
                    "run_id": run_id,
                    "status": "cancelled",
                    "message": "用户取消",
                }
            )

        logger.info(f"Task {task_id} cancelled by user")
