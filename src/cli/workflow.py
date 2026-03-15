"""
工作流编排模块

创建时间: 2025-03-11
创建者: TraeAI
任务: 工作流编排

修改时间: 2026-03-13
修改者: TraeAI
任务: refactor-analysis-layer-functions
修改内容: 重构函数，使用辅助函数拆解职责

修改时间: 2026-03-15
修改者: TraeAI
任务: storage-layer-decoupling
修改内容: 移除向后兼容代码，使用 run_id/session 参数

修改时间: 2026-03-16
修改者: TraeAI
任务: postgresql-migration-cleanup
修改内容: 移除 db_path 参数，使用 PostgreSQL 单一数据库
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, List

from src.cli.workflow_helpers import (
    _init_workflow,
    _execute_stages,
    _log_workflow_summary,
)

if TYPE_CHECKING:
    from src.models.cloud.client import ConfiguredCloudModelClient


@dataclass
class StageResult:
    name: str
    success: bool
    elapsed: float
    error: str | None = None
    skipped: bool = False


def run_full_workflow(
    source_path: Path,
    metadata_path: Path | None = None,
    cache_path: Path | None = None,
    skip_preprocess: bool = False,
    skip_annotate: bool = False,
    skip_aggregate: bool = False,
    skip_diagnose: bool = False,
    analysis_id: str | None = None,
    cloud_client: "ConfiguredCloudModelClient | None" = None,
    annotate_client: Any = None,
    incremental_disambig_client: Any = None,
    full_disambig_client: Any = None,
) -> List[StageResult]:
    """
    执行完整工作流

    修改时间: 2026-03-15
    修改者: TraeAI
    任务: storage-layer-decoupling
    修改内容: 添加 incremental_disambig_client 和 full_disambig_client 参数，支持测试注入 mock

    修改时间: 2026-03-16
    修改者: TraeAI
    任务: postgresql-migration-cleanup
    修改内容: 移除 db_path 参数，使用 PostgreSQL 单一数据库
    """
    total_start = time.time()

    init_result = _init_workflow(
        source_path,
        metadata_path,
        skip_preprocess,
        skip_annotate,
        skip_aggregate,
        skip_diagnose,
        analysis_id,
    )

    helper_results = _execute_stages(
        init_result,
        source_path,
        metadata_path,
        cloud_client,
        annotate_client,
        incremental_disambig_client,
        full_disambig_client,
    )

    total_elapsed = time.time() - total_start
    results = [
        StageResult(
            name=r.name,
            success=r.success,
            elapsed=r.elapsed,
            error=r.error,
            skipped=r.skipped,
        )
        for r in helper_results
    ]

    _log_workflow_summary(helper_results, total_elapsed, init_result.analysis_logger, init_result.novel_id, init_result.run_id)

    init_result.session.close()

    return results
