"""
分析环境初始化服务

说明: 负责初始化分析环境，包括数据库连接、run_id 生成、日志目录创建等
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from loguru import logger

from src.config import settings
from src.config.analysis_logger import AnalysisLogger
from src.diagnosis.completion import has_diagnosis_data
from src.linguistic.completion import is_linguistic_complete
from src.metrics.queries.completion import is_aggregate_complete
from src.storage import Storage, get_storage_factory
from src.topic.completion import is_topic_model_complete
from src.work.queries import is_annotate_complete
from src.workflows.preprocess_readiness import is_preprocess_complete


class EnvironmentInitializer:
    """分析环境初始化服务"""

    def __init__(self, session_factory: Callable[[], Storage] | None = None):
        self.session_factory = session_factory or get_storage_factory()

    def init_analysis_environment(
        self,
        task_id: str,
        novel: dict,
    ) -> tuple[str, Path, str | None, Storage, AnalysisLogger, str]:
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

        db_session = self.session_factory()
        conn = db_session

        run_id = self._get_or_create_run_id(task_id, novel_id, source_path, novel_title, conn)

        # 2026-10-03 收口进程重启遗留的 running 审计行，避免僵尸行永久污染错误率统计
        # （run 08f9ba42 实证 12 条 running 僵尸行）；每次创建/恢复任务都会经过这里
        from src.audit.module import AuditModule

        orphaned = AuditModule.close_interrupted(self.session_factory, run_id)
        if orphaned:
            logger.info(f"Closed {orphaned} orphaned running invocations for run {run_id}")

        analysis_logger = self._create_analysis_logger(run_id)
        self._log_initialization_info(task_id, run_id, analysis_logger)

        return novel_id, source_path, novel_title, conn, analysis_logger, run_id

    def _get_or_create_run_id(
        self,
        task_id: str,
        novel_id: str,
        source_path: Path,
        novel_title: str | None,
        conn: Storage,
    ) -> str:
        """获取或创建 run_id"""
        run_repo = conn.runs

        existing_run = run_repo.get_run_by_task_id(task_id)
        if existing_run:
            run_id = existing_run["run_id"]
            logger.info(f"Reusing existing run_id: {run_id} for task_id: {task_id}")
        else:
            run_id = conn.new_id()
            run_repo.create_run(
                novel_id=novel_id,
                source_path=str(source_path),
                title=novel_title,
                run_id=run_id,
                task_id=task_id,
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

    def check_stage_completion_status(self, session: Storage, run_id: str) -> dict[str, bool]:
        """检查各阶段完成状态"""
        pass

        skip_preprocess = False
        skip_annotate = False
        skip_aggregate = False
        skip_linguistic = False
        skip_topic_model = False
        skip_diagnose = False

        if is_preprocess_complete(session, run_id):
            logger.info("Preprocess complete, skipping")
            skip_preprocess = True
        if skip_preprocess and is_annotate_complete(session, run_id):
            logger.info("Annotate complete, skipping")
            skip_annotate = True
        if skip_annotate and not settings.linguistic.ltp.enabled:
            logger.info("Linguistic disabled, treating stage as complete")
            skip_linguistic = True
        elif skip_annotate and is_linguistic_complete(session, run_id):
            logger.info("Linguistic complete, skipping")
            skip_linguistic = True
        if skip_linguistic and is_aggregate_complete(session, run_id):
            logger.info("Aggregate complete, skipping")
            skip_aggregate = True
        if skip_aggregate and is_topic_model_complete(session, run_id):
            logger.info("Topic model complete, skipping")
            skip_topic_model = True
        if skip_topic_model and has_diagnosis_data(session, run_id):
            logger.info("Diagnose complete, skipping")
            skip_diagnose = True

        return {
            "skip_preprocess": skip_preprocess,
            "skip_annotate": skip_annotate,
            "skip_aggregate": skip_aggregate,
            "skip_linguistic": skip_linguistic,
            "skip_topic_model": skip_topic_model,
            "skip_diagnose": skip_diagnose,
        }
