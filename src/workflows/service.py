"""
分析服务类

说明: 编排的公开入口——建任务、跑阶段、恢复、重分析。阶段编排、取消检查、终态兜底
分别在 src/workflows/analysis/ 下，队列运行时由 src/work 提供（本层向下调用）。
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Callable

from loguru import logger

from src.config import settings
from src.event_bus import EVENT_BUS, EventBus
from src.storage import Storage, get_storage_factory
from src.storage.task_status import TaskStatus
from src.work.task_manager import TaskManager
from src.workflows.analysis.environment_initializer import EnvironmentInitializer
from src.workflows.analysis.error_handler import AnalysisErrorHandler, TerminalStateFallbackMixin
from src.workflows.analysis.stage_executor import StageExecutor
from src.workflows.analysis.stage_orchestrator import StageOrchestratorMixin
from src.workflows.progress import AnalysisEventBus
from src.workflows.schemas import ReanalyzeRequest
from src.workflows.tasks import TaskService

__all__ = [
    "TASK_KIND_ANALYSIS",
    "TASK_KIND_REANALYSIS",
    "AnalysisService",
]
TASK_KIND_ANALYSIS = "analysis"
TASK_KIND_REANALYSIS = "reanalysis"


class AnalysisService(StageOrchestratorMixin, TerminalStateFallbackMixin):
    def __init__(
        self,
        task_service: TaskService,
        task_manager: TaskManager,
        session_factory: Callable[[], Storage] | None = None,
        bus: EventBus = EVENT_BUS,
    ):
        self.task_service = task_service
        self.task_manager = task_manager
        self.session_factory = session_factory or get_storage_factory()
        self.env_initializer = EnvironmentInitializer(self.session_factory)
        self.bus = bus
        self.stage_executor = StageExecutor(bus)
        self.error_handler = AnalysisErrorHandler(task_service=task_service, task_manager=task_manager)

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
            and (not request.force_annotate)
            and (not request.force_aggregate)
            and (not request.force_topic_model)
            and (not request.force_diagnose)
            and (not request.force_linguistic)
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

    async def recover_pending_tasks(self) -> tuple[int, int]:
        "按正式产出恢复待执行任务"
        count = 0
        for run in self.session_factory().runs.get_pending_tasks():
            try:
                await self.resume_task(run["novel_id"], run["task_id"])
            except Exception:
                logger.exception("恢复待执行任务失败: {}", run["task_id"])
                continue
            count += 1
        return count, 0

    def _schedule_task_execution(
        self, task_id: str, novel: dict, task_kind: str, request: ReanalyzeRequest | None, *, resume: bool = False
    ) -> None:
        """
        统一调度入口：按任务类型构建参数后直接创建执行协程
        """
        skip_states: dict[str, str] = {}

        def record_skip_states(skips: dict[str, bool], excluded: dict[str, bool] | None = None) -> dict[str, bool]:
            for key, skip in skips.items():
                if skip:
                    stage = key.removeprefix("skip_").replace("_", "-")
                    skip_states[stage] = "not_in_scope" if excluded and excluded[key] else "completed"
                    if (stage == "linguistic" and not settings.linguistic.ltp.enabled
                        and not (excluded and excluded[key])):
                        skip_states[stage] = "disabled"
            return skips

        if task_kind == TASK_KIND_ANALYSIS:

            def skip_stages_builder(session: Storage, run_id: str) -> dict[str, bool]:
                return record_skip_states(self.env_initializer.check_stage_completion_status(session, run_id))

            def pre_execute_hook(novel_id: str, skip_stages: dict[str, bool]) -> bool:
                if self._check_all_stages_completed(skip_stages):
                    self._handle_already_completed(task_id, novel_id, None)
                    return True
                return False

            num_topics = settings.topic_model.num_topics
            log_prefix = "Analysis"
            hook = pre_execute_hook
        elif task_kind == TASK_KIND_REANALYSIS:
            skip_stages = self._build_reanalysis_skip_stages(request)
            logger.info(f"Reanalysis skip_stages: {skip_stages}")

            def skip_stages_builder(session: Storage, run_id: str) -> dict[str, bool]:
                if not resume:
                    return record_skip_states(dict(skip_stages), skip_stages)
                completed = self.env_initializer.check_stage_completion_status(session, run_id)
                return record_skip_states(
                    {name: skip or completed[name] for name, skip in skip_stages.items()}, skip_stages
                )

            num_topics = request.num_topics if request else settings.topic_model.num_topics
            log_prefix = "Reanalysis"
            hook = None
        else:
            raise ValueError(f"任务 {task_id} 的 task_kind 非法: {task_kind}")
        task = asyncio.create_task(
            self._run_analysis_core(
                task_id=task_id,
                novel=novel,
                skip_stages_builder=skip_stages_builder,
                num_topics=num_topics,
                log_prefix=log_prefix,
                pre_execute_hook=hook,
                skip_states=skip_states,
            )
        )
        self.task_manager.store_asyncio_task(task_id, task)

    async def create_task_and_start(self, novel_id: str) -> str:
        """
        创建新任务并立即启动分析

        说明: 只负责“创建+启动”，不做复用/猜测行为
        """
        novel = self.task_service.get_novel(novel_id)
        task_id = self.task_service.create_task(novel_id)
        self.task_manager.create_task(task_id, novel_id)
        task = self.task_service.get_task(task_id)
        await AnalysisEventBus(task_id, run_id=task["run_id"], bus=self.bus).notify(
            "task_state", {"status": "pending"}
        )
        self._schedule_task_execution(task_id, novel, TASK_KIND_ANALYSIS, None)
        return task_id

    async def resume_task(self, novel_id: str, task_id: str) -> str:
        """
        继续执行 pending/failed/cancelled 任务

        说明: 只负责“继续已有任务”，不创建新任务
        """
        novel = self.task_service.get_novel(novel_id)
        task = self.task_service.get_task(task_id)
        if task.get("novel_id") != novel_id:
            raise ValueError(f"任务 {task_id} 不属于小说 {novel_id}")
        status = task.get("status", "")
        if status not in ("pending", "failed", "cancelled"):
            raise ValueError(f"仅支持继续 pending/failed/cancelled 任务，当前状态为 {status}")
        task_info = self.task_manager.get_task(task_id)
        if task_info and task_info.asyncio_task and (not task_info.asyncio_task.done()):
            raise ValueError(f"任务 {task_id} 正在运行，不能重复继续")
        if task_info is None:
            self.task_manager.create_task(task_id, novel_id)
        self.task_manager.update_task(task_id, status=TaskStatus.PENDING)
        notifier = AnalysisEventBus(task_id, run_id=task["run_id"], bus=self.bus)
        await notifier.notify("task_reset", {"status": "pending"})
        self._schedule_task_execution(task_id, novel, TASK_KIND_ANALYSIS, None, resume=True)
        return task_id

    async def start_reanalysis(self, novel_id: str, request: ReanalyzeRequest | None = None) -> str:
        novel = self.task_service.get_novel(novel_id)
        task_id = self.task_service.create_task(novel_id)
        self.task_manager.create_task(task_id, novel_id)
        task = self.task_service.get_task(task_id)
        await AnalysisEventBus(task_id, run_id=task["run_id"], bus=self.bus).notify(
            "task_state", {"status": "pending"}
        )
        self._schedule_task_execution(task_id, novel, TASK_KIND_REANALYSIS, request)
        return task_id

    async def _run_analysis_core(
        self,
        task_id: str,
        novel: dict,
        skip_stages_builder: Callable[[Storage, str], dict[str, bool]],
        num_topics: int,
        log_prefix: str = "Analysis",
        pre_execute_hook: Callable[[str, dict[str, bool]], bool] | None = None,
        skip_states: dict[str, str] | None = None,
    ) -> None:
        "领取任务并执行正式分析链"
        start = time.time()
        analysis_logger = None
        session = None
        run_id = None
        bus = None
        try:
            if self._prepare_task_execution_claim(task_id) != "claimed":
                return
            novel_id, source_path, title, session, analysis_logger, run_id = (
                self.env_initializer.init_analysis_environment(task_id, novel)
            )
            bus = AnalysisEventBus(task_id, run_id=run_id, bus=self.bus)
            await bus.notify("task_state", {"status": "running"})
            skip_stages = skip_stages_builder(session, run_id)
            if pre_execute_hook and pre_execute_hook(novel_id, skip_stages):
                await bus.emit_task_complete()
                return
            await self._execute_analysis_stages(
                bus, session, run_id, source_path, novel_id, title, analysis_logger, skip_stages, num_topics,
                skip_states=skip_states,
            )
            await self.error_handler.handle_success(
                task_id, novel_id, time.time() - start, analysis_logger, session, run_id, bus=bus, log_prefix=log_prefix
            )
        except asyncio.CancelledError:
            if session and run_id:
                await self.error_handler.handle_cancel(
                    task_id, novel["novel_id"], session, run_id, analysis_logger, bus=bus
                )
            else:
                self.task_manager.cancel_completed_task(task_id)
                task = self.task_service.get_task(task_id)
                notifier = AnalysisEventBus(task_id, run_id=task["run_id"], bus=self.bus)
                await notifier.emit_task_cancelled()
        except Exception as exc:
            if session and run_id:
                await self.error_handler.handle_failure(
                    task_id,
                    novel["novel_id"],
                    time.time() - start,
                    exc,
                    analysis_logger,
                    session,
                    run_id,
                    bus=bus,
                    log_prefix=log_prefix,
                )
            else:
                self._write_failure_to_db(task_id, str(exc))
                task = self.task_service.get_task(task_id)
                notifier = AnalysisEventBus(task_id, run_id=task["run_id"], bus=self.bus)
                await notifier.emit_task_error(str(exc))
        finally:
            if analysis_logger:
                analysis_logger.close()
            if run_id:
                self.bus.release_run(run_id)
