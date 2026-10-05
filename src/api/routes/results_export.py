"""
分析结果导出路由

创建时间: 2026-10-02
创建者: Trae
任务: 大文件拆分（routes/results.py → 同目录资源域子模块）
说明: 从 src/api/routes/results.py 拆出完整结果导出域路由
（get_results/_build_results_response/_write_results_to_file），行为保持不变。
"""

from __future__ import annotations

import json
from typing import Annotated, Any

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
from src.api.services.results_export_service import fetch_all_results_data
from src.config import settings
from src.storage.repositories import AnnotationRepository, ChapterRepository, StatsRepository

# 说明: tags 由主模块 router（tags=["results"]）在 include 时统一附加，避免标签重复
router = APIRouter()


@router.get(
    "/{novel_id}/results",
    response_model=ResultsWriteResponse,
    summary="导出完整分析结果（复盘与测试用）",
    description="""
📋 **复盘与测试专用接口**

此接口将完整分析数据写入 `outputs/` 目录下的JSON文件，用于：
- 项目复盘与结果审查
- 测试验证与数据对比
- 分析结果归档备份

**参数：**
- task_id: 分析任务ID（8位短UUID，必需）

**返回内容：**
- 写入状态（成功/失败）
- 文件存储路径
- 数据完整性检查结果（缺失字段列表）

**生产环境数据获取请使用专用接口：**
- `GET /{novel_id}/paragraph-curves` - 获取段落曲线（情绪 + 张力）
- `GET /{novel_id}/chapter-annotations` - 获取分块标注与伏笔详情
- `GET /{novel_id}/characters` - 获取人物统计
- `GET /{novel_id}/topics` - 获取主题分布
- `GET /{novel_id}/diagnosis` - 获取云端诊断
- `GET /{novel_id}/metrics/*` - 获取各类聚合指标
""",
    responses={
        200: {
            "description": "结果已写入文件",
            "content": {
                "application/json": {
                    "example": {
                        "success": True,
                        "message": "分析结果已写入文件",
                        "file_path": "outputs/a1b2c3d4.json",
                        "novel_id": "10960c77",
                        "novel_name": "重明传",
                        "task_id": "a1b2c3d4",
                        "missing_fields": [],
                    }
                }
            },
        },
        400: {
            "description": "分析未完成或数据不完整",
            "content": {
                "application/json": {
                    "example": {
                        "success": False,
                        "message": "分析未完成，数据库不存在",
                        "file_path": None,
                        "novel_id": "10960c77",
                        "novel_name": None,
                        "task_id": "a1b2c3d4",
                        "missing_fields": ["paragraph_curves"],
                    }
                }
            },
        },
    },
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
    file_path = _write_results_to_file(task_id, results_data)

    if missing_fields:
        logger.warning(f"Task {task_id} has missing fields: {missing_fields}")

    return _build_results_response(file_path, novel_id, novel_name, missing_fields)


def _build_results_response(
    file_path: str, novel_id: str, novel_name: str | None, missing_fields: list[str]
) -> ResultsWriteResponse:
    """
    构建结果响应对象
    """
    return ResultsWriteResponse(
        success=True,
        message="分析结果已写入文件",
        file_path=file_path,
        novel_id=novel_id,
        novel_name=novel_name,
        missing_fields=missing_fields if missing_fields else None,
    )


def _write_results_to_file(task_id: str, data: dict[str, Any]) -> str:
    results_dir = settings.paths.results_dir
    results_dir.mkdir(parents=True, exist_ok=True)

    filename = f"{task_id}.json"
    file_path = results_dir / filename

    with open(file_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    logger.info(f"Results written to {file_path}")
    return str(file_path)
