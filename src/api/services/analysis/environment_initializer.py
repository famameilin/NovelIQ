"""
分析环境初始化服务

创建时间: 2026-04-07
创建者: GLM-5
任务: AnalysisService 重构 - 提取环境初始化职责
说明: 负责初始化分析环境，包括数据库连接、run_id 生成、日志目录创建等
"""

from __future__ import annotations

import uuid
from pathlib import Path
from typing import TYPE_CHECKING

from loguru import logger
from sqlalchemy.orm import Session

from src.config import settings
from src.config.analysis_logger import AnalysisLogger
from src.storage.repositories import RunRepository, StatsRepository
from src.storage.session import SessionFactory

if TYPE_CHECKING:
    pass


class EnvironmentInitializer:
    """分析环境初始化服务"""

    def __init__(self, session_factory: SessionFactory | None = None):
        self.session_factory = session_factory or SessionFactory()

    def init_analysis_environment(
        self,
        task_id: str,
        novel: dict,
    ) -> tuple[str, Path, str | None, Session, AnalysisLogger, str]:
        """
        初始化分析环境

        Args:
            task_id: 任务ID
            novel: 小说信息字典

        Returns:
            Tuple[novel_id, source_path, novel_title, session, analysis_logger, run_id]
        """
        novel_id = novel["novel_id"]
        source_path = Path(novel["file_path"])
        novel_title = novel.get("filename", "").replace(".txt", "") if novel.get("filename") else None

        db_session = self.session_factory.get_session(init_tables=True)
        conn = db_session.connection

        run_id = self._get_or_create_run_id(task_id, novel_id, source_path, novel_title, conn)

        analysis_logger = self._create_analysis_logger(run_id)
        self._log_initialization_info(task_id, run_id, analysis_logger)

        self._ensure_global_context(run_id, novel_id, novel_title, conn)

        return novel_id, source_path, novel_title, conn, analysis_logger, run_id

    def _get_or_create_run_id(
        self,
        task_id: str,
        novel_id: str,
        source_path: Path,
        novel_title: str | None,
        conn: Session,
    ) -> str:
        """获取或创建 run_id"""
        run_repo = RunRepository(conn)

        existing_run = run_repo.get_run_by_run_id_prefix(task_id)
        if existing_run:
            run_id = existing_run["run_id"]
            logger.info(f"Reusing existing run_id: {run_id} for task_id: {task_id}")
        else:
            run_id = f"{task_id}{str(uuid.uuid4())[8:]}"
            run_repo.create_run(
                novel_id=novel_id,
                source_path=str(source_path),
                title=novel_title,
                run_id=run_id,
            )
            logger.info(f"Created analysis run: run_id={run_id} for novel_id={novel_id}")

        return run_id

    def _create_analysis_logger(self, run_id: str) -> AnalysisLogger:
        """创建分析日志记录器"""
        log_base_dir = settings.paths.log_dir
        return AnalysisLogger(log_base_dir, run_id)

    def _log_initialization_info(
        self,
        task_id: str,
        run_id: str,
        analysis_logger: AnalysisLogger,
    ) -> None:
        """记录初始化信息"""
        logger.info(f"Task ID: {task_id}")
        logger.info(f"Run ID: {run_id}")
        logger.info(f"Log directory: {analysis_logger.log_dir}")

    def _ensure_global_context(
        self,
        run_id: str,
        novel_id: str,
        novel_title: str | None,
        conn: Session,
    ) -> None:
        """确保全局上下文存在"""
        stats_repo = StatsRepository(conn)
        if not stats_repo.has_global_context(run_id):
            stats_repo.insert_global_context(
                run_id=run_id,
                novel_id=novel_id,
                novel_title=novel_title,
                core_characters="[]",
                world_setting="",
            )
            logger.info(f"Created database with novel_id={novel_id}")

    def check_stage_completion_status(self, session: Session, run_id: str) -> dict[str, bool]:
        """检查各阶段完成状态"""
        from src.storage.repositories import AnnotationRepository, ChunkRepository

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
