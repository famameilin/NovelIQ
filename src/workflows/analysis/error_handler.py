"""
分析错误处理服务

负责处理分析过程中的成功、失败和取消事件
"""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING

from loguru import logger

from src.storage import Storage

if TYPE_CHECKING:
    from src.config.analysis_logger import AnalysisLogger
    from src.work.task_manager import TaskManager
    from src.workflows.progress import AnalysisEventBus
    from src.workflows.tasks import TaskService


class AnalysisErrorHandler:
    """分析错误处理服务"""

    def __init__(self, task_service: TaskService, task_manager: TaskManager):
        self.task_service = task_service
        self.task_manager = task_manager

    async def handle_success(
        self,
        task_id: str,
        novel_id: str,
        elapsed: float,
        analysis_logger: AnalysisLogger | None,
        session: Storage,
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
        run_repo = session.runs
        try:
            run_repo.update_run_task_fields(run_id, status="completed")
        except Exception as exc:
            logger.error(f"Task {task_id} 终态 DB 写回失败: {exc}")
            raise
        self.task_manager.notify_run_completed(run_id)
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
        session: Storage,
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
        logger.error(f"{log_prefix} failed: {task_id} - {error}")
        run_repo = session.runs
        try:
            run_repo.update_run_task_fields(run_id, status="failed")
        except Exception as exc:
            logger.error(f"Task {task_id} 终态 DB 写回失败: {exc}")
            raise
        if bus:
            await bus.emit_task_error(str(error))

    async def handle_cancel(
        self,
        task_id: str,
        novel_id: str,
        session: Storage,
        run_id: str,
        analysis_logger: AnalysisLogger | None,
        bus: AnalysisEventBus | None = None,
    ) -> None:
        """
        处理分析取消
        """
        run_repo = session.runs
        try:
            run_repo.update_run_task_fields(run_id, status="cancelled")
        except Exception as exc:
            logger.error(f"Task {task_id} 终态 DB 写回失败: {exc}")
            raise
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


class TerminalStateFallbackMixin:
    """终态兜底混入（宿主需提供 task_service/task_manager/session_factory）"""

    task_service: TaskService
    task_manager: TaskManager
    session_factory: Callable[[], Storage]

    def _check_all_stages_completed(self, skip_stages: dict[str, bool]) -> bool:
        return (
            skip_stages["skip_preprocess"]
            and skip_stages["skip_annotate"]
            and skip_stages["skip_linguistic"]
            and skip_stages["skip_aggregate"]
            and skip_stages["skip_topic_model"]
            and skip_stages["skip_diagnose"]
        )

    def _handle_already_completed(self, task_id: str, novel_id: str, analysis_logger: AnalysisLogger | None) -> None:
        """处理已完成的分析任务，确保 DB 状态一致"""
        logger.info(f"Task {task_id} already completed, no action needed")
        from src.storage.id_mapping import task_id_to_run_id

        sf = self.session_factory
        db_session = sf()
        sql_session = db_session
        run_repo = sql_session.runs
        run_id = task_id_to_run_id(task_id, sql_session)
        run_repo.update_run_task_fields(run_id, status="completed")
        if analysis_logger:
            analysis_logger.write_summary(
                {
                    "novel_id": novel_id,
                    "task_id": task_id,
                    "total_time": 0,
                    "status": "already_completed",
                    "message": "任务已完成，无需重新分析",
                }
            )

    def _write_failure_to_db(self, task_id: str, error_message: str) -> None:
        """
        将任务失败状态写入 DB（兜底路径专用）

        说明: 当 session 或 run_id 为 None 时（环境初始化失败），无法走常规 error_handler 路径，
              此方法通过 task_id 直接查询 run_id 并写入 DB 终态，确保 DB 状态一致性
              这是极端异常路径的兜底保护
        """
        from src.storage.id_mapping import TaskIDNotFoundError, task_id_to_run_id

        try:
            sf = self.session_factory
            db_session = sf()
            sql_session = db_session
            run_repo = sql_session.runs
            run_id = task_id_to_run_id(task_id, sql_session)
            run_repo.update_run_task_fields(run_id, status="failed")
        except TaskIDNotFoundError:
            logger.warning(f"Task {task_id} not found in id_mapping during failure DB write, skipping")
        except Exception as e:
            logger.error(f"Failed to write failure status to DB for task {task_id}: {e}")
