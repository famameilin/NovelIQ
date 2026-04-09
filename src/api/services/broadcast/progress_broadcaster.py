"""
进度广播服务

创建时间: 2026-04-07
创建者: GLM-5
任务: AnalysisService 重构 - 提取 WebSocket 广播职责
说明: 负责通过 WebSocket 向前端推送进度更新和 LLM 输出
"""

from __future__ import annotations

from src.api.models.stream import LLMOutputData, ProgressDetail, StreamMessage, StreamMessageType
from src.api.services.stream_manager import stream_manager


class ProgressBroadcaster:
    """进度广播服务 - 负责通过 WebSocket 推送进度更新"""

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
        """广播进度消息到 WebSocket"""
        progress_detail = ProgressDetail(
            stage=stage,
            sub_stage=sub_stage,
            phase=phase,
            current=current,
            total=total,
            percent=percent,
            message=message,
        )
        stream_message = StreamMessage(
            type=message_type,
            task_id=task_id,
            data=progress_detail.model_dump(mode="json"),
        )
        await stream_manager.broadcast(task_id, stream_message.model_dump(mode="json"))

    async def broadcast_llm_output(
        self,
        task_id: str,
        message_type: StreamMessageType,
        phase: str,
        content: str,
        chunk_id: int = 0,
    ) -> None:
        """广播 LLM 输出消息到 WebSocket"""
        llm_data = LLMOutputData(
            phase=phase,
            chunk_id=chunk_id,
            content=content,
        )
        stream_message = StreamMessage(
            type=message_type,
            task_id=task_id,
            data=llm_data.model_dump(mode="json"),
        )
        await stream_manager.broadcast(task_id, stream_message.model_dump(mode="json"))
