from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from loguru import logger

from src.api.exceptions import NovelNotFoundError
from src.api.models.tasks import (
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
from src.workflows.application import TaskApplicationService
from src.workflows.dependencies import get_analysis_service, get_task_application_service, get_task_service
from src.workflows.schemas import ReanalyzeRequest
from src.workflows.service import AnalysisService
from src.workflows.tasks import TaskService

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
    analysis_service: AnalysisService = Depends(get_analysis_service),
) -> CreateTaskResponse:
    """
    创建并启动一个新的分析任务
    """
    task_id = await analysis_service.create_task_and_start(novel_id)
    return CreateTaskResponse(novel_id=novel_id, task_id=task_id, message="分析任务已创建并启动")


@router.post("/{novel_id}/tasks/{task_id}/resume", response_model=ResumeTaskResponse)
async def resume_task(
    novel_id: str,
    task_id: str,
    task_application_service: TaskApplicationService = Depends(get_task_application_service),
) -> ResumeTaskResponse:
    """
    继续执行指定的 pending/failed 任务
    """
    resumed_task_id = await task_application_service.resume_task(novel_id, task_id)
    return ResumeTaskResponse(novel_id=novel_id, task_id=resumed_task_id, message="分析任务已继续执行")


@router.post("/{novel_id}/reanalyze", response_model=ReanalyzeResponse)
async def start_reanalysis(
    novel_id: str,
    request: ReanalyzeRequest | None = None,
    analysis_service: AnalysisService = Depends(get_analysis_service),
) -> ReanalyzeResponse:
    task_id = await analysis_service.start_reanalysis(novel_id, request)
    return ReanalyzeResponse(novel_id=novel_id, task_id=task_id, message="重新分析任务已启动")


@router.get("/{novel_id}/tasks", response_model=TaskListResponse)
async def list_tasks(novel_id: str, task_service: TaskService = Depends(get_task_service)) -> TaskListResponse:
    """
    获取小说的所有任务列表
    """
    tasks = task_service.get_tasks_by_novel(novel_id)
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
    task_application_service: TaskApplicationService = Depends(get_task_application_service),
):
    """
    删除单个分析任务

    删除顺序: DB 状态判断 → 清运行态缓存 → 删 DB 记录 → 删内存缓存
    """
    return await task_application_service.delete_task(novel_id, task_id)


@router.get("/{novel_id}/tasks/{task_id}/status", response_model=StatusResponse)
async def get_task_status(
    novel_id: str,
    task_id: str,
    task_service: TaskService = Depends(get_task_service),
) -> StatusResponse:
    """
    查询单个任务状态

    数据库是唯一真相源，队列运行期持续写回状态到 DB
    """
    try:
        task = task_service.get_task(task_id)
    except NovelNotFoundError:
        raise HTTPException(status_code=404, detail="任务不存在") from None

    if task.get("novel_id") != novel_id:
        raise HTTPException(status_code=404, detail="任务不存在或不属于该小说")

    mapped_status = _map_status_to_task_status(task["status"])
    return StatusResponse(
        novel_id=novel_id,
        task_id=task_id,
        status=mapped_status,
        progress=task.get("progress", 0.0),
        stage=task.get("stage"),
        sub_stage=task.get("sub_stage"),
        current=task.get("current"),
        total=task.get("total"),
        message=task.get("message"),
        llm_outputs=None,
        error=task.get("error"),
        started_at=task.get("started_at"),
        completed_at=task.get("completed_at"),
    )


@router.post("/{novel_id}/tasks/{task_id}/cancel")
async def cancel_task(
    novel_id: str,
    task_id: str,
    task_application_service: TaskApplicationService = Depends(get_task_application_service),
):
    """
    取消正在运行的分析任务：立即停止——停止新派发并中断在飞执行；未完成的 work 不保存
    """
    return await task_application_service.cancel_task(novel_id, task_id)


@router.post("/{novel_id}/tasks/batch-delete", response_model=BatchDeleteTasksResponse)
async def batch_delete_tasks(
    novel_id: str,
    request: BatchDeleteTasksRequest,
    task_application_service: TaskApplicationService = Depends(get_task_application_service),
) -> BatchDeleteTasksResponse:
    """
    批量删除指定的分析任务

    即使部分删除失败，也会继续处理其他任务
    """
    deleted_ids: list[str] = []
    failed_ids: list[dict[str, str]] = []

    for task_id in request.task_ids:
        try:
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
