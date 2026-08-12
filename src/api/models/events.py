"""
统一事件模型与 Event Bus

说明:
  - StreamEvent: 统一事件格式，所有 SSE 事件使用同一结构
  - AnalysisEventBus: 持有当前上下文，自动补全缺失字段，统一发送到 SSE

核心设计:
  所有事件走同一条路径，Event Bus 持有 stage/sub_stage/chunk_id 上下文，
  LLM 输出不再是旁路，自动获得完整上下文后统一发送
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING, Any, Literal

from loguru import logger

if TYPE_CHECKING:
    from src.api.services.task_manager import TaskManager


# ------------------------------------------------------------------ #
#  StreamMessageType — SSE 事件类型枚举                                #
# ------------------------------------------------------------------ #


class StreamMessageType(StrEnum):
    """流式消息类型枚举"""

    stage_start = "stage_start"
    stage_progress = "stage_progress"
    stage_complete = "stage_complete"
    llm_output = "llm_output"
    llm_thinking = "llm_thinking"
    tool_call = "tool_call"
    task_complete = "task_complete"
    task_error = "task_error"
    task_cancelled = "task_cancelled"


# ------------------------------------------------------------------ #
#  StreamEvent — 统一事件格式                                         #
# ------------------------------------------------------------------ #

StreamEventAction = Literal["start", "progress", "complete", "output", "thinking", "tool_call"]
"""StreamEvent.action 的合法值"""


@dataclass
class StreamEvent:
    """
    统一 SSE 事件格式

    所有层发送的事件都使用此格式，只是字段填充不同
    Event Bus 会自动补全缺失的上下文字段

    action 语义:
        start    — 阶段/phase/chunk 开始
        progress — 增量进度
        complete — 阶段/phase/chunk 完成
        output   — LLM 正式输出
        thinking — LLM 思考过程输出
    """

    action: StreamEventAction  # 开始 / 进度 / 完成 / 输出 / 思考 / 工具调用
    stage: str = ""
    sub_stage: str = ""
    chunk_id: int | None = None
    stream_id: str | None = None
    current: int | None = None
    total: int | None = None
    percent: float | None = None  # 全局进度（stage 级别）
    sub_percent: float | None = None  # 子阶段进度（如 Agent 单章节内的领域写入进度）
    content: str = ""
    message: str = ""
    status: str | None = None  # 工具调用状态（tool_call 事件专用: started/success/failed）

    def to_dict(self) -> dict[str, Any]:
        return {
            "action": self.action,
            "stage": self.stage,
            "sub_stage": self.sub_stage,
            "chunk_id": self.chunk_id or 0,
            "stream_id": self.stream_id,
            "current": self.current or 0,
            "total": self.total or 0,
            "percent": self.percent or 0.0,
            "sub_percent": self.sub_percent or 0.0,
            "content": self.content,
            "message": self.message,
            "status": self.status or "",
        }


# ------------------------------------------------------------------ #
#  Action → SSE event type 映射                                       #
# ------------------------------------------------------------------ #

# 终止类事件（task_complete / task_error / task_cancelled）不在此映射表中，
# 原因如下：
#   1. 语义差异：映射表中的 5 个 action 是「进行中」事件，需要 EventBus 补全
#      stage/sub_stage/chunk_id 等上下文字段；而终止类事件表示任务级终态，
#      不需要也不应携带 chunk 级上下文
#   2. 数据格式不同：终止类事件的 data 结构固定（如 {"error": ..., "stage": ...}），
#      与 StreamEvent.to_dict() 的 10 字段格式不同，强行走 emit() 再翻译会丢失
#      语义或产生冗余字段
#   3. 副作用控制：emit() 内部会同步调用 task_manager.update_task()，
#      对终止事件而言这些更新既不必要也可能引发状态冲突
# 因此 emit_task_complete / emit_task_error / emit_task_cancelled 直接调用
# event_manager.send()，跳过 emit() 的上下文补全和 TaskManager 同步逻辑
_ACTION_TO_SSE_EVENT: dict[str, str] = {
    "start": StreamMessageType.stage_start.value,
    "progress": StreamMessageType.stage_progress.value,
    "complete": StreamMessageType.stage_complete.value,
    "output": StreamMessageType.llm_output.value,
    "thinking": StreamMessageType.llm_thinking.value,
    "tool_call": StreamMessageType.tool_call.value,
}

# preprocess 的 paragraph embedding 子阶段按 embedding batch 高频发 progress 事件；
# 若继续落到 INFO，会把控制台刷满并淹没真正有诊断价值的阶段切换日志
_DEBUG_PROGRESS_SUB_STAGES = {
    "paragraph_embedding",
}

_STAGE_PERCENT_RANGES: dict[str, tuple[float, float]] = {
    "preprocess": (0.0, 10.0),
    "annotate": (10.0, 80.0),
    "aggregate": (80.0, 90.0),
    "topic-model": (90.0, 95.0),
    "diagnose": (95.0, 100.0),
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
        self._current: int | None = None
        self._total: int | None = None
        self._percent: float | None = None
        self._sub_percent: float | None = None

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
        # 补全上下文：构建新事件对象，避免修改原始事件
        resolved_stage = event.stage or self._stage
        resolved_sub_stage = event.sub_stage or self._sub_stage
        resolved_chunk_id = event.chunk_id if event.chunk_id is not None else self._chunk_id

        if event.stage:
            self._stage = event.stage
        if event.sub_stage:
            self._sub_stage = event.sub_stage
        if event.chunk_id is not None:
            self._chunk_id = event.chunk_id
        if event.current is not None:
            self._current = event.current
        if event.total is not None:
            self._total = event.total
        if event.percent is not None:
            self._percent = event.percent
        if event.sub_percent is not None:
            self._sub_percent = event.sub_percent

        # None 值不覆盖已有的上下文值，保持语义："未传"不覆盖"已传"
        resolved_current = event.current if event.current is not None else self._current
        resolved_total = event.total if event.total is not None else self._total

        # 自动计算 percent：当事件没有提供 percent 时，根据 current/total 和当前阶段计算
        resolved_percent: float | None
        if event.percent is not None:
            resolved_percent = event.percent
        elif resolved_current is not None and resolved_total is not None and resolved_total > 0:
            resolved_percent = self._calculate_percent_for_stage(resolved_stage, resolved_current, resolved_total)
        else:
            resolved_percent = self._percent

        resolved_sub_percent: float | None
        resolved_sub_percent = event.sub_percent if event.sub_percent is not None else self._sub_percent

        resolved_event = StreamEvent(
            action=event.action,
            stage=resolved_stage,
            sub_stage=resolved_sub_stage,
            chunk_id=resolved_chunk_id,
            current=resolved_current,
            total=resolved_total,
            percent=resolved_percent,
            sub_percent=resolved_sub_percent,
            content=event.content,
            message=event.message,
            status=event.status,
        )

        # 翻译 action → SSE event type
        sse_event_type = _ACTION_TO_SSE_EVENT.get(resolved_event.action)
        if sse_event_type is None:
            logger.warning(
                f"[EventBus] unknown action={resolved_event.action}, falling back to 'message'. "
                f"Valid actions: {list(_ACTION_TO_SSE_EVENT.keys())}"
            )
            sse_event_type = "message"

        # LLM 流式正文/思考片段/工具调用，以及 embedding batch 这类高频 progress，
        # 都降到 DEBUG，避免 INFO 被细粒度增量日志刷屏；普通阶段开始/完成仍保留 INFO
        log_level = (
            logger.debug
            if resolved_event.action in {"output", "thinking", "tool_call"}
            or (
                resolved_event.action == "progress"
                and resolved_event.sub_stage in _DEBUG_PROGRESS_SUB_STAGES
            )
            else logger.info
        )
        log_level(
            f"[EventBus] task_id={self.task_id}, action={resolved_event.action}, "
            f"stage={resolved_event.stage}, sub_stage={resolved_event.sub_stage}, "
            f"chunk_id={resolved_event.chunk_id}, percent={resolved_percent}, sub_percent={resolved_sub_percent}"
        )

        # 唯一发送口（lazy import 避免循环依赖）
        from src.api.services.event_manager import event_manager

        await event_manager.send(
            task_id=self.task_id,
            event_type=sse_event_type,
            data=resolved_event.to_dict(),
        )

        # 同步更新 TaskManager
        if resolved_event.action in ("start", "progress", "complete"):
            # 这里不能再吞掉异常；如果 DB 写回失败，就必须让任务主链感知并按失败路径收口，
            # 否则会重新回到“内存继续跑、DB 状态滞后”的双真相源
            task_update_kwargs: dict[str, Any] = {
                "stage": resolved_event.stage,
                "sub_stage": resolved_event.sub_stage,
                "message": resolved_event.message,
            }
            # EventBus 的 None 表示“当前事件未提供该字段”，不是“把数据库字段清空”
            # 对非空进度列必须只在确实拿到值时才写回，避免 start 事件把 current=None 落库
            if resolved_event.current is not None:
                task_update_kwargs["current"] = resolved_event.current
            if resolved_event.total is not None:
                task_update_kwargs["total"] = resolved_event.total
            if resolved_event.percent is not None:
                task_update_kwargs["progress"] = resolved_event.percent

            self.task_manager.update_task(self.task_id, **task_update_kwargs)
        elif resolved_event.action == "output":
            try:
                self.task_manager.append_llm_output(self.task_id, resolved_event.content)
            except Exception as e:
                logger.error(f"Failed to append LLM output: {e}")

    def _calculate_percent_for_stage(self, stage: str, current: int, total: int) -> float:
        """
        根据阶段和当前进度计算全局 percent

        说明: 当事件没有提供 percent 时，根据 current/total 和阶段范围自动计算

        各阶段进度范围:
        - preprocess: 0-10%
        - annotate: 10-80%
        - aggregate: 80-90%
        - topic-model: 90-95%
        - diagnose: 95-100%
        """
        if total <= 0:
            return 0.0

        progress_ratio = current / total

        start, end = _STAGE_PERCENT_RANGES.get(stage, (0.0, 100.0))
        return start + progress_ratio * (end - start)

    # ------------------------------------------------------------------
    #  便捷方法：阶段级事件
    # ------------------------------------------------------------------

    async def emit_stage_start(self, stage: str, message: str = "", percent: float = 0.0, total: int = 0) -> None:
        """发送阶段开始事件"""
        self._stage = stage
        self._sub_stage = ""
        self._chunk_id = 0
        self._sub_percent = 0.0
        await self.emit(
            StreamEvent(
                action="start",
                stage=stage,
                message=message,
                percent=percent,
                total=total,
                sub_percent=0.0,
            )
        )

    async def emit_stage_complete(self, stage: str) -> None:
        """发送阶段完成事件"""
        self._sub_percent = 100.0
        _, stage_end_percent = _STAGE_PERCENT_RANGES.get(stage, (0.0, 100.0))
        await self.emit(
            StreamEvent(
                action="complete",
                stage=stage,
                percent=stage_end_percent,
                sub_percent=100.0,
                message=f"{stage} 完成",
            )
        )

    async def emit_task_complete(self) -> None:
        """发送任务完成事件（使用 task_complete SSE 事件类型）"""
        from src.api.services.event_manager import event_manager

        await event_manager.send(
            task_id=self.task_id,
            event_type=StreamMessageType.task_complete.value,
            data={"stage": "completed", "percent": 100.0, "message": "分析完成"},
        )

    async def emit_task_error(self, error: str, stage: str = "failed") -> None:
        """发送任务错误事件"""
        from src.api.services.event_manager import event_manager

        await event_manager.send(
            task_id=self.task_id,
            event_type=StreamMessageType.task_error.value,
            data={"error": error, "stage": stage},
        )

    async def emit_task_cancelled(self) -> None:
        """发送任务取消事件"""
        from src.api.services.event_manager import event_manager

        await event_manager.send(
            task_id=self.task_id,
            event_type=StreamMessageType.task_cancelled.value,
            data={"stage": "cancelled", "message": "任务已取消"},
        )
