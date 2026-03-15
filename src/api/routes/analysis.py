from __future__ import annotations

from fastapi import APIRouter, Depends
from typing import Optional

from src.api.models.requests import AnalyzeRequest, ReanalyzeRequest
from src.api.models.responses import (
    AnalyzeResponse,
    StatusResponse,
    TaskStatus,
    ReanalyzeResponse,
    TaskListResponse,
    TaskInfoResponse,
)
from src.api.services.novel_service import NovelService
from src.api.services.task_manager import TaskManager
from src.api.services.analysis_service import AnalysisService
from src.api.routes.novels import get_novel_service

router = APIRouter(prefix="/novels", tags=["analysis"])

_task_manager = TaskManager()


def get_task_manager() -> TaskManager:
    return _task_manager


@router.post("/{novel_id}/analyze", response_model=AnalyzeResponse)
async def start_analysis(
    novel_id: str,
    request: Optional[AnalyzeRequest] = None,
    novel_service: NovelService = Depends(get_novel_service),
    task_manager: TaskManager = Depends(get_task_manager),
) -> AnalyzeResponse:
    analysis_service = AnalysisService(novel_service, task_manager)
    task_id = await analysis_service.start_analysis(novel_id, request)
    return AnalyzeResponse(novel_id=novel_id, task_id=task_id)


@router.post("/{novel_id}/reanalyze", response_model=ReanalyzeResponse)
async def start_reanalysis(
    novel_id: str,
    request: Optional[ReanalyzeRequest] = None,
    novel_service: NovelService = Depends(get_novel_service),
    task_manager: TaskManager = Depends(get_task_manager),
) -> ReanalyzeResponse:
    analysis_service = AnalysisService(novel_service, task_manager)
    task_id = await analysis_service.start_reanalysis(novel_id, request)
    return ReanalyzeResponse(novel_id=novel_id, task_id=task_id)


@router.get("/{novel_id}/tasks", response_model=TaskListResponse)
async def list_tasks(novel_id: str, novel_service: NovelService = Depends(get_novel_service)) -> TaskListResponse:
    """
    获取小说的所有任务列表

    修改时间: 2026-03-16
    修改者: TraeAI
    任务: postgresql-migration-cleanup
    修改内容: 移除 db_path 字段，使用 run_id
    """
    tasks = novel_service.get_tasks_by_novel(novel_id)
    return TaskListResponse(
        novel_id=novel_id,
        tasks=[
            TaskInfoResponse(
                task_id=t["task_id"],
                novel_id=t["novel_id"],
                status=t["status"],
                run_id=t.get("run_id"),
            )
            for t in tasks
        ],
    )


@router.delete("/{novel_id}/tasks/{task_id}")
async def delete_task(novel_id: str, task_id: str, novel_service: NovelService = Depends(get_novel_service)):
    novel_service.delete_task(task_id)
    return {"message": "任务删除成功", "novel_id": novel_id, "task_id": task_id}


@router.get("/{novel_id}/status", response_model=StatusResponse)
async def get_analysis_status(
    novel_id: str,
    task_id: Optional[str] = None,
    novel_service: NovelService = Depends(get_novel_service),
    task_manager: TaskManager = Depends(get_task_manager),
) -> StatusResponse:
    """
    2026-03-12: Claude修改，添加task_id参数支持
    - task_id非必须，但有多个task时必须提供
    - 使用和analyze一样的多任务判断逻辑
    """
    from src.api.exceptions import AnalysisError

    if task_id:
        task_info = task_manager.get_task(task_id)
        if task_info is None:
            novel_service.get_task(task_id)
            return StatusResponse(
                novel_id=novel_id, task_id=task_id, status=TaskStatus.COMPLETED, progress=100.0, stage="completed"
            )
        return StatusResponse(
            novel_id=novel_id,
            task_id=task_id,
            status=task_info.status,
            progress=task_info.progress,
            stage=task_info.stage,
            error=task_info.error,
        )

    task, error = novel_service.get_single_valid_task(novel_id)

    if error:
        raise AnalysisError(error)

    if task is None:
        return StatusResponse(novel_id=novel_id, status=TaskStatus.PENDING, progress=0.0)

    task_id = task["task_id"]
    task_status = task.get("status", "unknown")

    task_info = task_manager.get_task(task_id)
    if task_info is None:
        status_map = {
            "completed": TaskStatus.COMPLETED,
            "running": TaskStatus.RUNNING,
            "pending": TaskStatus.PENDING,
            "failed": TaskStatus.FAILED,
        }
        return StatusResponse(
            novel_id=novel_id,
            task_id=task_id,
            status=status_map.get(task_status, TaskStatus.PENDING),
            progress=100.0 if task_status == "completed" else 0.0,
            stage=task_status,
        )

    return StatusResponse(
        novel_id=novel_id,
        task_id=task_id,
        status=task_info.status,
        progress=task_info.progress,
        stage=task_info.stage,
        error=task_info.error,
    )
