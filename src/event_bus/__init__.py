"""进程内消息投递与定向回执，不承担业务状态和数据库事务"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any
from uuid import uuid4


@dataclass(frozen=True, slots=True)
class Message:
    """消息身份用于去重，请求身份与执行身份共同限定回执所属"""

    topic: str
    source: str
    target: str
    run_id: str
    work_id: str = ""
    invocation_id: str = ""
    payload: Any = None
    message_id: str = field(default_factory=lambda: uuid4().hex)
    request_id: str = field(default_factory=lambda: uuid4().hex)


class MissingSubscriber(RuntimeError):
    """必需接收者尚未建立，禁止静默丢弃关键消息"""


class EventBus:
    """单事件循环投递；请求仅由指定组件处理，回执沿原调用返回"""

    def __init__(self) -> None:
        self._subs: dict[str, list[asyncio.Queue[Message]]] = {}
        self._handlers: dict[tuple[str, str], Callable[[Message], Awaitable[Any]]] = {}
        self._requests: dict[tuple[str, ...], asyncio.Task[Any]] = {}
        self._loop: asyncio.AbstractEventLoop | None = None

    def _bind_loop(self) -> None:
        loop = asyncio.get_running_loop()
        if self._loop is not loop:
            if self._loop is not None:
                self.reset()
            self._loop = loop

    def reset(self) -> None:
        self._subs.clear()
        self._handlers.clear()
        self._requests.clear()
        self._loop = None

    def handle(self, topic: str, target: str, handler: Callable[[Message], Awaitable[Any]]) -> None:
        """组件在派发之前注册，重复注册属于调用方配置错误"""
        # 组件可以在同步装配阶段注册，首次异步投递才绑定事件循环
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            pass
        else:
            self._bind_loop()
        key = (topic, target)
        if key in self._handlers:
            raise ValueError(f"重复消息处理器: {key}")
        self._handlers[key] = handler

    def unhandle(self, topic: str, target: str) -> None:
        self._handlers.pop((topic, target), None)

    def has_handler(self, topic: str, target: str) -> bool:
        return (topic, target) in self._handlers

    async def deliver(self, message: Message) -> Any:
        """交付通知但不缓存回执，背压只等待接收方接管"""
        self._bind_loop()
        handler = self._handlers.get((message.topic, message.target))
        if handler is None:
            raise MissingSubscriber(f"未注册必需接收者: {message.topic}/{message.target}")
        return await handler(message)

    def release_run(self, run_id: str) -> None:
        """只回收指定运行已经结束的业务请求"""
        self._requests = {key: task for key, task in self._requests.items() if key[3] != run_id or not task.done()}

    async def request(self, message: Message) -> Any:
        """同一请求的重复投递共用结果；取消调用方不取消已开始的保存"""
        self._bind_loop()
        handler = self._handlers.get((message.topic, message.target))
        if handler is None:
            raise MissingSubscriber(f"未注册必需接收者: {message.topic}/{message.target}")
        key = (
            message.source,
            message.target,
            message.topic,
            message.run_id,
            message.work_id,
            message.invocation_id,
            message.request_id,
        )
        task = self._requests.get(key)
        if task is None:

            async def deliver() -> Any:
                return await handler(message)

            task = asyncio.create_task(deliver())
            self._requests[key] = task
        return await asyncio.shield(task)

    def publish(self, message: Message) -> None:
        self._bind_loop()
        subscribers = self._subs.get(message.topic, [])
        if not subscribers:
            raise MissingSubscriber(f"未订阅必需主题: {message.topic}")
        for queue in subscribers:
            queue.put_nowait(message)

    def subscribe(self, topic: str) -> asyncio.Queue[Message]:
        self._bind_loop()
        queue: asyncio.Queue[Message] = asyncio.Queue()
        self._subs.setdefault(topic, []).append(queue)
        return queue

    def unsubscribe(self, topic: str, queue: asyncio.Queue[Message]) -> None:
        subscribers = self._subs.get(topic, [])
        if queue in subscribers:
            subscribers.remove(queue)

    async def events(self, topic: str) -> AsyncIterator[Message]:
        queue = self.subscribe(topic)
        try:
            while True:
                yield await queue.get()
        finally:
            self.unsubscribe(topic, queue)


EVENT_BUS = EventBus()
