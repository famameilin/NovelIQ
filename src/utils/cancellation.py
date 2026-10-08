"""阶段内取消：取消要立即生效，不等整个阶段跑完

分析取消的入口是 `cancel` 接口（DB 先落 cancelling，再置内存取消信号），
编排器只在阶段之间检查取消——长阶段（LTP 全书推理、段落向量、LDA 推断、
诊断 Agent 取证）会拖到阶段结束才响应。这里补上阶段内的响应手段：

- `run_cancellable`：事件循环内可中断的等待（诊断 Agent 的图调用）直接中断，
  与 work 队列 `agent.cancel` 同一语义；
- `check_cancelled`：线程化的 CPU/DB 重活不能安全硬中断（`asyncio.to_thread`
  的工作线程不受取消影响，可能仍在写编排器 session），按处理单元边界检查。

取消命中统一抛 `asyncio.CancelledError`，交给既有的 `handle_cancel` 收口落
`cancelled` 终态——不新增取消专用事务，也不把取消当失败。
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable

CANCEL_MESSAGE = "分析已取消"


def check_cancelled(is_cancelled: Callable[[], bool] | None) -> None:
    """处理单元边界检查取消；命中即抛出与 work 队列一致的取消信号"""
    if is_cancelled is not None and is_cancelled():
        raise asyncio.CancelledError(CANCEL_MESSAGE)


async def run_cancellable[T](
    awaitable: Awaitable[T],
    is_cancelled: Callable[[], bool] | None,
    *,
    poll_seconds: float = 0.2,
) -> T:
    """等待可能很长的可中断操作，取消信号到达即中断这次等待

    不在这里做业务回滚：调用方按既有取消路径收口，未被取消时原样返回结果
    或抛出原异常。
    """
    if is_cancelled is None:
        return await awaitable

    task = asyncio.ensure_future(awaitable)
    try:
        while True:
            done, _ = await asyncio.wait({task}, timeout=poll_seconds)
            if done:
                return task.result()
            if is_cancelled():
                raise asyncio.CancelledError(CANCEL_MESSAGE)
    finally:
        if not task.done():
            task.cancel()
        await asyncio.gather(task, return_exceptions=True)
