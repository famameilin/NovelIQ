from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from loguru import logger

from src.api.dependencies import get_novel_service, get_task_manager
from src.api.exceptions import NovelNotFoundError
from src.api.models.requests import ReanalyzeRequest
from src.api.models.responses import (
    BatchDeleteTasksRequest,
    BatchDeleteTasksResponse,
    CreateTaskResponse,
    ReanalyzeResponse,
    ResumeTaskResponse,
    StatusResponse,
    TaskInfoResponse,
    TaskListResponse,
    TaskStatus,
)
from src.api.services.analysis_service import AnalysisService
from src.api.services.novel_service import NovelService
from src.api.services.task_application_service import TaskApplicationService
from src.api.services.task_manager import TaskManager
from src.storage.db import get_session_factory
from src.storage.id_mapping import TaskIDNotFoundError, task_id_to_run_id
from src.storage.repositories import RunRepository

_STATUS_MAP: dict[str, TaskStatus] = {
    "completed": TaskStatus.COMPLETED,
    "running": TaskStatus.RUNNING,
    "pending": TaskStatus.PENDING,
    "failed": TaskStatus.FAILED,
    "cancelling": TaskStatus.CANCELLING,
    "cancelled": TaskStatus.CANCELLED,
}


def _map_status_to_task_status(status: str) -> TaskStatus:
    """
    将数据库状态字符串映射为TaskStatus枚举
    """
    try:
        return _STATUS_MAP[status]
    except KeyError as exc:
        raise ValueError(f"未知任务状态: {status}") from exc


router = APIRouter(prefix="/novels", tags=["analysis"])


@router.post("/{novel_id}/tasks", response_model=CreateTaskResponse)
async def create_and_start_task(
    novel_id: str,
    novel_service: NovelService = Depends(get_novel_service),
    task_manager: TaskManager = Depends(get_task_manager),
) -> CreateTaskResponse:
    """
    创建并启动一个新的分析任务
    """
    analysis_service = AnalysisService(novel_service, task_manager)
    task_id = await analysis_service.create_task_and_start(novel_id)
    return CreateTaskResponse(novel_id=novel_id, task_id=task_id)


@router.post("/{novel_id}/tasks/{task_id}/resume", response_model=ResumeTaskResponse)
async def resume_task(
    novel_id: str,
    task_id: str,
    novel_service: NovelService = Depends(get_novel_service),
    task_manager: TaskManager = Depends(get_task_manager),
) -> ResumeTaskResponse:
    """
    继续执行指定的 pending/failed 任务
    """
    task_application_service = TaskApplicationService(novel_service, task_manager)
    resumed_task_id = await task_application_service.resume_task(novel_id, task_id)
    return ResumeTaskResponse(novel_id=novel_id, task_id=resumed_task_id)


@router.post("/{novel_id}/reanalyze", response_model=ReanalyzeResponse)
async def start_reanalysis(
    novel_id: str,
    request: ReanalyzeRequest | None = None,
    novel_service: NovelService = Depends(get_novel_service),  # noqa: B008
    task_manager: TaskManager = Depends(get_task_manager),  # noqa: B008
) -> ReanalyzeResponse:
    analysis_service = AnalysisService(novel_service, task_manager)
    task_id = await analysis_service.start_reanalysis(novel_id, request)
    return ReanalyzeResponse(novel_id=novel_id, task_id=task_id)


@router.get("/{novel_id}/tasks", response_model=TaskListResponse)
async def list_tasks(novel_id: str, novel_service: NovelService = Depends(get_novel_service)) -> TaskListResponse:  # noqa: B008
    """
    获取小说的所有任务列表
    """
    tasks = novel_service.get_tasks_by_novel(novel_id)
    return TaskListResponse(
        novel_id=novel_id,
        tasks=[
            TaskInfoResponse(
                task_id=t["task_id"],
                novel_id=t["novel_id"],
                status=t["status"],
                created_at=t.get("created_at"),
            )
            for t in tasks
        ],
    )


