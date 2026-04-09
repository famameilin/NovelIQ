from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
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
    "cancelling": TaskStatus.CANCELLING,
    "cancelled": TaskStatus.CANCELLED,
}


def _map_status_to_task_status(status: str) -> TaskStatus:
    """
    将数据库状态字符串映射为TaskStatus枚举

    创建时间: 2026-03-26
    创建者: TraeAI
    任务: 修复代码异味，提取重复的状态映射逻辑
    """
    return _STATUS_MAP.get(status, TaskStatus.PENDING)


def _get_task_detail_from_db(task_id: str) -> dict[str, Any] | None:
    """
    从数据库获取任务详情

    创建时间: 2026-03-26
    创建者: TraeAI
    任务: 修复代码异味，提取数据库查询逻辑

    修改时间: 2026-04-09
    修改者: GLM-5
    任务: sse-architecture-review
    修改内容: 返回完整 run 记录而非仅 TaskStatus，使 DB fallback 也能恢复 stage/progress

    当任务不在内存中时，从数据库查询状态
    返回: run 记录字典（含 status/progress/stage），不存在则返回 None
    """
    session_factory = get_session_factory()
    with session_factory() as session:
        try:
            run_id = task_id_to_run_id(task_id, session.connection())
        except (TaskIDNotFoundError, ValueError):
            return None
        run_repo = RunRepository(session)
        return run_repo.get_run(run_id)


router = APIRouter(prefix="/novels", tags=["analysis"])

_task_manager = TaskManager()
_task_manager.set_db_session_factory(lambda: get_session_factory()())


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


@router.post("/{novel_id}/tasks/{task_id}/cancel")
async def cancel_task(
    novel_id: str,
    task_id: str,
    task_manager: TaskManager = Depends(get_task_manager),
    novel_service: NovelService = Depends(get_novel_service),
):
    """
    取消正在运行的分析任务

    创建时间: 2026-04-07
    创建者: TraeAI
    任务: implement-task-cancellation
    说明: 设置取消信号，任务将在当前阶段完成后停止

    修改时间: 2026-04-07
    修改者: TraeAI
    任务: code-review-fix
    修改内容: 任务不在内存时同步更新 run 表状态，确保数据一致性
    """
    try:
        task = novel_service.get_task(task_id)
    except Exception:
        raise HTTPException(status_code=404, detail="任务不存在") from None

    if task.get("novel_id") != novel_id:
        raise HTTPException(status_code=400, detail="任务不属于该小说")

    task_status = task.get("status", "")
    if task_status in ("completed", "cancelled", "cancelling"):
        raise HTTPException(status_code=400, detail=f"任务已{task_status}，无需取消")
    if task_status == "failed":
        raise HTTPException(status_code=400, detail="任务已失败，无法取消")

    cancelled = task_manager.cancel_task(task_id)

    if cancelled:
        return {"task_id": task_id, "status": "cancelling", "message": "任务将在当前处理单元完成后停止"}

    if task_status in ("pending", "running"):
        novel_service.update_task_status(task_id, "cancelled")

        session_factory = get_session_factory()
        try:
            with session_factory() as session:
                run_id = task_id_to_run_id(task_id, session.connection())
                run_repo = RunRepository(session)
                run_repo.update_run_status(run_id, "cancelled")
                session.commit()
        except (TaskIDNotFoundError, ValueError):
            logger.warning(f"Task {task_id} run_id not found, skipping run table update")
        except Exception as e:
            logger.warning(f"Failed to update run status for cancelled task {task_id}: {e}")

        logger.info(f"Task {task_id} cancelled (not in memory), status updated to cancelled")
        return {"task_id": task_id, "status": "cancelled", "message": "任务已标记为取消"}

    raise HTTPException(status_code=400, detail=f"任务状态为 {task_status}，无法取消")


@router.post("/{novel_id}/tasks/batch-delete", response_model=BatchDeleteTasksResponse)
async def batch_delete_tasks(
    novel_id: str,
    request: BatchDeleteTasksRequest,
    novel_service: NovelService = Depends(get_novel_service),  # noqa: B008
    task_manager: TaskManager = Depends(get_task_manager),  # noqa: B008
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
            try:
                task = novel_service.get_task(task_id)
            except Exception:
                failed_ids.append({"task_id": task_id, "reason": "任务不存在"})
                logger.warning(f"Batch delete task: task {task_id} not found")
                continue

            if task.get("novel_id") != novel_id:
                failed_ids.append({"task_id": task_id, "reason": f"任务不属于小说 {novel_id}"})
                logger.warning(f"Batch delete task: task {task_id} does not belong to novel {novel_id}")
                continue

            # 先取消运行中的任务，再删除
            running_statuses = ("pending", "running", "cancelling")
            if task.get("status") in running_statuses:
                task_manager.cancel_task(task_id)
            # 取消 asyncio.Task，使用 gather + return_exceptions 避免异常泄露
            task_info = task_manager.get_task(task_id)
            if task_info and task_info.asyncio_task and not task_info.asyncio_task.done():
                task_info.asyncio_task.cancel()
                try:
                    import asyncio

                    await asyncio.wait_for(
                        asyncio.gather(task_info.asyncio_task, return_exceptions=True),
                        timeout=5.0,
                    )
                except TimeoutError:
                    logger.warning(
                        f"Batch delete: task {task_id} cancel timed out, "
                        "background coroutine may still be running"
                    )
                except Exception as e:
                    logger.warning(f"Batch delete: unexpected error cancelling task {task_id}: {e}")

            # 先从内存中移除，防止后台协程继续更新已删除的数据
            task_manager.delete_task(task_id)
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

    修改时间: 2026-04-07
    修改者: TraeAI
    任务: implement-task-cancellation
    修改内容: 返回详细进度字段，使 HTTP 轮询与 WebSocket 行为一致
    """
    if task_id:
        task_info = task_manager.get_task(task_id)
        if task_info is None:
            run = _get_task_detail_from_db(task_id)
            if run is None:
                return StatusResponse(
                    novel_id=novel_id,
                    task_id=task_id,
                    status=TaskStatus.PENDING,
                    progress=0.0,
                )
            mapped_status = _map_status_to_task_status(run["status"])
            return StatusResponse(
                novel_id=novel_id,
                task_id=task_id,
                status=mapped_status,
                progress=run.get("progress", 0.0),
                stage=run.get("stage"),
            )
        return StatusResponse(
            novel_id=novel_id,
            task_id=task_id,
            status=task_info.status,
            progress=task_info.progress,
            stage=task_info.stage,
            sub_stage=task_info.sub_stage,
            current=task_info.current,
            total=task_info.total,
            message=task_info.message,
            llm_outputs=task_info.llm_outputs[-20:] if task_info.llm_outputs else None,
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
        run = _get_task_detail_from_db(task_id)
        if run is None:
            return StatusResponse(
                novel_id=novel_id,
                task_id=task_id,
                status=_map_status_to_task_status(task_status),
                progress=0.0,
            )
        return StatusResponse(
            novel_id=novel_id,
            task_id=task_id,
            status=_map_status_to_task_status(run["status"]),
            progress=run.get("progress", 0.0),
            stage=run.get("stage"),
        )

    return StatusResponse(
        novel_id=novel_id,
        task_id=task_id,
        status=task_info.status,
        progress=task_info.progress,
        stage=task_info.stage,
        sub_stage=task_info.sub_stage,
        current=task_info.current,
        total=task_info.total,
        message=task_info.message,
        llm_outputs=task_info.llm_outputs[-20:] if task_info.llm_outputs else None,
        error=task_info.error,
    )
