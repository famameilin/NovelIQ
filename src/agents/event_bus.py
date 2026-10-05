"""进程内异步事件总线：调度闭环的发布/订阅通道

2026-10-03 事件驱动调度：模型池是调度中心——开局按空位举行多次选举并发布
"election" 消息；任务队列订阅 "election" 依次启动队头任务；任务完成发布
"task_completed"，模型池订阅后继续选举并发布 "election"。

单事件循环内运行；订阅队列按事件循环惰性重建（进程内单例可安全跨测试）。
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator


class EventBus:
    """主题化发布/订阅：publish 同步入队，subscribe 返回异步迭代器"""

    def __init__(self) -> None:
        self._subs: dict[str, list[asyncio.Queue[None]]] = {}
        self._loop: asyncio.AbstractEventLoop | None = None

    def _queue(self) -> asyncio.Queue[None]:
        loop = asyncio.get_running_loop()
        if self._loop is not loop:
            self._subs = {}
            self._loop = loop
        return asyncio.Queue()

    def reset(self) -> None:
        """清空全部订阅与事件循环绑定（测试隔离用）"""
        self._subs = {}
        self._loop = None

    def publish(self, topic: str) -> None:
        """向主题的所有订阅者投递一条消息（无订阅者即丢弃）"""
        if self._loop is None or self._loop.is_closed():
            return
        for queue in self._subs.get(topic, []):
            queue.put_nowait(None)

    def subscribe(self, topic: str) -> asyncio.Queue[None]:
        queue = self._queue()
        self._subs.setdefault(topic, []).append(queue)
        return queue

    def unsubscribe(self, topic: str, queue: asyncio.Queue[None]) -> None:
        """从主题订阅列表移除队列"""
        subscribers = self._subs.get(topic)
        if subscribers is not None and queue in subscribers:
            subscribers.remove(queue)

    async def events(self, topic: str) -> AsyncIterator[None]:
        """持续消费主题消息；协程退出时自动退订"""
        queue = self.subscribe(topic)
        try:
            while True:
                await queue.get()
                yield None
        finally:
            self.unsubscribe(topic, queue)


EVENT_BUS = EventBus()
