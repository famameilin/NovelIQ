"""
分析结果导出路由

说明: 完整分析结果导出到 outputs/*.json（复盘与测试用）；数据装配在
src/api/services/results_export_service.py，本模块只做依赖注入与响应组装。
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query
from loguru import logger
from sqlalchemy.orm import Session

from src.api.dependencies import get_novel_service
from src.api.models.responses import ResultsWriteResponse
from src.api.routes.results_common import (
    _require_readable_run_status,
    _require_run_for_novel,
    get_db_session,
    resolve_run_id,
)
from src.api.services.novel_service import NovelService
from src.api.services.results_export_service import (
    build_results_response,
    fetch_all_results_data,
    write_results_to_file,
)
from src.storage.repositories import AnnotationRepository, ChapterRepository, StatsRepository

# 说明: tags 由主模块 router（tags=["results"]）在 include 时统一附加，避免标签重复
router = APIRouter()


@router.get(
    "/{novel_id}/results",
    response_model=ResultsWriteResponse,
    summary="导出完整分析结果（复盘与测试用）",
    description="把完整分析数据写入 outputs/*.json：写入状态、文件路径与缺失字段清单。"
    "生产读路径请用 paragraph-curves / chapter-annotations / characters / topics / diagnosis / metrics/* 等接口。",
)
async def get_results(
    novel_id: str,
    task_id: Annotated[str, Query(..., description="分析任务ID")],
    run_id: Annotated[str, Depends(resolve_run_id)],
    session: Annotated[Session, Depends(get_db_session)],
    novel_service: Annotated[NovelService, Depends(get_novel_service)],
) -> ResultsWriteResponse:
    run = _require_run_for_novel(session, novel_id, run_id)

    _require_readable_run_status(run)

    stats_repo = StatsRepository(session)
    annotation_repo = AnnotationRepository(session)
    chapter_repo = ChapterRepository(session)

    results_data, missing_fields, novel_name = fetch_all_results_data(
        novel_id, task_id, run_id, stats_repo, annotation_repo, chapter_repo
    )
    file_path = write_results_to_file(task_id, results_data)

    if missing_fields:
        logger.warning(f"Task {task_id} has missing fields: {missing_fields}")

    return build_results_response(file_path, novel_id, novel_name, missing_fields)


