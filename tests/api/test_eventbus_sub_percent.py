"""
Tests for EventBus.emit sub_percent propagation.
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from src.api.models.events import StreamEvent, AnalysisEventBus


@pytest.mark.asyncio
async def test_eventbus_emits_sub_percent():
    """验证 EventBus.emit 正确传递 sub_percent"""
    task_manager = MagicMock()
    task_manager.update_progress = MagicMock()

    bus = AnalysisEventBus(task_id="test-task", task_manager=task_manager)

    with patch("src.api.services.event_manager.event_manager") as mock_em:
        mock_em.send = AsyncMock()

        event = StreamEvent(
            action="complete",
            sub_stage="phase1",
            chunk_id=0,
            sub_percent=25,
            message="phase1 done",
        )
        await bus.emit(event)

        # 验证 event_manager.send 被调用
        mock_em.send.assert_called_once()
        call_kwargs = mock_em.send.call_args.kwargs
        assert call_kwargs["data"]["sub_percent"] == 25


@pytest.mark.asyncio
async def test_eventbus_emits_sub_percent_none_when_not_provided():
    """验证 EventBus.emit 在未提供 sub_percent 时传递 None"""
    task_manager = MagicMock()
    task_manager.update_progress = MagicMock()

    bus = AnalysisEventBus(task_id="test-task", task_manager=task_manager)

    with patch("src.api.services.event_manager.event_manager") as mock_em:
        mock_em.send = AsyncMock()

        event = StreamEvent(
            action="complete",
            sub_stage="phase1",
            chunk_id=0,
            message="phase1 done",
        )
        await bus.emit(event)

        call_kwargs = mock_em.send.call_args.kwargs
        # to_dict() 将 None sub_percent 转为 0.0（SSE 前端不接受 None）
        assert call_kwargs["data"]["sub_percent"] == 0.0


@pytest.mark.asyncio
async def test_eventbus_preserves_sub_percent_from_context():
    """验证 EventBus 保留上下文中已有的 sub_percent"""
    task_manager = MagicMock()
    task_manager.update_progress = MagicMock()

    bus = AnalysisEventBus(task_id="test-task", task_manager=task_manager)

    with patch("src.api.services.event_manager.event_manager") as mock_em:
        mock_em.send = AsyncMock()

        event1 = StreamEvent(
            action="complete",
            sub_stage="phase1",
            chunk_id=0,
            sub_percent=25,
        )
        await bus.emit(event1)

        event2 = StreamEvent(
            action="thinking",
            sub_stage="",
        )
        await bus.emit(event2)

        call1_kwargs = mock_em.send.call_args_list[0].kwargs
        call2_kwargs = mock_em.send.call_args_list[1].kwargs

        assert call1_kwargs["data"]["sub_percent"] == 25
        assert call2_kwargs["data"]["sub_percent"] == 25
