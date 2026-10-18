"""
API 统一依赖注入模块

说明: 统一 FastAPI 依赖注入函数，替代手动 session 管理。任务与运行的读写、编排与应用
      服务由 src/workflows 装配（见 src/workflows/dependencies.py），本层只取实例；
      work 队列的运行态类型不出现在 api。
"""

from __future__ import annotations

from collections.abc import Generator
from pathlib import Path
from typing import Annotated, Any

from fastapi import Depends, Query

from src.api.exceptions import AnalysisNotCompleteError, NovelNotFoundError
from src.api.services.metrics_service import MetricsService, get_metrics_service
from src.storage import Storage, get_storage_factory
from src.workflows import dependencies as workflows_deps
from src.workflows.novels import NovelService
from src.workflows.tasks import TaskService

READABLE_RUN_STATUSES = ("completed",)


def require_run_for_novel(session: Storage, novel_id: str, run_id: str) -> dict[str, Any]:
    """校验 run_id 存在且属于当前小说"""
    run_repo = session.runs
    session.reads.api_dependencies_require_run_for_novel_1(run_id)
    run = run_repo.get_run(run_id)
    if not run:
        raise NovelNotFoundError(novel_id=novel_id, message=f"运行记录不存在: {run_id}")
    if run.get("novel_id") != novel_id:
        from src.storage.id_mapping import run_id_to_task_id

        actual_task_id = run_id_to_task_id(run_id, session)
        raise NovelNotFoundError(novel_id=novel_id, message=f"任务 {actual_task_id} 不属于小说 {novel_id}")
    return run


def require_readable_run_status(run: dict[str, Any]) -> None:
    if run["status"] not in READABLE_RUN_STATUSES:
        raise AnalysisNotCompleteError(f"分析未完成，当前状态: {run['status']}", run_status=run["status"])


_upload_dir = Path("data/uploads")
_novel_service_instance: NovelService | None = None


def invalidate_metrics_cache(run_id: str) -> None:
    """
    run 成功收口时失效聚合指标缓存

    说明: 缓存归读侧所有，装配时登记给编排层，避免执行层反向依赖 api
    """
    get_metrics_service().invalidate_cache(run_id)


workflows_deps.configure(run_completed_callback=invalidate_metrics_cache)
__all__ = [
    "MetricsService",
    "get_db_session",
    "get_metrics_service",
    "get_novel_service",
    "get_task_manager",
    "get_task_service",
    "invalidate_metrics_cache",
    "require_readable_run_status",
    "require_run_for_novel",
    "resolve_run_id",
]


def _get_novel_service_instance() -> NovelService:
    """获取 NovelService 单例实例"""
    global _novel_service_instance
    if _novel_service_instance is None:
        _novel_service_instance = NovelService(
            _upload_dir,
            task_service=workflows_deps.get_task_service(),
            task_application_service=workflows_deps.get_task_application_service(),
        )
    return _novel_service_instance


def get_novel_service() -> NovelService:
    """
    获取小说服务单例"""
    return _get_novel_service_instance()


def get_task_service() -> TaskService:
    """获取任务读写服务单例（运行生命周期入口）"""
    return workflows_deps.get_task_service()


def get_task_manager():
    """获取队列运行态单例（仅供启动恢复等装配点转交）"""
    return workflows_deps.get_task_manager()


def get_db_session() -> Generator[Storage, None, None]:
    """提供普通 Storage 入口，连接生命周期由各操作管理"""
    session_factory = get_storage_factory()
    session = session_factory()
    yield session


async def resolve_run_id(
    task_id: Annotated[str, Query(..., description="分析任务ID（8位短UUID）")],
    task_service: Annotated[TaskService, Depends(get_task_service)],
) -> str:
    """
    从 task_id 解析出 run_id，无效时抛 NovelNotFoundError (404)

    Args:
        task_id: 独立生成并精确映射到运行的 8 位任务 ID
        task_service: 任务读写服务实例

    Returns:
        完整的 run_id 字符串

    Raises:
        NovelNotFoundError: 当 task_id 无效或找不到对应运行记录时
    """
    task = task_service.get_run_by_task_id(task_id)
    if task is None:
        task = task_service.load_task(task_id)
    if task is None:
        raise NovelNotFoundError(f"任务不存在: {task_id}")
    run_id = task.get("run_id")
    if run_id is None:
        task_from_db = task_service.load_task(task_id)
        if task_from_db is not None:
            run_id = task_from_db.get("run_id")
    if run_id is None:
        raise NovelNotFoundError(f"任务数据不完整: {task_id}")
    return run_id
