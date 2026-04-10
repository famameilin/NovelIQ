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


@pytest.mark.asyncio
async def test_eventbus_calculates_percent_from_current_total():
    """
    验证 EventBus.emit 在事件没有提供 percent 时，根据 current/total 自动计算

    创建时间: 2026-04-11
    创建者: GLM-5
    任务: fix-thinking-percent-calculation
    说明: 测试 thinking 事件没有 percent 字段时，EventBus 应根据 current/total 自动计算
    """
    task_manager = MagicMock()
    task_manager.update_progress = MagicMock()

    bus = AnalysisEventBus(task_id="test-task", task_manager=task_manager)

    with patch("src.api.services.event_manager.event_manager") as mock_em:
        mock_em.send = AsyncMock()

        # 先发送一个 progress 事件设置 stage 和 current/total
        event1 = StreamEvent(
            action="progress",
            stage="annotate",
            sub_stage="phase1",
            current=21,
            total=37,
            percent=49.7,
            message="标注 chunk 21/37",
        )
        await bus.emit(event1)

        # 发送 thinking 事件，没有 percent 字段
        event2 = StreamEvent(
            action="thinking",
            content="thinking content",
        )
        await bus.emit(event2)

        call1_kwargs = mock_em.send.call_args_list[0].kwargs
        call2_kwargs = mock_em.send.call_args_list[1].kwargs

        # 第一个事件应该有正确的 percent
        assert call1_kwargs["data"]["percent"] == 49.7
        # 第二个事件应该根据 current/total 自动计算 percent
        # annotate 阶段范围是 10-80，current=21, total=37
        # percent = 10 + (21/37) * 70 ≈ 49.73
        expected_percent = 10 + (21 / 37) * 70
        assert abs(call2_kwargs["data"]["percent"] - expected_percent) < 0.1


@pytest.mark.asyncio
async def test_eventbus_calculates_percent_for_different_stages():
    """
    验证 EventBus._calculate_percent_for_stage 对不同阶段的计算

    创建时间: 2026-04-11
    创建者: GLM-5
    任务: fix-thinking-percent-calculation
    """
    task_manager = MagicMock()
    bus = AnalysisEventBus(task_id="test-task", task_manager=task_manager)

    # preprocess: 0-10%
    assert bus._calculate_percent_for_stage("preprocess", 5, 10) == 5.0

    # annotate: 10-80%
    assert bus._calculate_percent_for_stage("annotate", 5, 10) == 45.0

    # aggregate: 80-90%
    assert bus._calculate_percent_for_stage("aggregate", 5, 10) == 85.0

    # topic-model: 90-95%
    assert bus._calculate_percent_for_stage("topic-model", 5, 10) == 92.5

    # diagnose: 95-100%
    assert bus._calculate_percent_for_stage("diagnose", 5, 10) == 97.5

    # 未知阶段: 0-100%
    assert bus._calculate_percent_for_stage("unknown", 5, 10) == 50.0
