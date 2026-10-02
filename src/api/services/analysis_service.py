"""
分析服务类

修改时间: 2026-10-02
修改者: Trae
修改内容: 大文件拆分——取消检查与 DB 领取状态机迁至 src/api/services/analysis/task_claim.py，
阶段编排迁至 src/api/services/analysis/stage_orchestrator.py，终态兜底迁至
src/api/services/analysis/error_handler.py（TerminalStateFallbackMixin）。
本模块保留构造与公开入口，并 re-export 拆出符号以维持既有导入路径。
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Callable

from loguru import logger
from sqlalchemy.orm import Session

from src.api.exceptions import NovelNotFoundError
from src.api.models.events import AnalysisEventBus, StreamMessageType
from src.api.models.requests import ReanalyzeRequest
from src.api.models.responses import TaskStatus
from src.api.services.analysis.environment_initializer import EnvironmentInitializer
from src.api.services.analysis.error_handler import AnalysisErrorHandler, TerminalStateFallbackMixin
from src.api.services.analysis.stage_executor import StageExecutor
from src.api.services.analysis.stage_orchestrator import StageOrchestratorMixin
from src.api.services.analysis.task_claim import (
    _RESUME_RESET_WINDOW_SECONDS,
    CancellationStateCheckError,
)
from src.api.services.event_manager import event_manager
from src.api.services.novel_service import NovelService
from src.api.services.task_manager import TaskManager
from src.config import settings
from src.config.analysis_logger import AnalysisLogger
from src.storage.session import SessionFactory

__all__ = [
    "TASK_KIND_ANALYSIS",
    "TASK_KIND_REANALYSIS",
    "AnalysisService",
    "CancellationStateCheckError",
    "_RESUME_RESET_WINDOW_SECONDS",
]

TASK_KIND_ANALYSIS = "analysis"
TASK_KIND_REANALYSIS = "reanalysis"


# 说明: TaskClaimMixin 经由 StageOrchestratorMixin 继承链一并混入
class AnalysisService(StageOrchestratorMixin, TerminalStateFallbackMixin):
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

    def _build_reanalysis_skip_stages(self, request: ReanalyzeRequest | None) -> dict[str, bool]:
        if request is None:
            return {
                "skip_preprocess": False,
                "skip_annotate": False,
                "skip_aggregate": False,
                "skip_linguistic": False,
                "skip_topic_model": False,
                "skip_diagnose": False,
            }
        all_force_false = (
            not request.force_preprocess
            and not request.force_annotate
            and not request.force_aggregate
            and not request.force_topic_model
            and not request.force_diagnose
            and not request.force_linguistic
        )
        if all_force_false:
            return {
                "skip_preprocess": False,
                "skip_annotate": False,
                "skip_aggregate": False,
                "skip_linguistic": False,
                "skip_topic_model": False,
                "skip_diagnose": False,
            }
        return {
            "skip_preprocess": not request.force_preprocess,
            "skip_annotate": not request.force_annotate,
            "skip_aggregate": not request.force_aggregate,
            "skip_linguistic": not request.force_linguistic,
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

    async def recover_pending_tasks(self) -> tuple[int, int]:
        """启动时恢复 pending 任务并隔离单任务失败，返回已调度和已取消数量"""
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

    def _schedule_task_execution(
        self,
        task_id: str,
        novel: dict,
        task_kind: str,
        request: ReanalyzeRequest | None,
    ) -> None:
        """
        2026-08-20 统一调度入口，直接创建执行协程，消除冗余跳转层
        根据任务类型构建参数后直接调用核心执行逻辑
        """
        # 根据任务类型构建执行参数
        if task_kind == TASK_KIND_ANALYSIS:
            # 分析任务：检查阶段完成状态，支持断点续传
            def skip_stages_builder(session: Session, run_id: str) -> dict[str, bool]:
                return self.env_initializer.check_stage_completion_status(session, run_id)

            def pre_execute_hook(novel_id: str, skip_stages: dict[str, bool]) -> bool:
                if self._check_all_stages_completed(skip_stages):
                    self._handle_already_completed(task_id, novel_id, None)
                    return True
                return False

            num_topics = settings.topic_model.num_topics
            log_prefix = "Analysis"
            hook = pre_execute_hook

        elif task_kind == TASK_KIND_REANALYSIS:
            # 重分析任务：根据请求参数决定重跑哪些阶段
            skip_stages = self._build_reanalysis_skip_stages(request)
            logger.info(f"Reanalysis skip_stages: {skip_stages}")

            def skip_stages_builder(session: Session, run_id: str) -> dict[str, bool]:
                return skip_stages

            num_topics = request.num_topics if request else settings.topic_model.num_topics
            log_prefix = "Reanalysis"
            hook = None

        else:
            raise ValueError(f"任务 {task_id} 的 task_kind 非法: {task_kind}")

        # 直接创建并调度执行协程
        task = asyncio.create_task(
            self._run_analysis_core(
                task_id=task_id,
                novel=novel,
                skip_stages_builder=skip_stages_builder,
                num_topics=num_topics,
                log_prefix=log_prefix,
                pre_execute_hook=hook,
            )
        )
        self.task_manager.store_asyncio_task(task_id, task)

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
                # 领取前取消也要发送 SSE 终态，避免客户端只能轮询状态
                await event_manager.send(
                    task_id=task_id,
                    event_type=StreamMessageType.task_cancelled.value,
                    data={"stage": "cancelled", "message": "任务已取消"},
                )
                return
            if claim_result == "skipped":
                logger.info(f"Task {task_id} execution claim skipped because another state transition won the DB truth")
                # 跳过执行时清除本进程缓存，避免残留心跳覆盖真实 owner
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

            if self._is_cancelled(task_id):
                # 成功收口前收到取消时仍需落 DB 终态并发送事件
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
                # 环境初始化失败时也要写入 DB 失败终态
                self.novel_service.update_task_status(task_id, "failed")
                self.task_manager.complete_task(task_id, success=False, error=str(e))
                self._write_failure_to_db(task_id, str(e))
        finally:
            if analysis_logger:
                analysis_logger.close()
            if session:
                session.close()
