"""
工作流辅助函数模块

创建时间: 2026-03-13
创建者: TraeAI
任务: refactor-analysis-layer-functions
说明: 从 run_full_workflow 函数中提取的辅助函数，实现职责分离

修改时间: 2026-03-15
修改者: TraeAI
任务: storage-layer-decoupling
修改内容: 移除向后兼容代码，使用 run_id/session 参数

修改时间: 2026-03-15
修改者: TraeAI
任务: storage-layer-decoupling
修改内容: 移除 operations 导入，使用 Repository 替代

修改时间: 2026-03-16
修改者: TraeAI
任务: postgresql-migration-cleanup
修改内容: 移除 db_path 参数，使用 PostgreSQL 单一数据库

修改时间: 2026-03-19
修改者: TraeAI
任务: unify-id-generation-cli
修改内容: 使用统一的ID生成工具 generate_task_id 替代 uuid.uuid4()
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

from loguru import logger
from sqlalchemy.orm import Session

from src.config.analysis_logger import AnalysisLogger
from src.ingest.reader import ingest_path
from src.models.cloud import ConfiguredCloudModelClient
from src.storage.db import get_session
from src.storage.id_mapping import generate_task_id
from src.storage.repositories import AnnotationRepository, ChunkRepository, RunRepository, StatsRepository
from src.workflows.aggregate import run_aggregate
from src.workflows.annotate import run_annotate
from src.workflows.diagnose import run_diagnose
from src.workflows.preprocess import run_preprocess

if TYPE_CHECKING:
    pass


@dataclass
class StageResult:
    name: str
    success: bool
    elapsed: float
    error: str | None = None
    skipped: bool = False


def _check_stage_completion(session: Session, stage_name: str, run_id: str) -> bool:
    """
    检查阶段是否完成

    修改时间: 2026-03-15
    修改者: TraeAI
    任务: storage-layer-decoupling
    修改内容: 使用 Repository 替代 operations 函数
    """
    if stage_name == "preprocess":
        chunk_repo = ChunkRepository(session)
        return chunk_repo.has_chunks(run_id)
    elif stage_name == "annotate":
        ann_repo = AnnotationRepository(session)
        return ann_repo.has_annotations(run_id)
    elif stage_name == "aggregate":
        stats_repo = StatsRepository(session)
        return stats_repo.has_aggregated_data(run_id)
    return False


def _execute_preprocess_stage(
    source_path: Path,
    metadata_path: Path | None,
    run_id: str,
    session: Session,
) -> StageResult:
    stage_start = time.time()

    if _check_stage_completion(session, "preprocess", run_id):
        logger.info("Stage preprocess: SKIPPED (already completed)")
        return StageResult(name="preprocess", success=True, elapsed=0.0, skipped=True)

    chunks, chars, elapsed = run_preprocess(
        source_path=source_path,
        run_id=run_id,
        session=session,
    )

    if chunks == 0:
        raise RuntimeError("preprocess produced no chunks")

    stage_elapsed = time.time() - stage_start
    logger.info(f"Stage preprocess: OK [{stage_elapsed:.2f}s]")
    return StageResult(name="preprocess", success=True, elapsed=stage_elapsed)


def _execute_annotate_stage(
    run_id: str,
    session: Session,
    analysis_logger: AnalysisLogger,
    annotate_client: Any,
    novel_id: str,
    novel_title: str | None,
    incremental_disambig_client: Any = None,
    full_disambig_client: Any = None,
) -> StageResult:
    """
    执行标注阶段

    修改时间: 2026-03-15
    修改者: TraeAI
    任务: storage-layer-decoupling
    修改内容: 添加 incremental_disambig_client 和 full_disambig_client 参数，支持测试注入 mock
    """
    stage_start = time.time()

    chunk_repo = ChunkRepository(session)
    if not chunk_repo.has_chunks(run_id):
        raise RuntimeError("annotate requires chunks data. Run preprocess first.")

    if _check_stage_completion(session, "annotate", run_id):
        logger.info("Stage annotate: SKIPPED (already completed)")
        return StageResult(name="annotate", success=True, elapsed=0.0, skipped=True)

    success, errors, total = run_annotate(
        run_id=run_id,
        session=session,
        resume=False,
        analysis_logger=analysis_logger,
        novel_id=novel_id,
        novel_title=novel_title,
        annotate_client=annotate_client,
        incremental_disambig_client=incremental_disambig_client,
        full_disambig_client=full_disambig_client,
    )

    if success == 0:
        raise RuntimeError("annotate produced no annotations")

    stage_elapsed = time.time() - stage_start
    logger.info(f"Stage annotate: OK [{stage_elapsed:.2f}s]")
    return StageResult(name="annotate", success=True, elapsed=stage_elapsed)


def _execute_aggregate_stage(
    run_id: str,
    session: Session,
) -> StageResult:
    stage_start = time.time()

    chunk_repo = ChunkRepository(session)
    if not chunk_repo.has_chunks(run_id):
        raise RuntimeError("aggregate requires chunks data. Run preprocess first.")

    if _check_stage_completion(session, "aggregate", run_id):
        logger.info("Stage aggregate: SKIPPED (already completed)")
        return StageResult(name="aggregate", success=True, elapsed=0.0, skipped=True)

    chunks, emotion_rows, rhythm_rows = run_aggregate(
        run_id=run_id,
        session=session,
    )

    if chunks == 0:
        raise RuntimeError("aggregate produced no data")

    stage_elapsed = time.time() - stage_start
    logger.info(f"Stage aggregate: OK [{stage_elapsed:.2f}s]")
    return StageResult(name="aggregate", success=True, elapsed=stage_elapsed)


def _execute_diagnose_stage(
    run_id: str,
    session: Session,
    analysis_logger: AnalysisLogger,
    cloud_client: ConfiguredCloudModelClient | None,
) -> StageResult:
    stage_start = time.time()

    stats_repo = StatsRepository(session)
    if not stats_repo.has_aggregated_data(run_id):
        raise RuntimeError("diagnose requires aggregated data. Run aggregate first.")

    diagnose_client = cloud_client or ConfiguredCloudModelClient(analysis_logger=analysis_logger)
    run_diagnose(
        run_id=run_id,
        session=session,
        analysis_logger=analysis_logger,
        client=diagnose_client,
    )

    stage_elapsed = time.time() - stage_start
    logger.info(f"Stage diagnose: OK [{stage_elapsed:.2f}s]")
    return StageResult(name="diagnose", success=True, elapsed=stage_elapsed)


def _log_workflow_summary(
    results: list[StageResult],
    total_elapsed: float,
    analysis_logger: AnalysisLogger,
    novel_id: str,
    run_id: str,
) -> None:
    analysis_logger.write_summary(
        {
            "novel_id": novel_id,
            "analysis_id": analysis_logger.task_id,
            "run_id": run_id,
            "total_time": total_elapsed,
            "stages": [
                {"name": r.name, "success": r.success, "elapsed": r.elapsed, "skipped": r.skipped, "error": r.error}
                for r in results
            ],
        }
    )

    logger.info(f"\n{'=' * 50}")
    logger.info("=== Workflow Summary ===")
    logger.info(f"{'=' * 50}")

    for result in results:
        if result.skipped:
            status = "SKIPPED"
        elif result.success:
            status = "OK"
        else:
            status = f"FAILED: {result.error}"
        logger.info(f"  {result.name}: {status} [{result.elapsed:.2f}s]")

    logger.info(f"\nTotal time: {total_elapsed:.2f}s")
    logger.info(f"Log directory: {analysis_logger.log_dir}")

    all_success = all(r.success for r in results)
    if all_success:
        logger.info("Status: SUCCESS")
    else:
        logger.error("Status: FAILED")


class WorkflowInitResult:
    def __init__(
        self,
        novel_id: str,
        novel_title: str | None,
        run_id: str,
        session: Session,
        analysis_logger: AnalysisLogger,
        stages: list[tuple],
        total_stages: int,
    ) -> None:
        self.novel_id = novel_id
        self.novel_title = novel_title
        self.run_id = run_id
        self.session = session
        self.analysis_logger = analysis_logger
        self.stages = stages
        self.total_stages = total_stages


def _init_workflow(
    source_path: Path,
    metadata_path: Path | None,
    skip_preprocess: bool,
    skip_annotate: bool,
    skip_aggregate: bool,
    skip_diagnose: bool,
    analysis_id: str | None,
) -> WorkflowInitResult:
    """
    初始化工作流

    修改时间: 2026-03-15
    修改者: TraeAI
    任务: storage-layer-decoupling
    修改内容: 如果数据库已存在且有运行记录，复用最新的 run_id

    修改时间: 2026-03-15
    修改者: TraeAI
    任务: decouple-migration-progress-evaluation
    修改内容: 使用 SessionFactory 替代 connect_db/create_tables，消除 DeprecationWarning

    修改时间: 2026-03-16
    修改者: TraeAI
    任务: postgresql-migration-cleanup
    修改内容: 移除 db_path 参数，使用 get_session 获取 PostgreSQL 连接
    """
    session_factory = get_session()
    conn = session_factory.__enter__()

    docs = ingest_path(source_path, metadata_path)
    if docs:
        primary = docs[0]
        novel_id = primary.title or primary.source_path.stem
        novel_title = primary.title
    else:
        novel_id = source_path.stem
        novel_title = None

    run_repo = RunRepository(conn)
    existing_runs = run_repo.get_runs_by_novel(novel_id)
    if existing_runs:
        run_id = existing_runs[0]["run_id"]
        logger.info(f"Reusing existing analysis run: run_id={run_id}")
    else:
        run_id = run_repo.create_run(
            novel_id=novel_id,
            source_path=str(source_path),
            title=novel_title,
        )
        logger.info(f"Created analysis run: run_id={run_id}")

    log_base_dir = Path("logs") / "analysis"
    task_id = analysis_id or generate_task_id()
    analysis_logger = AnalysisLogger(log_base_dir, task_id)
    logger.info(f"Analysis ID: {analysis_logger.task_id}")
    logger.info(f"Log directory: {analysis_logger.log_dir}")

    stages = [
        ("preprocess", not skip_preprocess),
        ("annotate", not skip_annotate),
        ("aggregate", not skip_aggregate),
        ("diagnose", not skip_diagnose),
    ]
    total_stages = sum(1 for _, enabled in stages if enabled)

    return WorkflowInitResult(
        novel_id=novel_id,
        novel_title=novel_title,
        run_id=run_id,
        session=conn,
        analysis_logger=analysis_logger,
        stages=stages,
        total_stages=total_stages,
    )


def _execute_stages(
    init_result: WorkflowInitResult,
    source_path: Path,
    metadata_path: Path | None,
    cloud_client: ConfiguredCloudModelClient | None,
    annotate_client: Any = None,
    incremental_disambig_client: Any = None,
    full_disambig_client: Any = None,
) -> list[StageResult]:
    """
    执行所有阶段

    修改时间: 2026-03-15
    修改者: TraeAI
    任务: storage-layer-decoupling
    修改内容: 添加 incremental_disambig_client 和 full_disambig_client 参数，支持测试注入 mock
    """
    results: list[StageResult] = []
    current_stage = 0

    for stage_name, enabled in init_result.stages:
        if not enabled:
            results.append(StageResult(name=stage_name, success=True, elapsed=0.0, skipped=True))
            logger.info(f"Stage {stage_name}: SKIPPED (by user)")
            continue

        current_stage += 1
        logger.info(f"\n=== Stage {current_stage}/{init_result.total_stages}: {stage_name} ===")

        try:
            if stage_name == "preprocess":
                result = _execute_preprocess_stage(source_path, metadata_path, init_result.run_id, init_result.session)
            elif stage_name == "annotate":
                result = _execute_annotate_stage(
                    init_result.run_id,
                    init_result.session,
                    init_result.analysis_logger,
                    annotate_client,
                    init_result.novel_id,
                    init_result.novel_title,
                    incremental_disambig_client,
                    full_disambig_client,
                )
            elif stage_name == "aggregate":
                result = _execute_aggregate_stage(init_result.run_id, init_result.session)
            elif stage_name == "diagnose":
                result = _execute_diagnose_stage(
                    init_result.run_id,
                    init_result.session,
                    init_result.analysis_logger,
                    cloud_client,
                )
            else:
                continue
            results.append(result)
        except Exception as e:
            results.append(StageResult(name=stage_name, success=False, elapsed=0.0, error=str(e)))
            logger.error(f"Stage {stage_name}: FAILED")
            logger.error(f"Error: {e}")
            break

    return results
