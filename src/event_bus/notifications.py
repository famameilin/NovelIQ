"""分析过程的中立通知事实"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Literal

StreamEventAction = Literal[
    "start",
    "progress",
    "complete",
    "output",
    "thinking",
    "tool_call",
    "work_reset",
    "work_saved",
    "chapter_reset",
    "activity",
    "stage_state",
    "capacity",
    "task_state",
]
"""StreamEvent.action 的合法值"""


@dataclass
class StreamEvent:
    """真实过程通知，未记录的身份与计数保持空值"""

    action: StreamEventAction
    stage: str = ""
    sub_stage: str = ""
    chapter_id: int | None = None
    invocation_id: str | None = None
    message_id: str | None = None
    stream_id: str | None = None
    current: int | None = None
    total: int | None = None
    percent: float | None = None
    sub_percent: float | None = None
    content: str = ""
    message: str = ""
    status: str | None = None

    run_id: str = ""
    work_id: str = ""
    model_id: str = ""
    reservation_id: str = ""
    activity: str = ""
    unit: str = ""
    tool_call_id: str = ""
    case_id: str | None = None
    details: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        """保留空值，模型流必须有真实流身份"""
        if self.action in {"output", "thinking", "tool_call"} and not self.stream_id:
            raise ValueError("LLM 流事件缺少 stream_id")
        return asdict(self)
