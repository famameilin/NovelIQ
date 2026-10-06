"""
分析错误处理服务

说明: 负责处理分析过程中的成功、失败和取消事件

修改时间: 2026-10-02
修改者: Trae
修改内容: 大文件拆分——自 analysis_service.py 并入终态兜底逻辑
（_check_all_stages_completed/_handle_already_completed/_write_failure_to_db），
以 TerminalStateFallbackMixin 混入形式提供给 AnalysisService
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

from loguru import logger
from sqlalchemy.orm import Session

from src.storage.repositories import RunRepository
from src.storage.session import SessionFactory

if TYPE_CHECKING:
    from src.config.analysis_logger import AnalysisLogger
    from src.work.events import AnalysisEventBus
    from src.work.task_manager import TaskManager
    from src.workflows.tasks import TaskService


class AnalysisErrorHandler:
    """分析错误处理服务"""

    def __init__(
        self,
        task_service: TaskService,
        task_manager: TaskManager,
    ):
        self.task_service = task_service
        self.task_manager = task_manager

    def _run_still_owned_by_current_worker(self, session: Session, run_id: str) -> bool:
        """
        2026-08-14 P2-13：终态写回前的 worker 归属守卫

        resume 会把 run 重置为 pending 并被新 worker 领取；旧 worker 的延迟
        取消/失败写回若直接落终态，会覆写新轮 running 状态。此处比较 run 当前
        worker_id 与当前 worker：不匹配（已被新轮接管）或 run 已不存在时跳过
        DB 终态写回与 SSE 终态事件，避免旧轮终态污染新轮。
        """
        run = RunRepository(session).get_run(run_id)
        if run is None:
            return False
        worker_id = run.get("worker_id")
        if worker_id is None:
            # 无归属（如 claim 前取消路径，DB 终态由 cancel_unclaimed_pending_run 落库）
            return True
        return worker_id == self.task_manager.get_worker_id()

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
        self.task_manager.complete_task(task_id, success=True)

        # 2026-08-14 P2-13：旧 worker 延迟写回守卫（run 已被 resume 新轮接管时跳过）
        if not self._run_still_owned_by_current_worker(session, run_id):
            logger.warning(
                f"Task {task_id} 已完成但 run {run_id} 已被其他 worker 接管，"
                "跳过终态 DB 写回与事件推送（旧轮收口，避免覆写新轮状态）"
            )
            return

        run_repo = RunRepository(session)
        # 2026-08-13 P2：成功收口必须把 progress 归一为 100.0，
        # 避免 DB 中完成任务的进度停留在最后阶段区间（如 95.x）而 /status 误报未完成
        try:
            run_repo.update_run_task_fields(
                run_id,
                status="completed",
                progress=100.0,
                completed_at=datetime.now(UTC).replace(tzinfo=None),
            )
            session.commit()
        except Exception as exc:
            # 2026-08-14 P2-12：终态 DB 写失败不再静默/上抛——内存态已收口，
            # DB 停留在旧状态，留给重启孤儿回收兜底；显式告警便于排查
            logger.error(f"Task {task_id} 终态 DB 写回失败（内存态已收口，DB 状态待重启回收兜底）: {exc}")

        # 任务完成后上报读侧失效聚合指标缓存，确保新分析结果立即生效
        # 该缓存归读侧（api 依赖注入层）所有并在此注入回调，执行层不直接依赖读侧实现
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
        logger.error(f"{log_prefix} failed: {task_id} - {error}")
        self.task_manager.complete_task(task_id, success=False, error=str(error))

        # 这里必须先清掉失败现场遗留的未提交事务，
        # 再写 run 状态；否则后续 commit 会把半成品业务数据一并刷进数据库
        session.rollback()
        # 2026-08-14 P2-13：旧 worker 延迟写回守卫（run 已被 resume 新轮接管时跳过）
        if not self._run_still_owned_by_current_worker(session, run_id):
            logger.warning(
                f"Task {task_id} 失败但 run {run_id} 已被其他 worker 接管，"
                "跳过终态 DB 写回与事件推送（旧轮收口，避免覆写新轮状态）"
            )
            return
        run_repo = RunRepository(session)
        # 2026-08-13 修复：update_run_status 只写 status 不写 error 列，
        # 导致 DB 中 failed 任务 error 恒为 NULL、/status 接口 error 永远 None，
        # 前端重连后只能显示兜底「分析失败」文案。改为 update_run_task_fields 一并落 error。
        try:
            run_repo.update_run_task_fields(
                run_id,
                status="failed",
                error=str(error),
                completed_at=datetime.now(UTC).replace(tzinfo=None),
            )
            session.commit()
        except Exception as exc:
            logger.error(f"Task {task_id} 终态 DB 写回失败（内存态已收口，DB 状态待重启回收兜底）: {exc}")

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

        # 取消路径与失败路径一样，共享同一个 session；
        # 若不先 rollback，commit cancel 状态时仍会把之前残留的脏写入一起提交
        session.rollback()
        # 2026-08-14 P2-13：旧 worker 延迟取消写回守卫（run 已被 resume 新轮接管时跳过）
        if not self._run_still_owned_by_current_worker(session, run_id):
            logger.warning(
                f"Task {task_id} 取消但 run {run_id} 已被其他 worker 接管，"
                "跳过终态 DB 写回与事件推送（旧轮收口，避免覆写新轮状态）"
            )
            return
        run_repo = RunRepository(session)
        try:
            run_repo.update_run_task_fields(
                run_id,
                status="cancelled",
                cancel_requested=False,
                completed_at=datetime.now(UTC).replace(tzinfo=None),
            )
            session.commit()
        except Exception as exc:
            logger.error(f"Task {task_id} 终态 DB 写回失败（内存态已收口，DB 状态待重启回收兜底）: {exc}")

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
    """
    终态兜底混入（2026-10-02 自 analysis_service.py 并入）

    宿主需提供 task_service/task_manager/session_factory；方法体与原实现保持一致
    """

    task_service: TaskService
    task_manager: TaskManager
    session_factory: SessionFactory

    def _check_all_stages_completed(self, skip_stages: dict[str, bool]) -> bool:
        return (
            skip_stages["skip_preprocess"]
            and skip_stages["skip_annotate"]
            and skip_stages["skip_linguistic"]
            and skip_stages["skip_aggregate"]
            and skip_stages["skip_topic_model"]
            and skip_stages["skip_diagnose"]
        )

    def _handle_already_completed(
        self,
        task_id: str,
        novel_id: str,
        analysis_logger: AnalysisLogger | None,
    ) -> None:
        """处理已完成的分析任务，确保 DB 状态一致"""
        logger.info(f"Task {task_id} already completed, no action needed")
        self.task_manager.complete_task(task_id, success=True)

        # DB 终态写入：由于 complete_task() 不再写 DB，需自行操作
        from src.storage.id_mapping import task_id_to_run_id
        from src.storage.repositories import RunRepository

        sf = self.session_factory or SessionFactory()
        db_session = sf.get_session()
        with db_session:
            sql_session = db_session.connection
            with sql_session.begin():
                run_repo = RunRepository(sql_session)
                run_id = task_id_to_run_id(task_id, sql_session)
                run_repo.update_run_task_fields(
                    run_id,
                    status="completed",
                    progress=100.0,
                    completed_at=datetime.now(UTC).replace(tzinfo=None),
                )

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
        from src.storage.repositories import RunRepository

        try:
            sf = self.session_factory or SessionFactory()
            db_session = sf.get_session()
            with db_session:
                sql_session = db_session.connection
                run_repo = RunRepository(sql_session)
                run_id = task_id_to_run_id(task_id, sql_session)
                # update_run_task_fields 自带提交，可兼容查询已开启的隐式事务
                run_repo.update_run_task_fields(
                    run_id,
                    status="failed",
                    error=error_message,
                    completed_at=datetime.now(UTC).replace(tzinfo=None),
                )
        except TaskIDNotFoundError:
            logger.warning(f"Task {task_id} not found in id_mapping during failure DB write, skipping")
        except Exception as e:
            logger.error(f"Failed to write failure status to DB for task {task_id}: {e}")
