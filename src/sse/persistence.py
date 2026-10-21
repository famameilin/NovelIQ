"""持久 SSE 消息的可见性查询，游标分配与原始消息写入委托 storage

消息按 agent_outbox 宽表列读取（run/章节/事件类型与实际发出的字节），重放不按当前业务状态重建。
"""

from __future__ import annotations

import json
from typing import Any


class SseMessageRepository:
    """只管理 SSE 重放与展示状态，不读取 work 业务事务或审计记录"""

    def __init__(self, storage_factory):
        self.storage_factory = storage_factory

    def reserve_sequence(self, task_id: str, message_id: str) -> int:
        return self.storage_factory().sse.reserve_sequence(task_id, message_id)

    def emit(self, task_id: str, event_type: str, data: dict, *, sequence: int | None = None) -> dict:
        return self.storage_factory().sse.emit(task_id, event_type, data, sequence=sequence)

    def replay(self, task_id: str, after_seq: int, *, limit: int = 128) -> list[dict[str, Any]]:
        storage = self.storage_factory()
        run = storage.runs.get_run_by_task_id(task_id)
        if run is None:
            raise ValueError(f"SSE 任务不存在: {task_id}")
        messages: list[dict[str, Any]] = []
        rows = storage.sse.replay_candidates(run["run_id"], after_seq, 0, {}, set(), limit=limit)
        for row in rows:
            payload = json.loads(bytes(row.emitted_bytes))
            messages.append({"type": payload["type"], "data": payload["data"], "seq": int(row.stream_id)})
        return messages
