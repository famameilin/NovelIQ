"""
统一事件模型与 Event Bus

创建时间: 2026-04-09
创建者: GLM-5
任务: refactor/sse-unified-event-bus
说明:
  - StreamEvent: 统一事件格式，所有 SSE 事件使用同一结构
  - AnalysisEventBus: 持有当前上下文，自动补全缺失字段，统一发送到 SSE

核心设计:
  所有事件走同一条路径，Event Bus 持有 stage/sub_stage/chunk_id 上下文，
  LLM 输出不再是旁路，自动获得完整上下文后统一发送。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from loguru import logger

from src.api.models.stream import StreamMessageType
from src.api.services.event_manager import event_manager
from src.api.services.task_manager import TaskManager


# ------------------------------------------------------------------ #
#  StreamEvent — 统一事件格式                                         #
# ------------------------------------------------------------------ #

@dataclass
class StreamEvent:
    """
    统一 SSE 事件格式

    所有层发送的事件都使用此格式，只是字段填充不同。
    Event Bus 会自动补全缺失的上下文字段。

    action 语义:
        start    — 阶段/phase/chunk 开始
        progress — 增量进度
        complete — 阶段/phase/chunk 完成
        output   — LLM 正式输出
        thinking — LLM 思考过程输出
    """

    action: str   # start / progress / complete / output / thinking
    stage: str = ""
    sub_stage: str = ""
    chunk_id: int = 0
    current: int = 0
    total: int = 0
    percent: float = 0.0
    content: str = ""
    message: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "action": self.action,
            "stage": self.stage,
            "sub_stage": self.sub_stage,
            "chunk_id": self.chunk_id,
            "current": self.current,
            "total": self.total,
            "percent": self.percent,
            "content": self.content,
            "message": self.message,
        }


# ------------------------------------------------------------------ #
#  Action → SSE event type 映射                                       #
# ------------------------------------------------------------------ #

_ACTION_TO_SSE_EVENT: dict[str, str] = {
    "start": StreamMessageType.stage_start.value,
    "progress": StreamMessageType.stage_progress.value,
    "complete": StreamMessageType.stage_complete.value,
    "output": StreamMessageType.llm_output.value,
    "thinking": StreamMessageType.llm_thinking.value,
}


# ------------------------------------------------------------------ #
#  AnalysisEventBus — 上下文保持器 + 统一发送口                        #
# ------------------------------------------------------------------ #

class AnalysisEventBus:
    """
    分析事件总线

    职责:
    1. 持有当前 stage/sub_stage/chunk_id 上下文
    2. 自动补全事件缺失的字段
    3. 统一发送到 SSE（唯一发送口）
    4. 同步更新 TaskManager 状态
    """

    def __init__(self, task_id: str, task_manager: TaskManager) -> None:
        self.task_id = task_id
        self.task_manager = task_manager

        # 上下文状态：由 emit 的事件自动维护
        self._stage: str = ""
        self._sub_stage: str = ""
        self._chunk_id: int = 0

    async def emit(self, event: StreamEvent) -> None:
        """
        发送事件：补全上下文 → 翻译为 SSE → 发送

        子规则:
        - 如果事件提供了 stage/sub_stage/chunk_id，更新总线上下文
        - 如果事件缺失这些字段，用总线当前上下文补全
        - 将 action 翻译为 SSE event type
        - 调用 event_manager.send() 唯一发送口
        - 同步更新 TaskManager
        """
        # 补全上下文：事件有值则更新总线，无值则用总线填充
        if event.stage:
            self._stage = event.stage
        else:
            event.stage = self._stage

        if event.sub_stage:
            self._sub_stage = event.sub_stage
        else:
            event.sub_stage = self._sub_stage

        if event.chunk_id:
            self._chunk_id = event.chunk_id
        else:
            event.chunk_id = self._chunk_id

        # 翻译 action → SSE event type
        sse_event_type = _ACTION_TO_SSE_EVENT.get(event.action, "message")

        logger.info(
            f"[EventBus] task_id={self.task_id}, action={event.action}, "
            f"stage={event.stage}, sub_stage={event.sub_stage}, "
            f"chunk_id={event.chunk_id}"
        )

        # 唯一发送口
        await event_manager.send(
            task_id=self.task_id,
            event_type=sse_event_type,
            data=event.to_dict(),
        )

        # 同步更新 TaskManager（与 ProgressBroadcaster 原逻辑一致）
        if event.action in ("start", "progress"):
            self.task_manager.update_task(
                self.task_id,
                stage=event.stage,
                sub_stage=event.sub_stage,
                current=event.current,
                total=event.total,
                progress=event.percent,
                message=event.message,
            )
        elif event.action == "output":
            self.task_manager.append_llm_output(self.task_id, event.content)

    # ------------------------------------------------------------------
    #  便捷方法：阶段级事件
    # ------------------------------------------------------------------

    async def emit_stage_start(self, stage: str, message: str = "", percent: float = 0.0) -> None:
        """发送阶段开始事件"""
        self._stage = stage
        self._sub_stage = ""
        self._chunk_id = 0
        await self.emit(StreamEvent(
            action="start", stage=stage, message=message, percent=percent,
        ))

    async def emit_stage_complete(self, stage: str) -> None:
        """发送阶段完成事件"""
        await self.emit(StreamEvent(
            action="complete", stage=stage, percent=100.0,
        ))

    async def emit_task_complete(self) -> None:
        """发送任务完成事件（使用 task_complete SSE 事件类型）"""
        await event_manager.send(
            task_id=self.task_id,
            event_type=StreamMessageType.task_complete.value,
            data={"stage": "completed", "percent": 100.0, "message": "分析完成"},
        )

    async def emit_task_error(self, error: str, stage: str = "failed") -> None:
        """发送任务错误事件"""
        await event_manager.send(
            task_id=self.task_id,
            event_type=StreamMessageType.task_error.value,
            data={"error": error, "stage": stage},
        )

    async def emit_task_cancelled(self) -> None:
        """发送任务取消事件"""
        await event_manager.send(
            task_id=self.task_id,
            event_type=StreamMessageType.task_cancelled.value,
            data={"stage": "cancelled", "message": "任务已取消"},
        )
