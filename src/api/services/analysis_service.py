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
        max_chars: int = 2000,
        overlap: int = 200,
    ) -> None:
        task_id = bus.task_id

        if self._is_cancelled(task_id):
            await self.error_handler.handle_cancel(task_id, novel_id, session, run_id, analysis_logger, bus)
            return

        # ── 预处理 ──
        if not skip_stages["skip_preprocess"]:
            await bus.emit_stage_start(
                "preprocess", message="开始预处理", percent=settings.analysis.progress.preprocess.start
            )

            await self.stage_executor.run_preprocess(
                source_path, run_id, session, max_chars, overlap, self._make_stage_emitter(bus, "preprocess")
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
            except Exception:
                pass

            await bus.emit_stage_start(
                "annotate",
                message="开始标注分析",
                percent=settings.analysis.progress.annotate.start,
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
                "aggregate", message="开始数据聚合", percent=settings.analysis.progress.aggregate.start
            )

            await self.stage_executor.run_aggregate(run_id, session, self._make_stage_emitter(bus, "aggregate"))
            await bus.emit_stage_complete("aggregate")

        if self._is_cancelled(task_id):
            await self.error_handler.handle_cancel(task_id, novel_id, session, run_id, analysis_logger, bus)
            return

        # ── 主题建模 ──
        if not skip_stages["skip_topic_model"]:
            await bus.emit_stage_start(
                "topic-model", message="开始主题建模", percent=settings.analysis.progress.topic_model.start
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
                "diagnose", message="开始诊断报告", percent=settings.analysis.progress.diagnose.start
            )

            await self.stage_executor.run_diagnose(
                run_id, session, analysis_logger, self._make_stage_emitter(bus, "diagnose")
            )
            await bus.emit_stage_complete("diagnose")

    def _is_cancelled(self, task_id: str) -> bool:
        """
        检查任务是否已被请求取消

        创建时间: 2025-03-11
        创建者: TraeAI
        任务: 分析服务

        修改时间: 2026-04-19
        修改者: TraeAI
        任务: task-5-db-driven-cancel
        修改内容: DB 优先取消机制，同时检查内存 cancel_event（加速缓存）和 DB cancel_requested（持久化真相）

        返回:
            True 表示任务已请求取消，False 表示未取消
        """
        # 优先检查内存缓存（加速响应）
        task_info = self.task_manager.get_task(task_id)
        if task_info and task_info.cancel_event and task_info.cancel_event.is_set():
            return True

        # DB 检查：查询 cancel_requested 字段
        if self.session_factory:
            try:
                from src.storage.id_mapping import TaskIDNotFoundError, task_id_to_run_id
                from src.storage.repositories import RunRepository

                db_session = self.session_factory.get_session()
                with db_session:
                    # 使用底层 SQLAlchemy Session
                    sql_session = db_session.connection
                    try:
                        run_id = task_id_to_run_id(task_id, sql_session)
                        run_repo = RunRepository(sql_session)
                        run = run_repo.get_run(run_id)
                        if run and run.get("cancel_requested", False):
                            return True
                    except (TaskIDNotFoundError, ValueError):
                        # 不存在对应 run 记录，忽略
                        pass
            except Exception as e:
                logger.warning(f"Failed to check DB cancel_requested for task {task_id}: {e}")

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

    def _schedule_analysis_task(self, task_id: str, novel: dict, request: AnalyzeRequest | None = None) -> None:
        """
        安排分析协程并记录 asyncio.Task 引用。

        创建时间: 2026-04-19
        创建者: Codex (GPT-5)
        任务: task-api-decouple
        说明: 统一 create/resume 两条路径的协程调度，避免重复代码。
        """
        task = asyncio.create_task(self._run_analysis(task_id, novel, request))
        self.task_manager.store_asyncio_task(task_id, task)

    async def create_task_and_start(self, novel_id: str) -> str:
        """
        创建新任务并立即启动分析。

        创建时间: 2026-04-19
        创建者: Codex (GPT-5)
        任务: task-api-decouple
        说明: 只负责“创建+启动”，不做复用/猜测行为。
        """
        novel = self.novel_service.get_novel(novel_id)
        task_id = self.novel_service.create_task(novel_id)
        self.task_manager.create_task(task_id, novel_id)
        self._schedule_analysis_task(task_id, novel)
        return task_id

    async def resume_task(self, novel_id: str, task_id: str) -> str:
        """
        继续执行 pending/failed 任务。

        创建时间: 2026-04-19
        创建者: Codex (GPT-5)
        任务: task-api-decouple
        说明: 只负责“继续已有任务”，不创建新任务。
        """
        novel = self.novel_service.get_novel(novel_id)
        task = self.novel_service.get_task(task_id)

        if task.get("novel_id") != novel_id:
            raise ValueError(f"任务 {task_id} 不属于小说 {novel_id}")

        status = task.get("status", "")
        if status not in ("pending", "failed"):
            raise ValueError(f"仅支持继续 pending/failed 任务，当前状态为 {status}")

        task_info = self.task_manager.get_task(task_id)
        if task_info and task_info.asyncio_task and not task_info.asyncio_task.done():
            raise ValueError(f"任务 {task_id} 正在运行，不能重复继续")

        if task_info is None:
            self.task_manager.create_task(task_id, novel_id)
        else:
            # 重置内存态，避免沿用上一次失败任务的残留信息。
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
                llm_outputs=[],
                completed_at=None,
            )

        self._schedule_analysis_task(task_id, novel, AnalyzeRequest(task_id=task_id))
        return task_id

    async def start_analysis(self, novel_id: str, request: AnalyzeRequest | None = None) -> str:
        """
        兼容入口：保留旧方法名，语义收敛为“创建新任务并启动”。

        修改时间: 2026-04-19
        修改者: Codex (GPT-5)
        任务: task-api-decouple
        修改内容: 移除 create/reuse/resume 混合逻辑，改为仅创建新任务。
        """
        if request and request.task_id:
            raise AnalysisError("analyze 接口不再支持 task_id 续跑，请改用 /tasks/{task_id}/resume")
        return await self.create_task_and_start(novel_id)

    async def start_reanalysis(self, novel_id: str, request: ReanalyzeRequest | None = None) -> str:
        novel = self.novel_service.get_novel(novel_id)

        task_id = self.novel_service.create_task(novel_id)
        self.task_manager.create_task(task_id, novel_id)

        task = asyncio.create_task(self._run_reanalysis(task_id, novel, request))
        self.task_manager.store_asyncio_task(task_id, task)

        return task_id

    async def _run_analysis(self, task_id: str, novel: dict, request: AnalyzeRequest | None) -> None:
        """
        执行分析任务

        修改时间: 2026-04-14
        修改者: TraeAI
        任务: refactor-analysis-service-duplicate-code
        修改内容: 提取公共逻辑到 _run_analysis_core 方法
        """
        num_topics = settings.topic_model.single_book.num_topics
        max_chars = settings.chunking.max_chars
        overlap = settings.chunking.overlap

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
            max_chars=max_chars,
            overlap=overlap,
            pre_execute_hook=pre_execute_hook,
        )

    async def _run_reanalysis(self, task_id: str, novel: dict, request: ReanalyzeRequest | None) -> None:
        """
        执行重新分析任务

        修改时间: 2026-04-14
        修改者: TraeAI
        任务: refactor-analysis-service-duplicate-code
        修改内容: 提取公共逻辑到 _run_analysis_core 方法
        """
        skip_stages = self._build_reanalysis_skip_stages(request)
        logger.info(f"Reanalysis skip_stages: {skip_stages}")
        num_topics = request.num_topics if request else settings.topic_model.single_book.num_topics

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
        max_chars: int | None = None,
        overlap: int | None = None,
    ) -> None:
        """
        调用 _execute_analysis_stages，根据条件添加 max_chars/overlap 参数。

        创建时间: 2026-04-17
        创建者: TraeAI
        任务: refactor/split-provider-bundle-renderer
        说明: 消除 _run_analysis_core 中重复的 _execute_analysis_stages 调用逻辑。
        """
        if max_chars is not None and overlap is not None:
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
        else:
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
        max_chars: int | None = None,
        overlap: int | None = None,
        pre_execute_hook: Callable[[str, dict[str, bool]], bool] | None = None,
    ) -> None:
        """
        统一的分析执行核心逻辑

        创建时间: 2026-04-14
        创建者: TraeAI
        任务: refactor-analysis-service-duplicate-code
        说明: 封装 _run_analysis 和 _run_reanalysis 的公共逻辑

        Args:
            task_id: 任务ID
            novel: 小说信息字典
            skip_stages_builder: 构建 skip_stages 的函数
            num_topics: 主题数量
            log_prefix: 日志前缀
            max_chars: 分块最大字符数
            overlap: 分块重叠字符数
            pre_execute_hook: 执行前的钩子函数，返回 True 表示跳过执行
        """
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
                max_chars=max_chars,
                overlap=overlap,
            )

            if self._is_cancelled(task_id):
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
                    log_prefix=log_prefix,
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
        """
        获取任务状态（DB-only 查询）。

        创建时间: 2026-04-19
        创建者: AI Assistant
        任务: 统一任务状态查询为 DB-only
        说明: 从数据库查询任务状态，不再依赖内存中的 TaskManager。
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
        获取小说的所有任务（DB-only 查询）。

        创建时间: 2026-04-19
        创建者: AI Assistant
        任务: 统一任务状态查询为 DB-only
        说明: 从数据库查询小说的任务列表，不再依赖内存中的 TaskManager。
        """
        tasks = self.novel_service.get_tasks_by_novel(novel_id)
        return tasks
