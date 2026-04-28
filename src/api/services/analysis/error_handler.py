"""
分析错误处理服务

说明: 负责处理分析过程中的成功、失败和取消事件
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

from loguru import logger
from sqlalchemy.orm import Session

from src.storage.repositories import RunRepository

if TYPE_CHECKING:
    from src.api.models.events import AnalysisEventBus
    from src.api.services.novel_service import NovelService
    from src.api.services.task_manager import TaskManager
    from src.config.analysis_logger import AnalysisLogger


class AnalysisErrorHandler:
    """分析错误处理服务"""

    def __init__(
        self,
        novel_service: NovelService,
        task_manager: TaskManager,
    ):
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
        bus: AnalysisEventBus | None = None,
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

        # 任务完成后失效聚合指标缓存，确保新分析结果立即生效
        # 这里必须命中 api.dependencies 中维护的同一 MetricsService 单例，
        # 否则只会失效一个临时新实例上的空缓存，路由真实读取的缓存仍然保留旧值
        try:
            from src.api.dependencies import get_metrics_service

            metrics_service = get_metrics_service()
            metrics_service.invalidate_cache(run_id)
        except Exception as e:
            logger.warning(f"Failed to invalidate metrics cache for {run_id}: {e}")

        if bus:
            await bus.emit_task_complete()

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
        bus: AnalysisEventBus | None = None,
        log_prefix: str = "Analysis",
    ) -> None:
        """
        处理分析失败
        """
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

        # 这里必须先清掉失败现场遗留的未提交事务，
        # 再写 run 状态；否则后续 commit 会把半成品业务数据一并刷进数据库
        session.rollback()
        run_repo = RunRepository(session)
        run_repo.update_run_status(run_id, "failed")
        session.commit()

        if bus:
            await bus.emit_task_error(str(error))

    async def handle_cancel(
        self,
        task_id: str,
        novel_id: str,
        session: Session,
        run_id: str,
        analysis_logger: AnalysisLogger | None,
        bus: AnalysisEventBus | None = None,
    ) -> None:
        """
        处理分析取消
        """
        self.task_manager.cancel_completed_task(task_id, error="用户取消")
        self.novel_service.update_task_status(task_id, "cancelled")

        # 取消路径与失败路径一样，共享同一个 session；
        # 若不先 rollback，commit cancel 状态时仍会把之前残留的脏写入一起提交
        session.rollback()
        run_repo = RunRepository(session)
        run_repo.update_run_task_fields(
            run_id,
            status="cancelled",
            cancel_requested=False,
            completed_at=datetime.now(UTC),
        )
        session.commit()

        if bus:
            await bus.emit_task_cancelled()

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
