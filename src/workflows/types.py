"""
工作流共享类型定义

创建时间: 2026-04-08
创建者: TraeAI
任务: 修复 notify_callback 类型定义问题
说明: 定义工作流间共享的类型，如进度回调接口

修改时间: 2026-04-09
创建者: GLM-5
任务: refactor/sse-unified-event-bus
修改内容:
  - 新增 StreamEmitter Protocol，替代 IProgressCallback + stream_callback 双回调
  - StreamEmitter.emit() 接收 StreamEvent 统一格式
  - 保留 IProgressCallback 向后兼容（标记 deprecated）
"""

from __future__ import annotations

from collections.abc import Awaitable
from typing import Literal, Protocol

from src.api.models.events import StreamEvent


class StreamEmitter(Protocol):
    """
    统一事件发送器接口

    替代原来的 IProgressCallback + stream_callback 双回调模式。
    所有层通过同一个 emit 方法发送事件，Event Bus 负责补全上下文和发送。

    action 取值:
        start    — 阶段/phase/chunk 开始
        progress — 增量进度
        complete — 阶段/phase/chunk 完成
        output   — LLM 正式输出
        thinking — LLM 思考过程输出
    """

    async def emit(self, event: StreamEvent) -> None: ...


class IProgressCallback(Protocol):
    """
    进度回调接口定义 (deprecated, 保留向后兼容)

    新代码应使用 StreamEmitter 替代。
    """

    def __call__(
        self,
        phase: str,
        status: Literal["start", "progress", "complete"],
        current: int,
        total: int,
        percent: float,
    ) -> Awaitable[None]: ...
