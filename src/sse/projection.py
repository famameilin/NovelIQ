"""只归并已持久的通知，输出和执行详情有界保存"""

from __future__ import annotations

from copy import deepcopy
from typing import Any

STAGES = ("preprocess", "annotate", "linguistic", "aggregate", "topic-model", "diagnose")


class AnalysisProjection:
    def __init__(self) -> None:
        self.cursor = 0
        self.run_id = ""
        self.status: str | None = None
        self.stage = ""
        self.error: str | None = None
        self.stages: dict[str, dict[str, Any]] = {}
        self.models: list[dict[str, Any]] = []
        self.seats: list[dict[str, Any]] = []
        self.executions: dict[str, dict[str, Any]] = {}

    def apply(self, event_type: str, data: dict[str, Any], seq: int) -> None:
        if seq <= self.cursor:
            return
        self.cursor = seq
        self.run_id = data.get("run_id") or self.run_id
        stage = data.get("stage") or ""
        if event_type == "task_reset":
            self.status, self.error = "pending", None
        elif event_type in {"task_state", "task_complete", "task_error", "task_cancelled"}:
            self.status = data.get("status")
            self.error = data.get("error") or None
        elif event_type == "capacity":
            self.models = deepcopy(data.get("models", []))
            self.seats = deepcopy(data.get("seats", []))
        elif event_type == "stage_state":
            self.stages[stage] = {**self.stages.get(stage, {}), **data}
            if data.get("status") in {"running", "saving", "failed", "cancelled"}:
                self.stage = stage
        elif event_type == "stage_progress":
            current = self.stages.setdefault(stage, {"stage": stage, "status": "running"})
            current.setdefault("steps", {})[data.get("sub_stage") or "processing"] = deepcopy(data)
        invocation = data.get("invocation_id")
        if not invocation:
            return
        execution = self.executions.setdefault(
            invocation,
            {
                "invocation_id": invocation,
                "output": "",
                "thinking": "",
                "tools": {},
                "truncated": False,
            },
        )
        for key in ("run_id", "work_id", "model_id", "reservation_id", "chapter_id", "case_id", "stage", "sub_stage"):
            if data.get(key) is not None and data.get(key) != "":
                execution[key] = data[key]
        if data.get("details"):
            execution["details"] = deepcopy(data["details"])
        if event_type in {"llm_output", "llm_thinking"}:
            key = "output" if event_type == "llm_output" else "thinking"
            text = execution[key] + (data.get("content") or "")
            execution["truncated"] |= len(text) > 8192
            execution[key] = text[-8192:]
            execution["activity"] = "generating" if key == "output" else "thinking"
        elif event_type == "tool_call":
            call_id = data.get("tool_call_id")
            if call_id:
                execution["tools"][call_id] = deepcopy(data)
                while len(execution["tools"]) > 64:
                    del execution["tools"][next(iter(execution["tools"]))]
            execution["activity"] = "tool" if data.get("status") == "started" else "working"
        elif event_type == "agent_activity":
            execution["activity"] = data.get("activity") or "working"
            execution["error"] = data.get("message") if data.get("activity") == "error" else None
        elif event_type == "work_saved":
            execution["activity"] = "saved"
        while len(self.executions) > 128:
            occupied = {seat["reservation_id"] for seat in self.seats if not seat.get("foreign")}
            removable = next((key for key, value in self.executions.items()
                if value.get("reservation_id") not in occupied), None)
            if removable is None:
                break
            del self.executions[removable]

    def snapshot(self) -> dict[str, Any]:
        return deepcopy(
            {
                "cursor": self.cursor,
                "run_id": self.run_id,
                "status": self.status,
                "stage": self.stage,
                "error": self.error,
                "stages": self.stages,
                "models": self.models,
                "seats": self.seats,
                "executions": self.executions,
            }
        )
