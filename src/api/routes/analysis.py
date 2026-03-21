from __future__ import annotations

from fastapi import APIRouter, Depends
from typing import Optional, List, Dict
from loguru import logger

from src.api.models.requests import AnalyzeRequest, ReanalyzeRequest
from src.api.models.responses import (
    AnalyzeResponse,
    StatusResponse,
    TaskStatus,
    ReanalyzeResponse,
    TaskListResponse,
    TaskInfoResponse,
    BatchDeleteTasksRequest,
    BatchDeleteTasksResponse,
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

    修改时间: 2026-03-19
    修改者: TraeAI
    任务: API接口参数统一优化
    修改内容: 移除 run_id 字段，统一使用 task_id
    """
    tasks = novel_service.get_tasks_by_novel(novel_id)
    return TaskListResponse(
        novel_id=novel_id,
        tasks=[
            TaskInfoResponse(
                task_id=t["task_id"],
                novel_id=t["novel_id"],
                status=t["status"],
            )
            for t in tasks
        ],
    )


@router.delete("/{novel_id}/tasks/{task_id}")
async def delete_task(novel_id: str, task_id: str, novel_service: NovelService = Depends(get_novel_service)):
    novel_service.delete_task(task_id)
    return {"message": "任务删除成功", "novel_id": novel_id, "task_id": task_id}


@router.post("/{novel_id}/tasks/batch-delete", response_model=BatchDeleteTasksResponse)
async def batch_delete_tasks(
    novel_id: str,
    request: BatchDeleteTasksRequest,
    novel_service: NovelService = Depends(get_novel_service)
) -> BatchDeleteTasksResponse:
    """
    批量删除任务

    创建时间: 2026-03-19
    创建者: TraeAI
    任务: 新增批量删除功能

    批量删除指定的分析任务。
    即使部分删除失败，也会继续处理其他任务。
    """
    deleted_ids: List[str] = []
    failed_ids: List[Dict[str, str]] = []

    for task_id in request.task_ids:
        try:
            # 验证任务是否属于该小说
            task = novel_service.get_run_by_task_id(task_id)
            if task is None:
                # 尝试从数据库加载
                task = novel_service._load_task_from_db(task_id)

            if task is None:
                failed_ids.append({"task_id": task_id, "reason": "任务不存在"})
                logger.warning(f"Batch delete task: task {task_id} not found")
                continue

            if task.get("novel_id") != novel_id:
                failed_ids.append({"task_id": task_id, "reason": f"任务不属于小说 {novel_id}"})
                logger.warning(f"Batch delete task: task {task_id} does not belong to novel {novel_id}")
                continue

            novel_service.delete_task(task_id)
            deleted_ids.append(task_id)
            logger.info(f"Batch delete: task {task_id} deleted successfully")
        except Exception as e:
            failed_ids.append({"task_id": task_id, "reason": f"删除失败: {e}"})
            logger.error(f"Batch delete: failed to delete task {task_id}: {e}")

    total_count = len(request.task_ids)
    deleted_count = len(deleted_ids)
    failed_count = len(failed_ids)

    if deleted_count == total_count:
        message = f"成功删除 {deleted_count} 个任务"
        success = True
    elif deleted_count > 0:
        message = f"部分删除成功: {deleted_count} 个成功, {failed_count} 个失败"
        success = True
    else:
        message = f"删除失败: {failed_count} 个任务无法删除"
        success = False

    return BatchDeleteTasksResponse(
        success=success,
        message=message,
        deleted_count=deleted_count,
        failed_count=failed_count,
        deleted_ids=deleted_ids,
        failed_ids=failed_ids,
    )


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
