"""
分析服务类

创建时间: 2025-03-11
创建者: TraeAI
任务: 分析服务

修改时间: 2026-04-09
创建者: GLM-5
任务: refactor/sse-unified-event-bus
修改内容:
- 使用 AnalysisEventBus 替代 ProgressBroadcaster + 闭包回调
- 所有 SSE 事件走 EventBus 统一发送，不再有双路径
- 阶段级事件由 service 层 emit，内部进度由 workflow 层通过 emitter emit
- error_handler 使用 EventBus 发送终止事件
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable
from pathlib import Path

from loguru import logger
from sqlalchemy.orm import Session

from src.api.exceptions import AnalysisError
from src.api.models.events import AnalysisEventBus, StreamEvent
from src.api.models.requests import AnalyzeRequest, ReanalyzeRequest
from src.api.models.responses import TaskStatus
from src.api.services.analysis.environment_initializer import EnvironmentInitializer
from src.api.services.analysis.error_handler import AnalysisErrorHandler
from src.api.services.analysis.stage_executor import StageExecutor
from src.api.services.novel_service import NovelService
from src.api.services.task_manager import TaskManager
from src.config import settings
from src.config.analysis_logger import AnalysisLogger
from src.storage.session import SessionFactory


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
                # 构建新事件对象，避免修改原始 event
                event = StreamEvent(
                    action=event.action,
                    stage=stage,
                    sub_stage=event.sub_stage,
                    chunk_id=event.chunk_id,
                    current=event.current,
                    total=event.total,
                    percent=event.percent,
                    content=event.content,
                    message=event.message,
                )
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
        max_chars: int = 2000,
        overlap: int = 200,
    ) -> None:
        task_id = bus.task_id

        if self._is_cancelled(task_id):
            await self.error_handler.handle_cancel(task_id, novel_id, session, run_id, analysis_logger, bus)
            return

        # ── 预处理 ──
        if not skip_stages["skip_preprocess"]:
            await bus.emit_stage_start("preprocess", message="开始预处理", percent=settings.analysis.progress.preprocess.start)

            await self.stage_executor.run_preprocess(
                source_path, run_id, session, max_chars, overlap, self._make_stage_emitter(bus, "preprocess")
            )
            await bus.emit_stage_complete("preprocess")

        if self._is_cancelled(task_id):
            await self.error_handler.handle_cancel(task_id, novel_id, session, run_id, analysis_logger, bus)
            return

        # ── 标注 ──
        if not skip_stages["skip_annotate"]:
            await bus.emit_stage_start("annotate", message="开始标注分析", percent=settings.analysis.progress.annotate.start)

            await self.stage_executor.run_annotate(
                run_id, session, novel_id, analysis_logger, novel_title,
                emitter=self._make_stage_emitter(bus, "annotate"),
                is_cancelled=lambda: self._is_cancelled(task_id),
            )
            await bus.emit_stage_complete("annotate")

        if self._is_cancelled(task_id):
            await self.error_handler.handle_cancel(task_id, novel_id, session, run_id, analysis_logger, bus)
            return

        # ── 聚合 ──
        if not skip_stages["skip_aggregate"]:
            await bus.emit_stage_start("aggregate", message="开始数据聚合", percent=settings.analysis.progress.aggregate.start)

            await self.stage_executor.run_aggregate(
                run_id, session, self._make_stage_emitter(bus, "aggregate")
            )
            await bus.emit_stage_complete("aggregate")

        if self._is_cancelled(task_id):
            await self.error_handler.handle_cancel(task_id, novel_id, session, run_id, analysis_logger, bus)
            return

        # ── 主题建模 ──
        if not skip_stages["skip_topic_model"]:
            await bus.emit_stage_start("topic-model", message="开始主题建模", percent=settings.analysis.progress.topic_model.start)

            await self.stage_executor.run_topic_model(
                run_id, session, num_topics, self._make_stage_emitter(bus, "topic-model")
            )
            await bus.emit_stage_complete("topic-model")

        if self._is_cancelled(task_id):
            await self.error_handler.handle_cancel(task_id, novel_id, session, run_id, analysis_logger, bus)
            return

        # ── 诊断 ──
        if not skip_stages["skip_diagnose"]:
            await bus.emit_stage_start("diagnose", message="开始诊断报告", percent=settings.analysis.progress.diagnose.start)

            await self.stage_executor.run_diagnose(
                run_id, session, analysis_logger, self._make_stage_emitter(bus, "diagnose")
            )
            await bus.emit_stage_complete("diagnose")

    def _is_cancelled(self, task_id: str) -> bool:
        """检查任务是否已被请求取消"""
        task_info = self.task_manager.get_task(task_id)
        if task_info and task_info.cancel_event and task_info.cancel_event.is_set():
            return True
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
        logger.info(f"Task {task_id} already completed, no action needed")
        self.novel_service.update_task_status(task_id, "completed")
        self.task_manager.complete_task(task_id, success=True)
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

    def _is_zombie_task(self, task_id: str) -> bool:
        """检查 running 状态的任务是否为僵尸任务（服务重启后遗留的无效 running 状态）"""
        task_info = self.task_manager.get_task(task_id)
        if task_info is None:
            # TaskManager 中无记录，说明是上次进程遗留的僵尸任务
            return True
        if task_info.asyncio_task is None or task_info.asyncio_task.done():
            # asyncio task 不存在或已完成，但状态仍为 running → 僵尸
            return True
        return False

    async def start_analysis(self, novel_id: str, request: AnalyzeRequest | None = None) -> str:
        novel = self.novel_service.get_novel(novel_id)

        if request and request.task_id:
            specified_task_id = request.task_id
            specified_task = self.novel_service.get_task(specified_task_id)
            if specified_task.get("novel_id") != novel_id:
                raise AnalysisError(f"任务 {specified_task_id} 不属于小说 {novel_id}")
            logger.info(f"Using specified task_id: {specified_task_id}")

            if specified_task.get("status") in ("pending", "failed"):
                task = asyncio.create_task(self._run_analysis(specified_task_id, novel, request))
                self.task_manager.store_asyncio_task(specified_task_id, task)
            elif specified_task.get("status") == "running" and self._is_zombie_task(specified_task_id):
                logger.warning(f"Detected zombie task {specified_task_id}, restarting analysis")
                self.task_manager.create_task(specified_task_id, novel_id)
                task = asyncio.create_task(self._run_analysis(specified_task_id, novel, request))
                self.task_manager.store_asyncio_task(specified_task_id, task)

            return specified_task_id

        existing_task, error = self.novel_service.get_single_valid_task(novel_id)

        if error:
            raise AnalysisError(error)

        if existing_task:
            task_id = existing_task["task_id"]
            status = existing_task.get("status", "unknown")
            logger.info(f"Found existing task {task_id} (status={status}) for novel {novel_id}, reusing it")

            if status == "pending":
                task = asyncio.create_task(self._run_analysis(task_id, novel, request))
                self.task_manager.store_asyncio_task(task_id, task)
            elif status == "running" and self._is_zombie_task(task_id):
                logger.warning(f"Detected zombie task {task_id}, restarting analysis")
                self.task_manager.create_task(task_id, novel_id)
                task = asyncio.create_task(self._run_analysis(task_id, novel, request))
                self.task_manager.store_asyncio_task(task_id, task)

            return task_id

        task_id = self.novel_service.create_task(novel_id)
        self.task_manager.create_task(task_id, novel_id)

        task = asyncio.create_task(self._run_analysis(task_id, novel, request))
        self.task_manager.store_asyncio_task(task_id, task)

        return task_id

    async def start_reanalysis(self, novel_id: str, request: ReanalyzeRequest | None = None) -> str:
        novel = self.novel_service.get_novel(novel_id)

        task_id = self.novel_service.create_task(novel_id)
        self.task_manager.create_task(task_id, novel_id)

        task = asyncio.create_task(self._run_reanalysis(task_id, novel, request))
        self.task_manager.store_asyncio_task(task_id, task)

        return task_id

    async def _run_analysis(self, task_id: str, novel: dict, request: AnalyzeRequest | None) -> None:
        start_time = time.time()
        analysis_logger: AnalysisLogger | None = None
        session: Session | None = None
        run_id: str | None = None
        bus: AnalysisEventBus | None = None
        try:
            self.task_manager.update_task(task_id, cancel_event=asyncio.Event())

            (
                novel_id,
                source_path,
                novel_title,
                session,
                analysis_logger,
                run_id,
            ) = self.env_initializer.init_analysis_environment(task_id, novel)

            num_topics = settings.topic_model.single_book.num_topics
            max_chars = settings.chunking.max_chars
            overlap = settings.chunking.overlap

            skip_stages = self.env_initializer.check_stage_completion_status(session, run_id)

            if self._check_all_stages_completed(skip_stages):
                self._handle_already_completed(task_id, novel_id, analysis_logger)
                return

            self.task_manager.update_task(task_id, status=TaskStatus.RUNNING, stage="preprocess", progress=0)

            # 创建 EventBus：所有 SSE 事件的统一发送口
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
                max_chars=max_chars,
                overlap=overlap,
            )

            if self._is_cancelled(task_id):
                return

            elapsed = time.time() - start_time
            await self.error_handler.handle_success(
                task_id, novel_id, elapsed, analysis_logger, session, run_id, bus=bus, log_prefix="Analysis"
            )

        except asyncio.CancelledError:
            logger.info(f"Task {task_id} was cancelled via asyncio.Task.cancel()")
            if session and run_id:
                await self.error_handler.handle_cancel(
                    task_id, novel.get("novel_id", "unknown"), session, run_id, analysis_logger, bus=bus
                )
        except Exception as e:
            elapsed = time.time() - start_time
            if self._is_cancelled(task_id) and session and run_id:
                await self.error_handler.handle_cancel(
                    task_id, novel.get("novel_id", "unknown"), session, run_id, analysis_logger, bus=bus
                )
            elif session and run_id:
                await self.error_handler.handle_failure(
                    task_id, novel.get("novel_id", "unknown"), elapsed, e, analysis_logger, session, run_id, bus=bus
                )
            else:
                self.novel_service.update_task_status(task_id, "failed")
                self.task_manager.complete_task(task_id, success=False, error=str(e))
        finally:
            if analysis_logger:
                analysis_logger.close()
            if session:
                session.close()

    async def _run_reanalysis(self, task_id: str, novel: dict, request: ReanalyzeRequest | None) -> None:
        start_time = time.time()
        analysis_logger: AnalysisLogger | None = None
        session: Session | None = None
        run_id: str | None = None
        bus: AnalysisEventBus | None = None
        try:
            self.task_manager.update_task(task_id, cancel_event=asyncio.Event())

            (
                novel_id,
                source_path,
                novel_title,
                session,
                analysis_logger,
                run_id,
            ) = self.env_initializer.init_analysis_environment(task_id, novel)

            skip_stages = self._build_reanalysis_skip_stages(request)
            logger.info(f"Reanalysis skip_stages: {skip_stages}")
            num_topics = request.num_topics if request else settings.topic_model.single_book.num_topics

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
                return

            elapsed = time.time() - start_time
            await self.error_handler.handle_success(
                task_id, novel_id, elapsed, analysis_logger, session, run_id, bus=bus, log_prefix="Reanalysis"
            )

        except asyncio.CancelledError:
            logger.info(f"Reanalysis task {task_id} was cancelled via asyncio.Task.cancel()")
            if session and run_id:
                await self.error_handler.handle_cancel(
                    task_id, novel.get("novel_id", "unknown"), session, run_id, analysis_logger, bus=bus
                )
        except Exception as e:
            elapsed = time.time() - start_time
            if self._is_cancelled(task_id) and session and run_id:
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
                    log_prefix="Reanalysis",
                )
            else:
                self.novel_service.update_task_status(task_id, "failed")
                self.task_manager.complete_task(task_id, success=False, error=str(e))
        finally:
            if analysis_logger:
                analysis_logger.close()
            if session:
                session.close()

    def get_task_status(self, task_id: str) -> dict | None:
        task = self.task_manager.get_task(task_id)
        if not task:
            return None
        return {
            "task_id": task.task_id,
            "novel_id": task.novel_id,
            "status": task.status,
            "progress": task.progress,
            "stage": task.stage,
            "error": task.error,
            "started_at": task.started_at,
            "completed_at": task.completed_at,
        }

    def get_novel_tasks(self, novel_id: str) -> list[dict]:
        tasks = self.task_manager.get_tasks_by_novel(novel_id)
        return [
            {
                "task_id": t.task_id,
                "novel_id": t.novel_id,
                "status": t.status,
                "progress": t.progress,
                "stage": t.stage,
                "error": t.error,
                "started_at": t.started_at,
                "completed_at": t.completed_at,
            }
            for t in tasks
        ]
