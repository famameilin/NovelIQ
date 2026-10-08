"""
分析进度事件总线

说明:
  - AnalysisEventBus: 持有 stage/sub_stage/chapter_id 上下文，补全事件字段后
    经展示通道发送，并把阶段进度写回运行状态
  - SSE 事件名与展示消息契约分别由 src/agents/stream_events.py 与
    src/agents/event_manager.py 提供

核心设计:
  所有事件走同一条路径，Event Bus 持有上下文，LLM 输出不再是旁路，
  自动获得完整上下文后统一发送
"""

from __future__ import annotations

from typing import Any

from loguru import logger

from src.config import settings
from src.sse.events import StreamEvent, StreamMessageType
from src.work.task_manager import TaskManager

__all__ = ["AnalysisEventBus", "StreamEvent", "StreamMessageType"]


# 终态事件直接发送，避免补入章节上下文或触发 TaskManager 的进行中状态同步
_ACTION_TO_SSE_EVENT: dict[str, str] = {
    "start": StreamMessageType.stage_start.value,
    "progress": StreamMessageType.stage_progress.value,
    "complete": StreamMessageType.stage_complete.value,
    "output": StreamMessageType.llm_output.value,
    "thinking": StreamMessageType.llm_thinking.value,
    "tool_call": StreamMessageType.tool_call.value,
    "work_reset": "work_reset",
    "chapter_reset": "chapter_reset",
    "work_saved": "pipeline_progress",
}

# preprocess 的 paragraph embedding 子阶段按 embedding batch 高频发 progress 事件；
# 若继续落到 INFO，会把控制台刷满并淹没真正有诊断价值的阶段切换日志
_DEBUG_PROGRESS_SUB_STAGES = {
    "paragraph_embedding",
}

_STAGE_SETTING_NAMES = {
    "preprocess": "preprocess",
    "annotate": "annotate",
    "linguistic": "linguistic",
    "aggregate": "aggregate",
    "topic-model": "topic_model",
    "diagnose": "diagnose",
}


def _stage_percent_range(stage: str) -> tuple[float, float]:
    """阶段名归编排层，百分比配置只有一个来源"""
    name = _STAGE_SETTING_NAMES.get(stage)
    if name is None:
        return 0.0, 100.0
    configured = getattr(settings.progress, name)
    return configured.start, configured.end


def stage_progress_percent(stage: str, current: int, total: int) -> float:
    """按阶段配置计算全局进度，保存回调与阶段事件共用同一口径"""
    if total <= 0:
        return 0.0
    start, end = _stage_percent_range(stage)
    return start + current / total * (end - start)


class AnalysisEventBus:
    """
    分析事件总线

    职责:
    1. 持有当前 stage/sub_stage/chapter_id 上下文
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
        self._chapter_id: int = 0
        self._current: int | None = None
        self._total: int | None = None
        self._percent: float | None = None
        self._sub_percent: float | None = None

    async def emit(self, event: StreamEvent) -> None:
        """
        发送事件：补全上下文 → 翻译为 SSE → 发送

        子规则:
        - 如果事件提供了 stage/sub_stage/chapter_id，更新总线上下文
        - 如果事件缺失这些字段，用总线当前上下文补全
        - 将 action 翻译为 SSE event type
        - 调用 event_manager.send() 唯一发送口
        - 同步更新 TaskManager
        """
        # 补全上下文：构建新事件对象，避免修改原始事件
        resolved_stage = event.stage or self._stage
        resolved_sub_stage = event.sub_stage or self._sub_stage
        resolved_chapter_id = event.chapter_id if event.chapter_id is not None else self._chapter_id

        if event.stage:
            self._stage = event.stage
        if event.sub_stage:
            self._sub_stage = event.sub_stage
        if event.chapter_id is not None:
            self._chapter_id = event.chapter_id
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
            chapter_id=resolved_chapter_id,
            # 保留 LLM/工具事件的流标识，确保序列化和前端重连使用同一条流
            stream_id=event.stream_id,
            work_id=event.work_id,
            invocation_id=event.invocation_id,
            message_id=event.message_id,
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
            or (resolved_event.action == "progress" and resolved_event.sub_stage in _DEBUG_PROGRESS_SUB_STAGES)
            else logger.info
        )
        log_level(
            f"[EventBus] task_id={self.task_id}, action={resolved_event.action}, "
            f"stage={resolved_event.stage}, sub_stage={resolved_event.sub_stage}, "
            f"chapter_id={resolved_event.chapter_id}, percent={resolved_percent}, sub_percent={resolved_sub_percent}"
        )

        # 唯一发送口（lazy import 避免循环依赖）
        from src.sse.manager import event_manager

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
            # 2026-08-13 P2：total=0 是「未提供」的非法值（默认 0 曾把 analysis_runs.total
            # 从 100 清成 0），只有 >0 才写回数据库
            if resolved_total is not None and resolved_total > 0:
                task_update_kwargs["total"] = resolved_total
            if resolved_event.percent is not None:
                task_update_kwargs["progress"] = resolved_event.percent

            # 2026-10-03 DB 写回移出事件循环：update_task 的同步 UPDATE 一旦撞上行锁
            # （如 require_released_cutoff 曾把 FOR SHARE 持有整个 diagnose 阶段）会在
            # 事件循环线程上等满语句超时——整个 API（SSE/health/所有端点）随之冻结。
            # to_thread 只阻塞本事件处理，异常仍原样上抛给任务主链。
            import asyncio

            await asyncio.to_thread(self.task_manager.update_task, self.task_id, **task_update_kwargs)
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
        - annotate: 10-75%
        - linguistic: 75-80%
        - aggregate: 80-90%
        - topic-model: 90-95%
        - diagnose: 95-100%
        """
        return stage_progress_percent(stage, current, total)

    # 阶段级事件

    async def emit_stage_start(
        self,
        stage: str,
        message: str = "",
        percent: float | None = None,
        total: int | None = None,
    ) -> None:
        """发送阶段开始事件"""
        self._stage = stage
        self._sub_stage = ""
        self._chapter_id = 0
        self._sub_percent = 0.0
        # 2026-08-13 P2：阶段边界作废旧阶段的 current/total/percent 上下文，
        # 否则新阶段内不带进度字段的事件会沿用旧阶段数值套新阶段区间算错 percent，
        # 且 complete 事件会把 stale current/total 写回数据库
        self._current = None
        self._total = None
        self._percent = percent
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
        # 2026-08-13 P2：完成事件显式带 percent，旧阶段的 current/total 上下文
        # 不得随事件写回数据库（complete 事件本身不含进度数值）
        self._current = None
        self._total = None
        _, stage_end_percent = _stage_percent_range(stage)
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
        from src.sse.manager import event_manager

        await event_manager.send(
            task_id=self.task_id,
            event_type=StreamMessageType.task_complete.value,
            data={"stage": "completed", "percent": 100.0, "message": "分析完成"},
        )

    async def emit_task_error(self, error: str, stage: str = "failed") -> None:
        """发送任务错误事件"""
        from src.sse.manager import event_manager

        await event_manager.send(
            task_id=self.task_id,
            event_type=StreamMessageType.task_error.value,
            data={"error": error, "stage": stage},
        )

    async def emit_task_cancelled(self) -> None:
        """发送任务取消事件"""
        from src.sse.manager import event_manager

        await event_manager.send(
            task_id=self.task_id,
            event_type=StreamMessageType.task_cancelled.value,
            data={"stage": "cancelled", "message": "任务已取消"},
        )
