"""
分析服务类
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from loguru import logger
from sqlalchemy.orm import Session

from src.api.exceptions import AnalysisError, NovelNotFoundError
from src.api.models.events import AnalysisEventBus, StreamEvent, StreamMessageType
from src.api.models.requests import ReanalyzeRequest
from src.api.models.responses import TaskStatus
from src.api.services.analysis.environment_initializer import EnvironmentInitializer
from src.api.services.analysis.error_handler import AnalysisErrorHandler
from src.api.services.analysis.stage_executor import StageExecutor
from src.api.services.event_manager import event_manager
from src.api.services.novel_service import NovelService
from src.api.services.task_manager import TaskManager
from src.config import settings
from src.config.analysis_logger import AnalysisLogger
from src.storage.session import SessionFactory


class CancellationStateCheckError(RuntimeError):
    """
    取消状态检查失败异常
    """


TASK_KIND_ANALYSIS = "analysis"
TASK_KIND_REANALYSIS = "reanalysis"

# 任务 claim 时判定"刚被 resume 重置"的竞态窗口：resume 重置后旧 worker 的延迟取消
# 写回可能把状态覆盖回 cancelled，只有在该窗口内的重置才允许 claim 侧重新激活
_RESUME_RESET_WINDOW_SECONDS = 30


class AnalysisService:
    def __init__(
        self,
        novel_service: NovelService,
        task_manager: TaskManager,
        session_factory: SessionFactory | None = None,
    ):
        self.novel_service = novel_service
        self.task_manager = task_manager
        self.session_factory = session_factory or SessionFactory()
        self.env_initializer = EnvironmentInitializer(self.session_factory)
        self.stage_executor = StageExecutor()
        self.error_handler = AnalysisErrorHandler(
            novel_service=novel_service,
            task_manager=task_manager,
        )

    @staticmethod
    def _make_stage_emitter(bus: AnalysisEventBus, stage: str) -> Callable[[StreamEvent], Awaitable[None]]:
        """创建阶段 emitter：自动补全 stage 上下文"""

        async def emitter(event: StreamEvent) -> None:
            if not event.stage:
                # 用 dataclass replace 补全 stage，避免手动重建丢失字段
                from dataclasses import replace

                event = replace(event, stage=stage)
            await bus.emit(event)

        return emitter

    async def _execute_analysis_stages(
        self,
        bus: AnalysisEventBus,
        session: Session,
        run_id: str,
        source_path: Path,
        novel_id: str,
        novel_title: str | None,
        analysis_logger: AnalysisLogger | None,
        skip_stages: dict[str, bool],
        num_topics: int,
    ) -> None:
        """
        执行各分析阶段
        """
        task_id = bus.task_id

        if self._is_cancelled(task_id):
            await self.error_handler.handle_cancel(task_id, novel_id, session, run_id, analysis_logger, bus)
            return

        # ── 预处理 ──
        if not skip_stages["skip_preprocess"]:
            await bus.emit_stage_start(
                "preprocess", message="开始预处理", percent=settings.progress.preprocess.start
            )

            await self.stage_executor.run_preprocess(
                source_path, run_id, session, emitter=self._make_stage_emitter(bus, "preprocess")
            )
            await bus.emit_stage_complete("preprocess")

        if self._is_cancelled(task_id):
            await self.error_handler.handle_cancel(task_id, novel_id, session, run_id, analysis_logger, bus)
            return

        # ── 标注 ──
        if not skip_stages["skip_annotate"]:
            # 查询 chunk 总数，让前端知道进度规模
            total_chunks = 0
            try:
                from src.storage.repositories import ChunkRepository

                chunk_repo = ChunkRepository(session)
                total_chunks = chunk_repo.count_chunks(run_id)
            except Exception as exc:
                logger.warning(
                    "Failed to count chunks before annotate stage, "
                    "falling back to total=0: task_id={} run_id={} error={}",
                    task_id,
                    run_id,
                    exc,
                )

            await bus.emit_stage_start(
                "annotate",
                message="开始标注分析",
                percent=settings.progress.annotate.start,
                total=total_chunks,
            )

            await self.stage_executor.run_annotate(
                run_id,
                session,
                novel_id,
                analysis_logger,
                novel_title,
                emitter=self._make_stage_emitter(bus, "annotate"),
                is_cancelled=lambda: self._is_cancelled(task_id),
            )
            await bus.emit_stage_complete("annotate")

        if self._is_cancelled(task_id):
            await self.error_handler.handle_cancel(task_id, novel_id, session, run_id, analysis_logger, bus)
            return

        # ── 聚合 ──
        if not skip_stages["skip_aggregate"]:
            await bus.emit_stage_start(
                "aggregate", message="开始数据聚合", percent=settings.progress.aggregate.start
            )

            await self.stage_executor.run_aggregate(run_id, session, self._make_stage_emitter(bus, "aggregate"))
            await bus.emit_stage_complete("aggregate")

        if self._is_cancelled(task_id):
            await self.error_handler.handle_cancel(task_id, novel_id, session, run_id, analysis_logger, bus)
            return

        # ── 主题建模 ──
        if not skip_stages["skip_topic_model"]:
            await bus.emit_stage_start(
                "topic-model", message="开始主题建模", percent=settings.progress.topic_model.start
            )

            await self.stage_executor.run_topic_model(
                run_id, session, num_topics, self._make_stage_emitter(bus, "topic-model")
            )
            await bus.emit_stage_complete("topic-model")

        if self._is_cancelled(task_id):
            await self.error_handler.handle_cancel(task_id, novel_id, session, run_id, analysis_logger, bus)
            return

        # ── 诊断 ──
        if not skip_stages["skip_diagnose"]:
            await bus.emit_stage_start(
                "diagnose", message="开始诊断报告", percent=settings.progress.diagnose.start
            )

            await self.stage_executor.run_diagnose(
                run_id, session, analysis_logger, self._make_stage_emitter(bus, "diagnose")
            )
            await bus.emit_stage_complete("diagnose")

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

    def _check_all_stages_completed(self, skip_stages: dict[str, bool]) -> bool:
        return (
            skip_stages["skip_preprocess"]
            and skip_stages["skip_annotate"]
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
        """处理已完成的分析任务，确保 DB 状态一致
        """
        logger.info(f"Task {task_id} already completed, no action needed")
        self.novel_service.update_task_status(task_id, "completed")
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
                    completed_at=datetime.now(UTC),
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
                # 2026-08-13 修复：不用 `with sql_session.begin():` 包裹——兜底路径可能在
                # _is_cancelled 等查询已开启隐式事务后进入，begin() 会抛
                # "A transaction is already begun on this Session" 并被内部 except 吞掉，
                # 导致 DB 终态实际未写入。update_run_task_fields 内部自带 commit，
                # 无论 session 是否已有事务都能正确提交。
                run_repo.update_run_task_fields(
                    run_id,
                    status="failed",
                    error=error_message,
                    completed_at=datetime.now(UTC),
                )
        except TaskIDNotFoundError:
            logger.warning(f"Task {task_id} not found in id_mapping during failure DB write, skipping")
        except Exception as e:
            logger.error(f"Failed to write failure status to DB for task {task_id}: {e}")

    def _build_reanalysis_skip_stages(self, request: ReanalyzeRequest | None) -> dict[str, bool]:
        if request is None:
            return {
                "skip_preprocess": False,
                "skip_annotate": False,
                "skip_aggregate": False,
                "skip_topic_model": False,
                "skip_diagnose": False,
            }
        all_force_false = (
            not request.force_preprocess
            and not request.force_annotate
            and not request.force_aggregate
            and not request.force_topic_model
            and not request.force_diagnose
        )
        if all_force_false:
            return {
                "skip_preprocess": False,
                "skip_annotate": False,
                "skip_aggregate": False,
                "skip_topic_model": False,
                "skip_diagnose": False,
            }
        return {
            "skip_preprocess": not request.force_preprocess,
            "skip_annotate": not request.force_annotate,
            "skip_aggregate": not request.force_aggregate,
            "skip_topic_model": not request.force_topic_model,
            "skip_diagnose": not request.force_diagnose,
        }

    def _build_reanalysis_request_payload(self, request: ReanalyzeRequest | None) -> dict[str, object] | None:
        """
        构建可持久化的重分析请求载荷
        """
        if request is None:
            return None
        return request.model_dump(mode="json", exclude_none=True)

    def _restore_execution_request(self, task: dict) -> tuple[str, ReanalyzeRequest | None]:
        """
        从任务元数据恢复执行类型与请求参数
        """
        task_kind = task["task_kind"]
        if task_kind == TASK_KIND_ANALYSIS:
            return task_kind, None
        if task_kind == TASK_KIND_REANALYSIS:
            request_payload = task.get("request_payload")
            if request_payload is None:
                return task_kind, None
            return task_kind, ReanalyzeRequest.model_validate(request_payload)
        raise ValueError(f"任务 {task['task_id']} 的 task_kind 非法: {task_kind}")

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
                        # 用户在 worker 真正领取前就已经点了取消，此时直接落终态，
                        # 比先进入 cancelling 再等待一个不存在的执行方收尾更符合 DB-first 语义
                        run_repo.cancel_unclaimed_pending_run(run_id, message="任务在启动前已取消")
                        return "cancelled"
                    return self._claim_pending_run(run_repo, run_id)

                if status == "cancelled" and self._is_recent_resume_reset(run):
                    # resume 竞态恢复：resume 先把 DB 重置为 pending，旧 worker 的延迟取消
                    # 写回（handle_cancel 的 commit）可能随后把状态覆盖回 cancelled，导致新 worker
                    # 看到 cancelled 静默退出、resume 返回 200 但任务停住。该状态的特征是
                    # worker_id=None 且 heartbeat_at 为最近的 resume 重置时间；真实取消
                    # （取消未领取任务 / 执行中取消）都不会同时满足。重新激活为 pending 后走正常领取。
                    run_repo.update_run_task_fields(run_id, status="pending", completed_at=None)
                    refreshed = run_repo.get_run(run_id)
                    if refreshed is None or refreshed.get("status") != "pending":
                        return "skipped"
                    if refreshed.get("cancel_requested", False):
                        run_repo.cancel_unclaimed_pending_run(run_id, message="任务在启动前已取消")
                        return "cancelled"
                    return self._claim_pending_run(run_repo, run_id)

                if status == "cancelling" and cancel_requested:
                    # 这类任务没有真实 worker 可收尾时，直接在启动前完成取消收口，
                    # 避免卡在无 owner 的 cancelling 历史脏状态
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
                        completed_at=datetime.now(UTC),
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
            # 2026-08-13 P2：heartbeat_at 列无时区，落 naive UTC 挂钟（避免会话时区转换错位）
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
            # 2026-08-13 修复：取消信号落在「读 pending」与「原子 claim」之间的窗口时，
            # claim 的 UPDATE 不命中（status 已变 cancelling），此前直接返回 skipped 静默退出，
            # 任务会永久卡在无 owner 的 cancelling（再 cancel 400、resume 拒绝）。
            # 与 _prepare_task_execution_claim 的 cancelling 收口同口径：
            # 有 worker 的 cancelling 由该 worker 收尾，无 worker 的在此直接落 cancelled 终态。
            if refreshed.get("worker_id"):
                return "skipped"
            run_repo.update_run_task_fields(
                run_id,
                status="cancelled",
                cancel_requested=False,
                completed_at=datetime.now(UTC),
                message=refreshed.get("message") or "任务在启动前已取消",
                worker_id=None,
                heartbeat_at=None,
            )
            return "cancelled"
        return "skipped"

    def _is_recent_resume_reset(self, run: dict) -> bool:
        """
        判定 run 是否处于"刚被 resume 重置"的竞态窗口

        resume 重置会写入 worker_id=None 且 pending 状态写回自动刷新 heartbeat_at=now；
        若随后被旧 worker 的延迟取消写回覆盖为 cancelled，这两个字段保持不变。据此区分
        "resume 后的陈旧取消写回"与"真实用户取消"（后者 heartbeat_at 为 None 或早已陈旧）。
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
        # 2026-08-13 P2：写入端与孤儿回收（main.py）均以 UTC 生成/比较心跳时间。
        # analysis_runs 的 DateTime 列不带时区，写入时 tz 被剥离、读回为 naive UTC
        # 挂钟；这里统一补 UTC 后与 UTC 挂钟比较，避免服务器本地时区偏移
        # （如 UTC+8）把真实取消误判为「resume 后的陈旧取消写回」
        if heartbeat_dt.tzinfo is None:
            heartbeat_dt = heartbeat_dt.replace(tzinfo=UTC)
        cutoff = datetime.now(UTC) - timedelta(seconds=_RESUME_RESET_WINDOW_SECONDS)
        return heartbeat_dt >= cutoff

    async def recover_pending_tasks(self) -> tuple[int, int]:
        """
        启动时把 DB 中的 pending 任务重新接回当前执行器

        修改原因: startup recovery 需要按任务级隔离异常；
        单个 pending 恢复失败不能把后续 pending 任务整轮拦死

        Returns:
            tuple[int, int]: (scheduled_count, cancelled_count)
        """
        from src.storage.repositories import RunRepository

        scheduled_count = 0
        cancelled_count = 0
        db_session = self.session_factory.get_session()
        try:
            with db_session:
                run_repo = RunRepository(db_session.connection)
                pending_runs = run_repo.get_pending_tasks()

            for run in pending_runs:
                task_id = run["run_id"][:8] if len(run["run_id"]) >= 8 else run["run_id"]
                try:
                    if run.get("cancel_requested", False):
                        db_session = self.session_factory.get_session()
                        with db_session:
                            RunRepository(db_session.connection).cancel_unclaimed_pending_run(
                                run["run_id"],
                                message="任务在启动恢复前已取消",
                            )
                        cancelled_count += 1
                        continue

                    await self.resume_task(run["novel_id"], task_id)
                    scheduled_count += 1
                except (ValueError, NovelNotFoundError) as exc:
                    logger.warning(f"Skip pending task {task_id} during startup recovery: {exc}")
                except Exception as exc:
                    logger.exception(f"Failed to recover pending task {task_id} during startup recovery: {exc}")
        except Exception as exc:
            logger.error(f"Failed to recover pending tasks on startup: {exc}")
            raise

        return scheduled_count, cancelled_count

    def _schedule_analysis_task(self, task_id: str, novel: dict) -> None:
        """
        安排分析协程并记录 asyncio.Task 引用

        说明: 统一 create/resume 两条路径的协程调度，避免重复代码
        """
        task = asyncio.create_task(self._run_analysis(task_id, novel))
        self.task_manager.store_asyncio_task(task_id, task)

    def _schedule_reanalysis_task(self, task_id: str, novel: dict, request: ReanalyzeRequest | None = None) -> None:
        """
        安排重分析协程并记录 asyncio.Task 引用
        """
        task = asyncio.create_task(self._run_reanalysis(task_id, novel, request))
        self.task_manager.store_asyncio_task(task_id, task)

    def _schedule_task_execution(
        self,
        task_id: str,
        novel: dict,
        task_kind: str,
        request: ReanalyzeRequest | None,
    ) -> None:
        """
        按任务类型调度执行协程
        """
        if task_kind == TASK_KIND_ANALYSIS:
            self._schedule_analysis_task(task_id, novel)
            return
        if task_kind == TASK_KIND_REANALYSIS:
            self._schedule_reanalysis_task(task_id, novel, request)
            return
        raise ValueError(f"任务 {task_id} 的 task_kind 非法: {task_kind}")

    async def create_task_and_start(self, novel_id: str) -> str:
        """
        创建新任务并立即启动分析

        说明: 只负责“创建+启动”，不做复用/猜测行为
        """
        novel = self.novel_service.get_novel(novel_id)
        task_id = self.novel_service.create_task(novel_id, task_kind=TASK_KIND_ANALYSIS)
        self.task_manager.create_task(task_id, novel_id)
        self._schedule_task_execution(task_id, novel, TASK_KIND_ANALYSIS, None)
        return task_id

    async def resume_task(self, novel_id: str, task_id: str) -> str:
        """
        继续执行 pending/failed/cancelled 任务

        说明: 只负责“继续已有任务”，不创建新任务
        """
        novel = self.novel_service.get_novel(novel_id)
        task = self.novel_service.get_task(task_id)

        if task.get("novel_id") != novel_id:
            raise ValueError(f"任务 {task_id} 不属于小说 {novel_id}")

        status = task.get("status", "")
        if status not in ("pending", "failed", "cancelled"):
            raise ValueError(f"仅支持继续 pending/failed/cancelled 任务，当前状态为 {status}")

        task_info = self.task_manager.get_task(task_id)
        if task_info and task_info.asyncio_task and not task_info.asyncio_task.done():
            raise ValueError(f"任务 {task_id} 正在运行，不能重复继续")

        if task_info is None:
            self.task_manager.create_task(task_id, novel_id)

        # 重置内存态与 DB 运行态，避免 DB-only 状态接口短暂暴露上一轮失败残留
        self.task_manager.update_task(
            task_id,
            status=TaskStatus.PENDING,
            progress=0.0,
            stage=None,
            sub_stage=None,
            current=0,
            total=100,
            message=None,
            error=None,
            cancel_requested=False,
            worker_id=None,
            heartbeat_at=None,
            llm_outputs=[],
            completed_at=None,
        )

        # 清空上一轮 SSE 终态事件缓冲，避免重连客户端先回放 task_cancelled/task_error/
        # task_complete 再收新一轮 stage_start（resume 启动的是全新一轮，旧终态不应再出现）
        event_manager.clear_buffer(task_id)

        task_kind, execution_request = self._restore_execution_request(task)
        self._schedule_task_execution(task_id, novel, task_kind, execution_request)
        return task_id

    async def start_reanalysis(self, novel_id: str, request: ReanalyzeRequest | None = None) -> str:
        novel = self.novel_service.get_novel(novel_id)

        task_id = self.novel_service.create_task(
            novel_id,
            task_kind=TASK_KIND_REANALYSIS,
            request_payload=self._build_reanalysis_request_payload(request),
        )
        self.task_manager.create_task(task_id, novel_id)
        self._schedule_task_execution(task_id, novel, TASK_KIND_REANALYSIS, request)

        return task_id

    async def _run_analysis(self, task_id: str, novel: dict) -> None:
        """
        执行分析任务
        """
        num_topics = settings.topic_model.num_topics

        def skip_stages_builder(session: Session, run_id: str) -> dict[str, bool]:
            return self.env_initializer.check_stage_completion_status(session, run_id)

        def pre_execute_hook(novel_id: str, skip_stages: dict[str, bool]) -> bool:
            if self._check_all_stages_completed(skip_stages):
                self._handle_already_completed(task_id, novel_id, None)
                return True
            return False

        await self._run_analysis_core(
            task_id=task_id,
            novel=novel,
            skip_stages_builder=skip_stages_builder,
            num_topics=num_topics,
            log_prefix="Analysis",
            pre_execute_hook=pre_execute_hook,
        )

    async def _run_reanalysis(self, task_id: str, novel: dict, request: ReanalyzeRequest | None) -> None:
        """
        执行重新分析任务
        """
        skip_stages = self._build_reanalysis_skip_stages(request)
        logger.info(f"Reanalysis skip_stages: {skip_stages}")
        num_topics = request.num_topics if request else settings.topic_model.num_topics

        def skip_stages_builder(session: Session, run_id: str) -> dict[str, bool]:
            return skip_stages

        await self._run_analysis_core(
            task_id=task_id,
            novel=novel,
            skip_stages_builder=skip_stages_builder,
            num_topics=num_topics,
            log_prefix="Reanalysis",
        )

    async def _call_execute_analysis_stages(
        self,
        bus: AnalysisEventBus,
        session: Session,
        run_id: str,
        source_path: Path,
        novel_id: str,
        novel_title: str | None,
        analysis_logger: AnalysisLogger | None,
        skip_stages: dict[str, bool],
        num_topics: int,
    ) -> None:
        """
        调用 _execute_analysis_stages

        说明: 消除 _run_analysis_core 中重复的 _execute_analysis_stages 调用逻辑
        """
        await self._execute_analysis_stages(
            bus=bus,
            session=session,
            run_id=run_id,
            source_path=source_path,
            novel_id=novel_id,
            novel_title=novel_title,
            analysis_logger=analysis_logger,
            skip_stages=skip_stages,
            num_topics=num_topics,
        )

    async def _run_analysis_core(
        self,
        task_id: str,
        novel: dict,
        skip_stages_builder: Callable[[Session, str], dict[str, bool]],
        num_topics: int,
        log_prefix: str = "Analysis",
        pre_execute_hook: Callable[[str, dict[str, bool]], bool] | None = None,
    ) -> None:
        """
        统一的分析执行核心逻辑

        说明: 封装 _run_analysis 和 _run_reanalysis 的公共逻辑

        Args:
            task_id: 任务ID
            novel: 小说信息字典
            skip_stages_builder: 构建 skip_stages 的函数
            num_topics: 主题数量
            log_prefix: 日志前缀
            pre_execute_hook: 执行前的钩子函数，返回 True 表示跳过执行
        """
        start_time = time.time()
        analysis_logger: AnalysisLogger | None = None
        session: Session | None = None
        run_id: str | None = None
        bus: AnalysisEventBus | None = None

        try:
            self.task_manager.update_task(task_id, cancel_event=asyncio.Event())

            claim_result = self._prepare_task_execution_claim(task_id)
            if claim_result == "cancelled":
                self.task_manager.cancel_completed_task(task_id, error="用户取消")
                logger.info(f"Task {task_id} was cancelled before execution claim completed")
                # 2026-08-14 P2-10：claim 前取消（含 _claim_pending_run 内部收口分支）也
                # 必须补发 SSE 终态事件，否则已连接的客户端永远等不到取消信号，
                # 只能靠轮询 /status 兜底
                await event_manager.send(
                    task_id=task_id,
                    event_type=StreamMessageType.task_cancelled.value,
                    data={"stage": "cancelled", "message": "任务已取消"},
                )
                return
            if claim_result == "skipped":
                logger.info(f"Task {task_id} execution claim skipped because another state transition won the DB truth")
                # 2026-08-13 P2：skipped 也要清掉本进程的内存执行缓存（停心跳），
                # 否则残留 TaskInfo 的心跳写回会覆盖真实 owner 的 worker_id/heartbeat_at
                self.task_manager.cancel_completed_task(task_id)
                return

            (
                novel_id,
                source_path,
                novel_title,
                session,
                analysis_logger,
                run_id,
            ) = self.env_initializer.init_analysis_environment(task_id, novel)

            skip_stages = skip_stages_builder(session, run_id)

            if pre_execute_hook and pre_execute_hook(novel_id, skip_stages):
                return

            self.task_manager.update_task(task_id, status=TaskStatus.RUNNING, stage="preprocess", progress=0)

            bus = AnalysisEventBus(task_id, self.task_manager)

            await self._call_execute_analysis_stages(
                bus=bus,
                session=session,
                run_id=run_id,
                source_path=source_path,
                novel_id=novel_id,
                novel_title=novel_title,
                analysis_logger=analysis_logger,
                skip_stages=skip_stages,
                num_topics=num_topics,
            )

            if self._is_cancelled(task_id):
                # 2026-08-14 P2-13：所有阶段已完成但成功收口前收到取消——此前直接
                # return 既不落 DB 终态也不发事件，run 卡在 running 直到重启孤儿回收
                if session and run_id:
                    await self.error_handler.handle_cancel(
                        task_id, novel.get("novel_id", "unknown"), session, run_id, analysis_logger, bus=bus
                    )
                return

            elapsed = time.time() - start_time
            await self.error_handler.handle_success(
                task_id, novel_id, elapsed, analysis_logger, session, run_id, bus=bus, log_prefix=log_prefix
            )

        except asyncio.CancelledError:
            logger.info(f"Task {task_id} was cancelled via asyncio.Task.cancel()")
            if session and run_id:
                await self.error_handler.handle_cancel(
                    task_id, novel.get("novel_id", "unknown"), session, run_id, analysis_logger, bus=bus
                )
        except Exception as e:
            elapsed = time.time() - start_time
            if isinstance(e, CancellationStateCheckError):
                if session and run_id:
                    await self.error_handler.handle_failure(
                        task_id,
                        novel.get("novel_id", "unknown"),
                        elapsed,
                        e,
                        analysis_logger,
                        session,
                        run_id,
                        bus=bus,
                        log_prefix=log_prefix,
                    )
                else:
                    self.novel_service.update_task_status(task_id, "failed")
                    self.task_manager.complete_task(task_id, success=False, error=str(e))
                    self._write_failure_to_db(task_id, str(e))
                return

            cancelled = False
            try:
                cancelled = self._is_cancelled(task_id)
            except CancellationStateCheckError as cancel_check_error:
                # 原始异常已经存在时，取消状态检查失败不应覆盖原始失败，只记录并按失败路径收口
                logger.error(f"Failed to re-check cancellation state for task {task_id}: {cancel_check_error}")

            if cancelled and session and run_id:
                await self.error_handler.handle_cancel(
                    task_id, novel.get("novel_id", "unknown"), session, run_id, analysis_logger, bus=bus
                )
            elif session and run_id:
                await self.error_handler.handle_failure(
                    task_id,
                    novel.get("novel_id", "unknown"),
                    elapsed,
                    e,
                    analysis_logger,
                    session,
                    run_id,
                    bus=bus,
                    log_prefix=log_prefix,
                )
            else:
                # 2026-08-13 修复：与 CancellationStateCheckError 分支同口径，
                # 环境初始化失败（session/run_id 均缺失）时也必须把 DB 终态写下去，
                # 否则 run 永远停在 running/pending，只能等重启心跳超时兜底
                self.novel_service.update_task_status(task_id, "failed")
                self.task_manager.complete_task(task_id, success=False, error=str(e))
                self._write_failure_to_db(task_id, str(e))
        finally:
            if analysis_logger:
                analysis_logger.close()
            if session:
                session.close()

    def get_task_status(self, task_id: str) -> dict | None:
        """
        获取任务状态（DB-only 查询）

        说明: 从数据库查询任务状态，不再依赖内存中的 TaskManager
        """
        task = self.novel_service.get_run_by_task_id(task_id)
        if not task:
            return None
        return {
            "task_id": task["task_id"],
            "novel_id": task["novel_id"],
            "status": task["status"],
            "run_id": task["run_id"],
        }

    def get_novel_tasks(self, novel_id: str) -> list[dict]:
        """
        获取小说的所有任务（DB-only 查询）

        说明: 从数据库查询小说的任务列表，不再依赖内存中的 TaskManager
        """
        tasks = self.novel_service.get_tasks_by_novel(novel_id)
        return tasks
