"""
API 统一依赖注入模块

说明: 统一 FastAPI 依赖注入函数，替代手动 session 管理
"""

from __future__ import annotations

from collections.abc import Generator
from pathlib import Path
from typing import Annotated, Any

from fastapi import Depends, Query
from sqlalchemy.orm import Session

from src.api.exceptions import AnalysisNotCompleteError, NovelNotFoundError
from src.api.services.metrics_service import MetricsService
from src.api.services.novel_service import NovelService
from src.api.services.task_manager import TaskManager
from src.storage.db import get_session_factory
from src.storage.repositories import RunRepository

# 结果查询端点统一的可读状态白名单（results / linguistic / tabs 共用）
READABLE_RUN_STATUSES = ("completed",)


def require_run_for_novel(session: Session, novel_id: str, run_id: str) -> dict[str, Any]:
    """校验 run_id 存在且属于当前小说"""
    run_repo = RunRepository(session)
    run = run_repo.get_run(run_id)
    if not run:
        raise NovelNotFoundError(novel_id=novel_id, message=f"运行记录不存在: {run_id}")

    if run.get("novel_id") != novel_id:
        actual_task_id = run_id[:8] if len(run_id) >= 8 else run_id
        raise NovelNotFoundError(
            novel_id=novel_id,
            message=f"任务 {actual_task_id} 不属于小说 {novel_id}",
        )

    return run


def require_readable_run_status(run: dict[str, Any]) -> None:
    if run["status"] not in READABLE_RUN_STATUSES:
        raise AnalysisNotCompleteError(
            f"分析未完成，当前状态: {run['status']}",
            run_status=run["status"],
        )

# 模块级别的单例
_upload_dir = Path("data/uploads")
_novel_service_instance: NovelService | None = None
_task_manager = TaskManager()
_task_manager.set_db_session_factory(lambda: get_session_factory()())
_metrics_service_instance: MetricsService | None = None


def _get_novel_service_instance() -> NovelService:
    """获取 NovelService 单例实例"""
    global _novel_service_instance
    if _novel_service_instance is None:
        _novel_service_instance = NovelService(_upload_dir)
    return _novel_service_instance


def get_novel_service() -> NovelService:
    """
    获取小说服务的依赖函数

    Returns:
        NovelService 实例
    """
    return _get_novel_service_instance()


def get_task_manager() -> TaskManager:
    """
    获取任务执行缓存管理器单例

    说明: TaskManager 仍只负责执行缓存；这里统一暴露依赖入口，
          避免 novel/task 删除路径各自维护不同的单例来源
    """
    return _task_manager


def get_metrics_service() -> MetricsService:
    """
    获取聚合指标服务单例

    说明: MetricsService 提供聚合指标的统一获取和缓存，
          消除重复计算和代码重复
    """
    global _metrics_service_instance
    if _metrics_service_instance is None:
        _metrics_service_instance = MetricsService(cache_ttl=300)
    return _metrics_service_instance


def get_db_session() -> Generator[Session, None, None]:
    """
    获取数据库会话的依赖函数

    使用 yield 模式确保 session 在使用后自动关闭
    这是 FastAPI 推荐的依赖注入模式

    Yields:
        SQLAlchemy Session 实例
    """
    session_factory = get_session_factory()
    session = session_factory()
    try:
        yield session
    finally:
        session.close()


async def resolve_run_id(
    task_id: Annotated[str, Query(..., description="分析任务ID（8位短UUID）")],
    novel_service: Annotated[NovelService, Depends(get_novel_service)],
) -> str:
    """
    从 task_id 解析出 run_id，无效时抛 NovelNotFoundError (404)

    Args:
        task_id: 分析任务ID（run_id 的前8位）
        novel_service: 小说服务实例

    Returns:
        完整的 run_id 字符串

    Raises:
        NovelNotFoundError: 当 task_id 无效或找不到对应运行记录时
    """
    task = novel_service.get_run_by_task_id(task_id)
    if task is None:
        task = novel_service._load_task_from_db(task_id)
    if task is None:
        raise NovelNotFoundError(f"任务不存在: {task_id}")

    run_id = task.get("run_id")
    if run_id is None:
        task_from_db = novel_service._load_task_from_db(task_id)
        if task_from_db is not None:
            run_id = task_from_db.get("run_id")
    if run_id is None:
        raise NovelNotFoundError(f"任务数据不完整: {task_id}")

    return run_id
