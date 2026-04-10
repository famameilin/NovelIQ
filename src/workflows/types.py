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
  - StreamEmitter Protocol 替代 IProgressCallback + stream_callback 双回调
  - StreamEmitter.emit() 接收 StreamEvent 统一格式
"""

from __future__ import annotations

from typing import Protocol

from src.api.models.events import StreamEvent


class StreamEmitter(Protocol):
    """
    统一事件发送器接口（Protocol 形式，用于类型标注）

    替代原来的 IProgressCallback + stream_callback 双回调模式。
    所有层通过同一个 emit 方法发送事件，Event Bus 负责补全上下文和发送。

    注意: 实际使用中，emitter 参数多为 Callable[[StreamEvent], Awaitable[None]]
    形式（闭包），而非实现此 Protocol 的类实例。两者签名不同但语义等价：
    - Protocol: obj.emit(event)
    - Callable: emitter(event)

    action 取值:
        start    — 阶段/phase/chunk 开始
        progress — 增量进度
        complete — 阶段/phase/chunk 完成
        output   — LLM 正式输出
        thinking — LLM 思考过程输出
    """

    async def emit(self, event: StreamEvent) -> None: ...
