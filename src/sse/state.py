"""SSE 展示重置与 invocation 可见性规则，只解释实际展示消息"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

_TASK_STATE_EVENTS = {
    "stage_start",
    "stage_progress",
    "stage_complete",
    "task_complete",
    "task_error",
    "task_cancelled",
    "task_reset",
}


def display_scope(data: dict[str, Any]) -> str:
    """工作身份优先；诊断等无 work 的展示使用实际阶段作用域"""
    scope = f"{data.get('stage') or ''}:{data.get('chapter_id') or 0}:{data.get('sub_stage') or ''}"
    return str(data.get("work_id") or scope)


@dataclass
class DisplayState:
    """只从实际 SSE 重置消息恢复展示，不读取业务或审计状态"""

    restart_sequence: int = 0
    executions: dict[str, str] = field(default_factory=dict)
    retired: set[tuple[str, str]] = field(default_factory=set)
    execution_chapters: dict[str, int] = field(default_factory=dict)
    chapter_resets: dict[int, int] = field(default_factory=dict)
    suspended: set[str] = field(default_factory=set)

    def accepts(self, event_type: str, data: dict[str, Any], sequence: int | None = None) -> bool:
        if sequence is not None and event_type in _TASK_STATE_EVENTS and sequence < self.restart_sequence:
            return False
        scope, invocation = display_scope(data), str(data.get("invocation_id") or "")
        if (scope, invocation) in self.retired:
            return False
        chapter = int(data.get("chapter_id") or 0)
        if sequence is not None and sequence < self.chapter_resets.get(chapter, 0):
            return False
        if event_type == "work_reset":
            return bool(invocation)
        if scope in self.suspended:
            return False
        current = self.executions.get(scope)
        if data.get("work_id") and current is None:
            return False
        return current is None or invocation == current

    def observe(self, event_type: str, data: dict[str, Any], sequence: int) -> None:
        if event_type == "task_reset":
            self.restart_sequence = max(self.restart_sequence, sequence)
        elif event_type == "chapter_reset":
            chapter = int(data["chapter_id"])
            self.chapter_resets[chapter] = sequence
            for scope, invocation in self.executions.items():
                if self.execution_chapters.get(scope) == chapter:
                    self.retired.add((scope, invocation))
                    self.suspended.add(scope)
        elif event_type == "work_reset":
            scope, invocation = display_scope(data), str(data["invocation_id"])
            previous = self.executions.get(scope)
            if previous and previous != invocation:
                self.retired.add((scope, previous))
            self.executions[scope] = invocation
            self.execution_chapters[scope] = int(data.get("chapter_id") or 0)
            self.suspended.discard(scope)
