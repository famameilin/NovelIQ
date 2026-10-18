"""任务取消检查与 DB 领取状态机

取消检查（_is_cancelled）与 DB 领取状态机（_prepare_task_execution_claim/
_claim_pending_run/_is_recent_resume_reset）以混入形式提供给 AnalysisService。
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any

from loguru import logger

from src.workflows.exceptions import AnalysisError

if TYPE_CHECKING:
    from src.storage.session import SessionFactory
    from src.work.task_manager import TaskManager

# 任务 claim 时判定"刚被 resume 重置"的竞态窗口：resume 重置后旧 worker 的延迟取消
# 写回可能把状态覆盖回 cancelled，只有在该窗口内的重置才允许 claim 侧重新激活
_RESUME_RESET_WINDOW_SECONDS = 30


class CancellationStateCheckError(RuntimeError):
    """取消状态检查失败异常"""


class TaskClaimMixin:
    """取消检查与 DB 领取状态机混入（宿主需提供 session_factory/task_manager）"""

    session_factory: SessionFactory
    task_manager: TaskManager

    def _is_cancelled(self, task_id: str) -> bool:
        """
        检查任务是否已被请求取消

        返回:
            True 表示任务已请求取消，False 表示未取消
        """
        # 优先检查内存缓存（加速响应）
        task_info = self.task_manager.get_task(task_id)
        if task_info and task_info.cancel_event and task_info.cancel_event.is_set():
            return True

        # DB 检查：查询 cancel_requested 字段
        if self.session_factory:
            from src.storage.id_mapping import TaskIDNotFoundError, task_id_to_run_id
            from src.storage.repositories import RunRepository

            try:
                db_session = self.session_factory.get_session()
                with db_session:
                    # 使用底层 SQLAlchemy Session
                    sql_session = db_session.connection
                    try:
                        run_id = task_id_to_run_id(task_id, sql_session)
                    except (TaskIDNotFoundError, ValueError):
                        # 不存在对应 run 记录时，说明没有可持久化的取消请求
                        return False

                    run_repo = RunRepository(sql_session)
                    run = run_repo.get_run(run_id)
                    if run and run.get("cancel_requested", False):
                        return True
            except Exception as e:
                logger.error(f"Failed to check DB cancel_requested for task {task_id}: {e}")
                raise CancellationStateCheckError(f"任务 {task_id} 取消状态检查失败") from e

        return False

    def _prepare_task_execution_claim(self, task_id: str) -> str:
        """
        在真正启动分析前，先把任务从 DB 侧收口到可执行状态

        Returns:
            claimed: 当前 worker 已成功领取任务，可继续执行
            cancelled: 任务在真正执行前已被取消，调用方应直接结束
            skipped: 当前 worker 未获得执行权，调用方应静默退出
        """
        from src.storage.id_mapping import TaskIDNotFoundError, task_id_to_run_id
        from src.storage.repositories import RunRepository

        db_session = self.session_factory.get_session()
        try:
            with db_session:
                sql_session = db_session.connection
                try:
                    run_id = task_id_to_run_id(task_id, sql_session)
                except (TaskIDNotFoundError, ValueError) as exc:
                    raise AnalysisError(f"任务 {task_id} 不存在，无法启动执行") from exc

                run_repo = RunRepository(sql_session)
                run = run_repo.get_run(run_id)
                if run is None:
                    raise AnalysisError(f"任务 {task_id} 不存在，无法启动执行")

                status = run.get("status", "")
                cancel_requested = bool(run.get("cancel_requested", False))

                if status == "pending":
                    if cancel_requested:
                        # 未领取任务没有执行方收尾，直接落取消终态
                        run_repo.cancel_unclaimed_pending_run(run_id, message="任务在启动前已取消")
                        return "cancelled"
                    return self._claim_pending_run(run_repo, run_id)

                if status == "cancelled" and self._is_recent_resume_reset(run):
                    # 恢复 resume 后被旧 worker 延迟取消写回覆盖的短暂竞态
                    # 最近心跳且没有 worker 的 cancelled 任务可重新进入领取流程
                    run_repo.update_run_task_fields(run_id, status="pending", completed_at=None)
                    refreshed = run_repo.get_run(run_id)
                    if refreshed is None or refreshed.get("status") != "pending":
                        return "skipped"
                    if refreshed.get("cancel_requested", False):
                        run_repo.cancel_unclaimed_pending_run(run_id, message="任务在启动前已取消")
                        return "cancelled"
                    return self._claim_pending_run(run_repo, run_id)

                if status == "cancelling" and cancel_requested:
                    # 没有真实 worker 时直接收口，避免任务停在无 owner 的 cancelling
                    if refreshed_worker_id := run.get("worker_id"):
                        logger.info(
                            "Task {} is cancelling under worker {}, current worker skips execution claim",
                            task_id,
                            refreshed_worker_id,
                        )
                        return "skipped"

                    run_repo.update_run_task_fields(
                        run_id,
                        status="cancelled",
                        cancel_requested=False,
                        completed_at=datetime.now(UTC).replace(tzinfo=None),
                        message=run.get("message") or "任务在启动前已取消",
                        worker_id=None,
                        heartbeat_at=None,
                    )
                    return "cancelled"

                if status in ("running", "completed", "cancelled"):
                    return "skipped"

                return "skipped"
        except AnalysisError:
            raise
        except Exception as exc:
            logger.error(f"Failed to prepare execution claim for task {task_id}: {exc}")
            raise AnalysisError(f"任务 {task_id} 执行领取失败") from exc

    def _claim_pending_run(self, run_repo: Any, run_id: str) -> str:
        """
        领取 pending 任务：原子 claim，失败时按最新状态判定取消/跳过

        Returns:
            claimed: 当前 worker 已成功领取任务，可继续执行
            cancelled: 任务在真正执行前已被取消，调用方应直接结束
            skipped: 当前 worker 未获得执行权，调用方应静默退出
        """
        claimed = run_repo.claim_pending_run(
            run_id,
            worker_id=self.task_manager.get_worker_id(),
            # 无时区列统一写入 naive UTC
            heartbeat_at=datetime.now(UTC).replace(tzinfo=None),
        )
        if claimed:
            return "claimed"

        refreshed = run_repo.get_run(run_id)
        if refreshed is None:
            return "skipped"

        refreshed_status = refreshed.get("status")
        if refreshed_status == "cancelled":
            return "cancelled"
        if refreshed_status == "cancelling" and refreshed.get("cancel_requested"):
            # 取消可能在读取 pending 与原子领取之间到达
            # 有 worker 时由其收尾，无 worker 时直接落取消终态
            if refreshed.get("worker_id"):
                return "skipped"
            run_repo.update_run_task_fields(
                run_id,
                status="cancelled",
                cancel_requested=False,
                completed_at=datetime.now(UTC).replace(tzinfo=None),
                message=refreshed.get("message") or "任务在启动前已取消",
                worker_id=None,
                heartbeat_at=None,
            )
            return "cancelled"
        return "skipped"

    def _is_recent_resume_reset(self, run: dict) -> bool:
        """
        判定 run 是否处于"刚被 resume 重置"的竞态窗口

        最近心跳且没有 worker 表示可能被旧 worker 的延迟取消写回覆盖
        """
        if run.get("worker_id") is not None:
            return False
        heartbeat_at = run.get("heartbeat_at")
        if not heartbeat_at:
            return False
        try:
            heartbeat_dt = datetime.fromisoformat(heartbeat_at)
        except (TypeError, ValueError):
            return False
        # 无时区心跳按 UTC 解释，与写入端和孤儿回收口径保持一致
        if heartbeat_dt.tzinfo is None:
            heartbeat_dt = heartbeat_dt.replace(tzinfo=UTC)
        cutoff = datetime.now(UTC) - timedelta(seconds=_RESUME_RESET_WINDOW_SECONDS)
        return heartbeat_dt >= cutoff
