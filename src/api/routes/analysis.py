from __future__ import annotations

from fastapi import APIRouter, Depends
from loguru import logger

from src.api.exceptions import AnalysisError
from src.api.models.requests import AnalyzeRequest, ReanalyzeRequest
from src.api.models.responses import (
    AnalyzeResponse,
    BatchDeleteTasksRequest,
    BatchDeleteTasksResponse,
    ReanalyzeResponse,
    StatusResponse,
    TaskInfoResponse,
    TaskListResponse,
    TaskStatus,
)
from src.api.routes.novels import get_novel_service
from src.api.services.analysis_service import AnalysisService
from src.api.services.novel_service import NovelService
from src.api.services.task_manager import TaskManager
from src.storage.db import get_session_factory
from src.storage.id_mapping import TaskIDNotFoundError, task_id_to_run_id
from src.storage.repositories import RunRepository

_STATUS_MAP: dict[str, TaskStatus] = {
    "completed": TaskStatus.COMPLETED,
    "running": TaskStatus.RUNNING,
    "pending": TaskStatus.PENDING,
    "failed": TaskStatus.FAILED,
}


def _map_status_to_task_status(status: str) -> TaskStatus:
    """
    将数据库状态字符串映射为TaskStatus枚举

    创建时间: 2026-03-26
    创建者: TraeAI
    任务: 修复代码异味，提取重复的状态映射逻辑
    """
    return _STATUS_MAP.get(status, TaskStatus.PENDING)


def _get_task_status_from_db(task_id: str) -> TaskStatus:
    """
    从数据库获取任务状态

    创建时间: 2026-03-26
    创建者: TraeAI
    任务: 修复代码异味，提取数据库查询逻辑

    当任务不在内存中时，从数据库查询状态
    返回: TaskStatus枚举值
    """
    session_factory = get_session_factory()
    with session_factory() as session:
        try:
            run_id = task_id_to_run_id(task_id, session.connection())
        except (TaskIDNotFoundError, ValueError):
            return TaskStatus.PENDING
        run_repo = RunRepository(session)
        run = run_repo.get_run(run_id)
        if run:
            return _map_status_to_task_status(run["status"])
        return TaskStatus.PENDING


router = APIRouter(prefix="/novels", tags=["analysis"])

_task_manager = TaskManager()


def get_task_manager() -> TaskManager:
    return _task_manager


@router.post("/{novel_id}/analyze", response_model=AnalyzeResponse)
async def start_analysis(
    novel_id: str,
    request: AnalyzeRequest | None = None,
    novel_service: NovelService = Depends(get_novel_service),
    task_manager: TaskManager = Depends(get_task_manager),
) -> AnalyzeResponse:
    analysis_service = AnalysisService(novel_service, task_manager)
    task_id = await analysis_service.start_analysis(novel_id, request)
    return AnalyzeResponse(novel_id=novel_id, task_id=task_id)


@router.post("/{novel_id}/reanalyze", response_model=ReanalyzeResponse)
async def start_reanalysis(
    novel_id: str,
    request: ReanalyzeRequest | None = None,
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
    novel_id: str, request: BatchDeleteTasksRequest, novel_service: NovelService = Depends(get_novel_service)
) -> BatchDeleteTasksResponse:
    """
    批量删除任务

    创建时间: 2026-03-19
    创建者: TraeAI
    任务: 新增批量删除功能

    批量删除指定的分析任务。
    即使部分删除失败，也会继续处理其他任务。
    """
    deleted_ids: list[str] = []
    failed_ids: list[dict[str, str]] = []

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
    task_id: str | None = None,
    novel_service: NovelService = Depends(get_novel_service),
    task_manager: TaskManager = Depends(get_task_manager),
) -> StatusResponse:
    """
    查询分析任务状态

    创建时间: 2026-03-12
    创建者: Claude
    任务: 添加task_id参数支持
    说明: task_id非必须，但有多个task时必须提供

    修改时间: 2026-03-26
    修改者: TraeAI
    任务: 修复代码异味
    修改内容:
    - 移除函数内导入，使用模块顶部导入
    - 提取状态映射逻辑为辅助函数
    - 提取数据库查询逻辑为辅助函数
    """
    if task_id:
        task_info = task_manager.get_task(task_id)
        if task_info is None:
            task_status = _get_task_status_from_db(task_id)
            return StatusResponse(
                novel_id=novel_id,
                task_id=task_id,
                status=task_status,
                progress=100.0 if task_status == TaskStatus.COMPLETED else 0.0,
                stage="completed" if task_status == TaskStatus.COMPLETED else "unknown",
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
        mapped_status = _map_status_to_task_status(task_status)
        return StatusResponse(
            novel_id=novel_id,
            task_id=task_id,
            status=mapped_status,
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
