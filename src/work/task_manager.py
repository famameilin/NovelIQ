"任务执行对象与短期模型输出缓冲"

from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass, field

from src.storage import Storage
from src.storage.id_mapping import task_id_to_run_id


@dataclass
class TaskInfo:
    "当前进程持有的执行对象"

    task_id: str
    llm_outputs: list[str] = field(default_factory=list)
    asyncio_task: asyncio.Task | None = None


class TaskManager:
    "维护异步执行对象并写入任务状态"

    def __init__(self, run_completed_callback: Callable[[str], None] | None = None):
        self._tasks: dict[str, TaskInfo] = {}
        self._run_completed_callback = run_completed_callback
        self._session_factory: Callable[[], Storage] | None = None

    def set_db_session_factory(self, factory: Callable[[], Storage]) -> None:
        self._session_factory = factory

    def create_task(self, task_id: str, novel_id: str) -> TaskInfo:
        task = TaskInfo(task_id)
        self._tasks[task_id] = task
        return task

    def get_task(self, task_id: str) -> TaskInfo | None:
        return self._tasks.get(task_id)

    def update_task(self, task_id: str, *, status: str) -> None:
        if self._session_factory is None:
            raise RuntimeError("任务存储尚未初始化")
        session = self._session_factory()
        session.runs.update_run_task_fields(task_id_to_run_id(task_id, session), status=status)

    def cancel_completed_task(self, task_id: str, error: str | None = None) -> None:
        self.update_task(task_id, status="cancelled")

    def delete_task(self, task_id: str) -> bool:
        return self._tasks.pop(task_id, None) is not None

    def cancel_task(self, task_id: str) -> bool:
        task = self.get_task(task_id)
        if task is None or task.asyncio_task is None or task.asyncio_task.done():
            return False
        return task.asyncio_task.cancel()

    def append_llm_output(self, task_id: str, content: str) -> None:
        task = self.get_task(task_id)
        if task:
            task.llm_outputs.append(content)
            del task.llm_outputs[:-100]

    def store_asyncio_task(self, task_id: str, asyncio_task: asyncio.Task) -> None:
        self._tasks[task_id].asyncio_task = asyncio_task

    def notify_run_completed(self, run_id: str) -> None:
        if self._run_completed_callback:
            self._run_completed_callback(run_id)

    async def shutdown(self) -> None:
        running = [
            item.asyncio_task for item in self._tasks.values() if item.asyncio_task and not item.asyncio_task.done()
        ]
        for task in running:
            task.cancel()
        await asyncio.gather(*running, return_exceptions=True)
        self._tasks.clear()

    def reset_for_testing(self) -> None:
        for item in self._tasks.values():
            if item.asyncio_task and not item.asyncio_task.done():
                item.asyncio_task.cancel()
        self._tasks.clear()
