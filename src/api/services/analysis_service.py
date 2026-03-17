"""
分析服务类

创建时间: 2025-03-11
创建者: TraeAI
任务: 分析服务

修改时间: 2026-03-14
修改者: TraeAI
任务: services 使用 Repository 模式重构
修改内容:
- 添加 session_factory 参数，支持 Repository 模式
- 使用 RunRepository 创建和更新运行记录
- 使用 run_id 替代 task_id 作为数据库标识

修改时间: 2026-03-15
修改者: TraeAI
任务: storage-layer-decoupling
修改内容: 移除向后兼容代码，只使用 run_id/session 参数

修改时间: 2026-03-15
修改者: TraeAI
任务: storage-layer-decoupling
修改内容: 移除 operations 导入，使用 Repository 替代
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional
import asyncio
import time

from loguru import logger
from sqlalchemy.orm import Session

from src.config import settings
from src.config.analysis_logger import AnalysisLogger
from src.api.models.requests import AnalyzeRequest, ReanalyzeRequest
from src.api.models.responses import TaskStatus
from src.api.services.task_manager import TaskManager
from src.api.services.novel_service import NovelService
from src.api.exceptions import AnalysisError
from src.storage.session import SessionFactory
from src.storage.repositories import RunRepository, ChunkRepository, AnnotationRepository, StatsRepository


class AnalysisService:
    def __init__(
        self,
        novel_service: NovelService,
        task_manager: TaskManager,
        session_factory: SessionFactory | None = None,
    ):
        self.novel_service = novel_service
        self.task_manager = task_manager
        self.session_factory = session_factory or SessionFactory(novel_service.upload_dir)

    async def start_analysis(self, novel_id: str, request: Optional[AnalyzeRequest] = None) -> str:
        novel = self.novel_service.get_novel(novel_id)

        if request and request.task_id:
            specified_task_id = request.task_id
            specified_task = self.novel_service.get_task(specified_task_id)
            if specified_task.get("novel_id") != novel_id:
                raise AnalysisError(f"任务 {specified_task_id} 不属于小说 {novel_id}")
            logger.info(f"Using specified task_id: {specified_task_id}")

            if specified_task.get("status") == "pending":
                asyncio.create_task(self._run_analysis(specified_task_id, novel, request))

            return specified_task_id

        existing_task, error = self.novel_service.get_single_valid_task(novel_id)

        if error:
            raise AnalysisError(error)

        if existing_task:
            task_id = existing_task["task_id"]
            status = existing_task.get("status", "unknown")
            logger.info(f"Found existing task {task_id} (status={status}) for novel {novel_id}, reusing it")

            if status == "pending":
                asyncio.create_task(self._run_analysis(task_id, novel, request))

            return task_id

        task_id = self.novel_service.create_task(novel_id)
        self.task_manager.create_task(task_id, novel_id)

        asyncio.create_task(self._run_analysis(task_id, novel, request))

        return task_id

    async def start_reanalysis(self, novel_id: str, request: Optional[ReanalyzeRequest] = None) -> str:
        novel = self.novel_service.get_novel(novel_id)

        task_id = self.novel_service.create_task(novel_id)
        self.task_manager.create_task(task_id, novel_id)

        asyncio.create_task(self._run_reanalysis(task_id, novel, request))

        return task_id

    def _init_analysis_environment(
        self,
        task_id: str,
        novel: dict,
    ) -> tuple[str, Path, str | None, Session, AnalysisLogger, str]:
        """
        初始化分析环境

        返回: (novel_id, source_path, novel_title, session, analysis_logger, run_id)

        修改时间: 2026-03-15
        修改者: TraeAI
        任务: decouple-migration-progress-evaluation
        修改内容: 使用 SessionFactory 替代 connect_db/create_tables

        修改时间: 2026-03-15
        修改者: TraeAI
        任务: postgresql-migration
        修改内容: 移除 INSERT OR REPLACE SQLite 方言，改用 StatsRepository
        """
        novel_id = novel["novel_id"]
        source_path = Path(novel["file_path"])
        novel_title = novel.get("filename", "").replace(".txt", "") if novel.get("filename") else None

        log_base_dir = settings.paths.log_dir
        analysis_logger = AnalysisLogger(log_base_dir, task_id)
        logger.info(f"Task ID: {task_id}")
        logger.info(f"Log directory: {analysis_logger.log_dir}")

        db_session = self.session_factory.get_session(task_id, init_tables=True)
        conn = db_session.connection

        run_repo = RunRepository(conn)
        run_id = run_repo.create_run(
            novel_id=novel_id,
            source_path=str(source_path),
            title=novel_title,
        )
        logger.info(f"Created analysis run: run_id={run_id} for novel_id={novel_id}")

        stats_repo = StatsRepository(conn)
        stats_repo.insert_global_context(
            run_id=run_id,
            novel_id=novel_id,
            novel_title=novel_title,
            core_characters="[]",
            world_setting="",
        )
        logger.info(f"Created database with novel_id={novel_id}")

        return novel_id, source_path, novel_title, conn, analysis_logger, run_id

    def _check_stage_completion_status(self, session: Session, run_id: str) -> dict[str, bool]:
        """
        检查各阶段完成状态

        修改时间: 2026-03-15
        修改者: TraeAI
        任务: storage-layer-decoupling
        修改内容: 使用 Repository 替代 operations 函数，添加 run_id 参数
        """
        chunk_repo = ChunkRepository(session)
        ann_repo = AnnotationRepository(session)
        stats_repo = StatsRepository(session)

        skip_preprocess = False
        skip_annotate = False
        skip_aggregate = False
        skip_topic_model = False
        skip_diagnose = False

        if chunk_repo.is_preprocess_complete(run_id):
            logger.info("Preprocess complete, skipping")
            skip_preprocess = True
        if skip_preprocess and ann_repo.is_annotate_complete(run_id):
            logger.info("Annotate complete, skipping")
            skip_annotate = True
        if skip_annotate and stats_repo.is_aggregate_complete(run_id):
            logger.info("Aggregate complete, skipping")
            skip_aggregate = True
        if skip_aggregate and stats_repo.has_topic_data(run_id):
            logger.info("Topic model complete, skipping")
            skip_topic_model = True
        if skip_topic_model and stats_repo.has_diagnosis_data(run_id):
            logger.info("Diagnose complete, skipping")
            skip_diagnose = True

        return {
            "skip_preprocess": skip_preprocess,
            "skip_annotate": skip_annotate,
            "skip_aggregate": skip_aggregate,
            "skip_topic_model": skip_topic_model,
            "skip_diagnose": skip_diagnose,
        }

    async def _execute_analysis_stages(
        self,
        task_id: str,
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
        loop = asyncio.get_event_loop()

        if not skip_stages["skip_preprocess"]:
            self.task_manager.update_task(task_id, stage="preprocess", progress=settings.analysis.progress.preprocess)
            await loop.run_in_executor(
                None,
                lambda: self._run_preprocess(source_path, run_id, session, max_chars, overlap),
            )

        if not skip_stages["skip_annotate"]:
            self.task_manager.update_task(task_id, stage="annotate", progress=settings.analysis.progress.annotate)
            await loop.run_in_executor(
                None,
                lambda: self._run_annotate(run_id, session, novel_id, analysis_logger, novel_title),
            )

        if not skip_stages["skip_aggregate"]:
            self.task_manager.update_task(task_id, stage="aggregate", progress=settings.analysis.progress.aggregate)
            await loop.run_in_executor(None, lambda: self._run_aggregate(run_id, session))

        if not skip_stages["skip_topic_model"]:
            self.task_manager.update_task(task_id, stage="topic-model", progress=settings.analysis.progress.topic_model)
            await loop.run_in_executor(None, lambda: self._run_topic_model(run_id, session, num_topics))

        if not skip_stages["skip_diagnose"]:
            self.task_manager.update_task(task_id, stage="diagnose", progress=settings.analysis.progress.diagnose)
            await loop.run_in_executor(None, lambda: self._run_diagnose(run_id, session, analysis_logger))

    def _handle_analysis_success(
        self,
        task_id: str,
        novel_id: str,
        elapsed: float,
        analysis_logger: AnalysisLogger | None,
        session: Session,
        run_id: str,
        log_prefix: str = "Analysis",
    ) -> None:
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

        logger.info(f"{log_prefix} completed: {task_id}")

    def _handle_analysis_failure(
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

    def _build_reanalysis_skip_stages(self, request: Optional[ReanalyzeRequest]) -> dict[str, bool]:
        return {
            "skip_preprocess": not (request.force_preprocess if request else True),
            "skip_annotate": not (request.force_annotate if request else True),
            "skip_aggregate": not (request.force_aggregate if request else True),
            "skip_topic_model": not (request.force_topic_model if request else True),
            "skip_diagnose": not (request.force_diagnose if request else True),
        }

    async def _run_analysis(self, task_id: str, novel: dict, request: Optional[AnalyzeRequest]) -> None:
        start_time = time.time()
        analysis_logger: AnalysisLogger | None = None
        session: Session | None = None
        run_id: str | None = None
        try:
            novel_id, source_path, novel_title, session, analysis_logger, run_id = self._init_analysis_environment(
                task_id, novel
            )

            num_topics = request.num_topics if request else 25
            max_chars = request.max_chars if request else 2000
            overlap = request.overlap if request else 200

            skip_stages = self._check_stage_completion_status(session, run_id)

            if self._check_all_stages_completed(skip_stages):
                self._handle_already_completed(task_id, novel_id, analysis_logger)
                return

            self.task_manager.update_task(task_id, status=TaskStatus.RUNNING, stage="preprocess", progress=0)

            await self._execute_analysis_stages(
                task_id=task_id,
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

            elapsed = time.time() - start_time
            self._handle_analysis_success(task_id, novel_id, elapsed, analysis_logger, session, run_id)

        except Exception as e:
            elapsed = time.time() - start_time
            if session and run_id:
                self._handle_analysis_failure(
                    task_id, novel.get("novel_id", "unknown"), elapsed, e, analysis_logger, session, run_id
                )
            else:
                self.novel_service.update_task_status(task_id, "failed")
                self.task_manager.complete_task(task_id, success=False, error=str(e))
        finally:
            if analysis_logger:
                analysis_logger.close()
            if session:
                session.close()

    async def _run_reanalysis(self, task_id: str, novel: dict, request: Optional[ReanalyzeRequest]) -> None:
        start_time = time.time()
        analysis_logger: AnalysisLogger | None = None
        session: Session | None = None
        run_id: str | None = None
        try:
            novel_id, source_path, novel_title, session, analysis_logger, run_id = self._init_analysis_environment(
                task_id, novel
            )

            skip_stages = self._build_reanalysis_skip_stages(request)
            num_topics = request.num_topics if request else settings.topic_model.single_book.num_topics

            self.task_manager.update_task(task_id, status=TaskStatus.RUNNING, stage="preprocess", progress=0)

            await self._execute_analysis_stages(
                task_id=task_id,
                session=session,
                run_id=run_id,
                source_path=source_path,
                novel_id=novel_id,
                novel_title=novel_title,
                analysis_logger=analysis_logger,
                skip_stages=skip_stages,
                num_topics=num_topics,
            )

            elapsed = time.time() - start_time
            self._handle_analysis_success(
                task_id, novel_id, elapsed, analysis_logger, session, run_id, log_prefix="Reanalysis"
            )

        except Exception as e:
            elapsed = time.time() - start_time
            if session and run_id:
                self._handle_analysis_failure(
                    task_id,
                    novel.get("novel_id", "unknown"),
                    elapsed,
                    e,
                    analysis_logger,
                    session,
                    run_id,
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

    def _run_preprocess(
        self, source_path: Path, run_id: str, session: Session, max_chars: int = 2000, overlap: int = 200
    ) -> None:
        from src.workflows import run_preprocess

        run_preprocess(source_path=source_path, run_id=run_id, session=session, max_chars=max_chars, overlap=overlap)

    def _run_annotate(
        self,
        run_id: str,
        session: Session,
        novel_id: str,
        analysis_logger: AnalysisLogger | None,
        novel_title: str | None = None,
    ) -> None:
        from src.workflows import run_annotate

        run_annotate(
            run_id=run_id,
            session=session,
            resume=True,
            analysis_logger=analysis_logger,
            novel_id=novel_id,
            novel_title=novel_title,
        )

    def _run_aggregate(self, run_id: str, session: Session) -> None:
        from src.workflows import run_aggregate

        run_aggregate(run_id=run_id, session=session)

    def _run_topic_model(self, run_id: str, session: Session, num_topics: int | None = None) -> None:
        from src.workflows import run_topic_model

        if num_topics is None:
            num_topics = settings.topic_model.single_book.num_topics
        run_topic_model(run_id=run_id, session=session, num_topics=num_topics)

    def _run_diagnose(self, run_id: str, session: Session, analysis_logger: AnalysisLogger | None) -> None:
        from src.workflows import run_diagnose
        from src.models.cloud import ConfiguredCloudModelClient

        diagnose_client = ConfiguredCloudModelClient(analysis_logger=analysis_logger)
        run_diagnose(run_id=run_id, session=session, analysis_logger=analysis_logger, client=diagnose_client)

    def get_task_status(self, task_id: str) -> Optional[dict]:
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
