"""
进度广播服务

创建时间: 2026-04-09
创建者: GLM-5
任务: sse-architecture-review
说明: 统一的 SSE 广播封装，AnalysisService 和 ErrorHandler 共用
"""

from __future__ import annotations

from typing import Any

from loguru import logger

from src.api.models.stream import StreamMessageType
from src.api.services.event_manager import event_manager
from src.api.services.task_manager import TaskManager


class ProgressBroadcaster:
    """统一的 SSE 进度广播器"""

    def __init__(self, task_manager: TaskManager) -> None:
        self.task_manager = task_manager

    async def broadcast_progress(
        self,
        task_id: str,
        message_type: StreamMessageType,
        stage: str = "",
        sub_stage: str = "",
        phase: str = "",
        current: int = 0,
        total: int = 0,
        percent: float = 0.0,
        message: str = "",
    ) -> None:
        """广播进度消息到 SSE 并更新 TaskInfo"""
        logger.info(f"[broadcast_progress] task_id={task_id}, type={message_type}, stage={stage}")

        await event_manager.send(
            task_id=task_id,
            event_type=message_type.value,
            data={
                "stage": stage,
                "sub_stage": sub_stage,
                "phase": phase,
                "current": current,
                "total": total,
                "percent": percent,
                "message": message,
            },
        )

        if message_type in (StreamMessageType.stage_start, StreamMessageType.stage_progress):
            self.task_manager.update_task(
                task_id,
                stage=stage,
                sub_stage=sub_stage,
                current=current,
                total=total,
                progress=percent,
                message=message,
            )

    async def broadcast_llm_output(
        self,
        task_id: str,
        message_type: StreamMessageType,
        phase: str,
        content: str,
        chunk_id: int = 0,
    ) -> None:
        """广播 LLM 输出消息到 SSE 并更新 TaskInfo"""
        await event_manager.send(
            task_id=task_id,
            event_type=message_type.value,
            data={
                "phase": phase,
                "content": content,
                "chunk_id": chunk_id,
            },
        )

        self.task_manager.append_llm_output(task_id, content)
