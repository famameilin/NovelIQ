"""
运行管理协议接口

使用 RunRecord/RepositoryValue 替代过宽的动态字典
"""

from __future__ import annotations

from datetime import datetime
from typing import Protocol, runtime_checkable

from .types import RepositoryValue, RunRecord


@runtime_checkable
class RunRepositoryProtocol(Protocol):
    """
    分析运行管理接口

    管理分析运行的创建、查询和状态更新
    """

    def create_run(
        self,
        novel_id: str,
        source_path: str | None = None,
        title: str | None = None,
        author: str | None = None,
        run_id: str | None = None,
        task_kind: str = "analysis",
        request_payload: dict[str, RepositoryValue] | None = None,
    ) -> str:
        """
        创建新的分析运行记录

        Args:
            novel_id: 小说ID
            source_path: 源文件路径
            title: 小说标题

        Returns:
            运行ID
        """
        ...

    def get_run(self, run_id: str) -> RunRecord | None:
        """
        获取运行记录

        Args:
            run_id: 运行ID

        Returns:
            运行记录字典，不存在则返回 None
        """
        ...

    def update_run_status(self, run_id: str, status: str) -> None:
        """
        更新运行状态

        Args:
            run_id: 运行ID
            status: 新状态
        """
        ...

    def get_latest_run(self, novel_id: str) -> RunRecord | None:
        """
        获取指定小说的最新运行记录

        Args:
            novel_id: 小说ID

        Returns:
            最新运行记录字典，不存在则返回 None
        """
        ...

    def get_runs_by_novel(self, novel_id: str) -> list[RunRecord]:
        """获取指定小说的所有运行记录"""
        ...

    def get_by_status(self, status: str) -> list[RunRecord]:
        """按状态查询任务"""
        ...

    def get_running_tasks(self) -> list[RunRecord]:
        """获取所有运行中的任务"""
        ...

    def get_pending_tasks(self) -> list[RunRecord]:
        """获取所有 pending 任务"""
        ...

    def update_run_task_fields(
        self,
        run_id: str,
        *,
        status: str | None = None,
        progress: float | None = None,
        stage: str | None = None,
        sub_stage: str | None = None,
        current: int | None = None,
        total: int | None = None,
        message: str | None = None,
        error: str | None = None,
        task_kind: str | None = None,
        request_payload: dict[str, RepositoryValue] | None = None,
        cancel_requested: bool | None = None,
        worker_id: str | None = None,
        heartbeat_at: datetime | None = None,
        started_at: datetime | None = None,
        completed_at: datetime | None = None,
    ) -> None:
        """批量更新任务运行态字段"""
        ...
