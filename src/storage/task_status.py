"""任务生命周期状态词表

取值即 `analysis_runs.status` 列的取值域。队列的运行态写回（src/work）、
编排（src/workflows）与 api 的响应模型共用这一份词表，避免同一套状态在多处各写一份。
"""

from __future__ import annotations

from enum import StrEnum


class TaskStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    CANCELLING = "cancelling"
    CANCELLED = "cancelled"
    COMPLETED = "completed"
    FAILED = "failed"
