"""
创建时间: 2026-03-18
创建者: TraeAI
任务: code-quality-refactor - 拆分protocols.py
说明: 运行管理协议接口
"""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class RunRepositoryProtocol(Protocol):
    """
    分析运行管理接口

    管理分析运行的创建、查询和状态更新。
    """

    def create_run(self, novel_id: str, source_path: str | None, title: str | None) -> str:
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

    def get_run(self, run_id: str) -> dict[str, Any] | None:
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

    def get_latest_run(self, novel_id: str) -> dict[str, Any] | None:
        """
        获取指定小说的最新运行记录

        Args:
            novel_id: 小说ID

        Returns:
            最新运行记录字典，不存在则返回 None
        """
        ...