@router.delete("/{novel_id}/tasks/{task_id}")
async def delete_task(
    novel_id: str,
    task_id: str,
    novel_service: NovelService = Depends(get_novel_service),
    task_manager: TaskManager = Depends(get_task_manager),
):
    """
    删除单个分析任务

    删除顺序:
        1. DB 状态判断（任务是否存在、是否属于该小说、是否运行中）
        2. 清理运行态缓存（停止后台协程）
        3. 删除 DB 记录
        4. 删除内存缓存
    """
    task_application_service = TaskApplicationService(novel_service, task_manager)
    return await task_application_service.delete_task(novel_id, task_id)


@router.get("/{novel_id}/tasks/{task_id}/status", response_model=StatusResponse)
async def get_task_status(
    novel_id: str,
    task_id: str,
    novel_service: NovelService = Depends(get_novel_service),
    task_manager: TaskManager = Depends(get_task_manager),
) -> StatusResponse:
    """
    查询单个任务状态（推荐入口）

    2026-08-20 优化：一次数据库查询完成验证和响应构造，消除双查询问题
    """
    # 一次查询：通过 novel_service 获取任务元数据并验证归属
    try:
        task = novel_service.get_task(task_id)
    except NovelNotFoundError:
        raise HTTPException(status_code=404, detail="任务不存在") from None

    # 验证任务属于指定小说
    if task.get("novel_id") != novel_id:
        raise HTTPException(status_code=404, detail="任务不存在或不属于该小说")

    # 获取完整运行状态（通过 run_id 进行第二次查询，但仅当需要完整状态时）
    session_factory = get_session_factory()
    with session_factory() as session:
        try:
            run_id = task_id_to_run_id(task_id, session.connection())
        except (TaskIDNotFoundError, ValueError):
            # 任务元数据存在但运行记录不存在，返回待机状态
            return StatusResponse(
                novel_id=novel_id,
                task_id=task_id,
                status=TaskStatus.PENDING,
                progress=0.0,
            )

        run_repo = RunRepository(session)
        run = run_repo.get_run(run_id)

    if run is None:
        return StatusResponse(
            novel_id=novel_id,
            task_id=task_id,
            status=TaskStatus.PENDING,
            progress=0.0,
        )

    # 构建完整响应
    mapped_status = _map_status_to_task_status(run["status"])
    return StatusResponse(
        novel_id=novel_id,
        task_id=task_id,
        status=mapped_status,
        progress=run.get("progress", 0.0),
        stage=run.get("stage"),
        sub_stage=run.get("sub_stage"),
        current=run.get("current"),
        total=run.get("total"),
        message=run.get("message"),
        llm_outputs=None,
        error=run.get("error"),
        started_at=run.get("started_at"),
        completed_at=run.get("completed_at"),
    )


@router.post("/{novel_id}/tasks/{task_id}/cancel")
async def cancel_task(
    novel_id: str,
    task_id: str,
    task_manager: TaskManager = Depends(get_task_manager),
    novel_service: NovelService = Depends(get_novel_service),
):
    """
    取消正在运行的分析任务

    说明: 设置取消信号，任务将在当前阶段完成后停止
    """
    task_application_service = TaskApplicationService(novel_service, task_manager)
    return await task_application_service.cancel_task(novel_id, task_id)


@router.post("/{novel_id}/tasks/batch-delete", response_model=BatchDeleteTasksResponse)
async def batch_delete_tasks(
    novel_id: str,
    request: BatchDeleteTasksRequest,
    novel_service: NovelService = Depends(get_novel_service),  # noqa: B008
    task_manager: TaskManager = Depends(get_task_manager),  # noqa: B008
) -> BatchDeleteTasksResponse:
    """
    批量删除指定的分析任务

    即使部分删除失败，也会继续处理其他任务
    """
    deleted_ids: list[str] = []
    failed_ids: list[dict[str, str]] = []

    for task_id in request.task_ids:
        try:
            task_application_service = TaskApplicationService(novel_service, task_manager)
            await task_application_service.delete_task(novel_id, task_id)
            deleted_ids.append(task_id)
            logger.info(f"Batch delete: task {task_id} deleted successfully")
        except HTTPException as exc:
            failed_ids.append({"task_id": task_id, "reason": str(exc.detail)})
            logger.warning(f"Batch delete: task {task_id} rejected - {exc.detail}")
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

