"""
工作流共享类型定义

创建时间: 2026-04-08
创建者: TraeAI
任务: 修复 notify_callback 类型定义问题
说明: 定义工作流间共享的类型，如进度回调接口

修改时间: 2026-04-09
修改者: TraeAI
任务: 修复 async notify_callback 类型不匹配
修改内容: 返回类型改为 Awaitable[None]，支持同步和异步回调
"""

from __future__ import annotations

from collections.abc import Awaitable
from typing import Literal, Protocol


class IProgressCallback(Protocol):
    """
    进度回调接口定义

    支持同步和异步回调函数
    """

    def __call__(
        self,
        phase: str,
        status: Literal["start", "progress", "complete"],
        current: int,
        total: int,
        percent: float,
    ) -> Awaitable[None]: ...
