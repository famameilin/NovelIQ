"""
Tests for EventBus.emit sub_percent propagation.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.api.models.events import AnalysisEventBus, StreamEvent


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
async def test_eventbus_progress_message_without_sub_stage_preserves_phase_context():
    """
    验证 message-only progress 事件不会改写已有的 phase 级 sub_stage/sub_percent。

    创建时间: 2026-04-28
    创建者: Codex
    任务: fix-level3-sse-phase-progress-contract
    说明: Level3 mention 这类更细粒度节点只应刷新提示文案，EventBus 仍应沿用当前 phase
          上下文，避免前端下方 sub 进度条从 phase 级跳成内部 mention 级。

    修改时间: 2026-04-28
    任务: simplify-level3-sse-copy
    修改说明: 提示文案统一收口成“正在收集证据”，前端不再感知内部步骤名。
    """
    task_manager = MagicMock()
    task_manager.update_progress = MagicMock()

    bus = AnalysisEventBus(task_id="test-task", task_manager=task_manager)

    with patch("src.api.services.event_manager.event_manager") as mock_em:
        mock_em.send = AsyncMock()

        await bus.emit(
            StreamEvent(
                action="progress",
                stage="annotate",
                sub_stage="phase3",
                chunk_id=8,
                current=21,
                total=37,
                percent=49.7,
                sub_percent=75,
                message="phase3 进行中",
            )
        )
        await bus.emit(
            StreamEvent(
                action="progress",
                stage="annotate",
                chunk_id=8,
                message="正在收集证据",
            )
        )

        call1_kwargs = mock_em.send.call_args_list[0].kwargs
        call2_kwargs = mock_em.send.call_args_list[1].kwargs

        assert call1_kwargs["data"]["sub_stage"] == "phase3"
        assert call1_kwargs["data"]["sub_percent"] == 75
        assert call2_kwargs["data"]["sub_stage"] == "phase3"
        assert call2_kwargs["data"]["sub_percent"] == 75
        assert call2_kwargs["data"]["message"] == "正在收集证据"


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


@pytest.mark.asyncio
async def test_eventbus_start_event_without_current_does_not_write_none_progress_fields():
    """
    验证 start 事件缺少 current 时，不会把 None 透传给 TaskManager。

    创建时间: 2026-04-20
    创建者: Codex (GPT-5)
    任务: fix-eventbus-null-progress-write
    说明: workflow 内部的 start 事件通常只有 stage/message，不带 current。
          这里要求 EventBus 只写回已解析出的字段，避免 DB 非空列收到 None。
    """
    task_manager = MagicMock()
    bus = AnalysisEventBus(task_id="test-task", task_manager=task_manager)

    with patch("src.api.services.event_manager.event_manager") as mock_em:
        mock_em.send = AsyncMock()

        await bus.emit(StreamEvent(action="start", stage="preprocess", message="开始预处理", sub_percent=0.0))

    task_manager.update_task.assert_called_once()
    update_kwargs = task_manager.update_task.call_args.kwargs
    assert update_kwargs["stage"] == "preprocess"
    assert update_kwargs["sub_stage"] == ""
    assert update_kwargs["message"] == "开始预处理"
    assert "current" not in update_kwargs
    assert "total" not in update_kwargs
    assert "progress" not in update_kwargs


@pytest.mark.asyncio
async def test_eventbus_demotes_llm_output_and_thinking_logs_to_debug():
    """
    验证 EventBus 会把高频 LLM 流式事件记录到 DEBUG，而不是 INFO。

    创建时间: 2026-04-20
    创建者: Codex (GPT-5)
    任务: demote-llm-output-eventbus-log
    说明: output/thinking 会携带原始模型分片，若落到 INFO 会污染运行日志；
          start/progress/complete 仍应保留在 INFO，便于跟踪任务进度。
    """
    task_manager = MagicMock()
    bus = AnalysisEventBus(task_id="test-task", task_manager=task_manager)

    with (
        patch("src.api.services.event_manager.event_manager") as mock_em,
        patch("src.api.models.events.logger.debug") as mock_debug,
        patch("src.api.models.events.logger.info") as mock_info,
    ):
        mock_em.send = AsyncMock()

        await bus.emit(StreamEvent(action="output", content='{"raw_name":"室内"}'))
        await bus.emit(StreamEvent(action="thinking", content="思考片段"))
        await bus.emit(StreamEvent(action="progress", stage="annotate", sub_stage="phase1", percent=10.0))

    assert mock_debug.call_count == 2
    assert mock_info.call_count == 1


@pytest.mark.asyncio
async def test_eventbus_demotes_high_frequency_embedding_progress_logs_to_debug():
    """
    验证 EventBus 会把高频 embedding batch progress 记录到 DEBUG，而不是 INFO。

    创建时间: 2026-04-28
    创建者: Codex
    任务: demote-eventbus-embedding-progress-log
    说明: `semantic_chunking_embedding` / `paragraph_embedding` 会在 preprocess 中按批次连续发 progress；
          这类日志应降到 DEBUG，但普通 progress 仍应保留在 INFO。
    """
    task_manager = MagicMock()
    bus = AnalysisEventBus(task_id="test-task", task_manager=task_manager)

    with (
        patch("src.api.services.event_manager.event_manager") as mock_em,
        patch("src.api.models.events.logger.debug") as mock_debug,
        patch("src.api.models.events.logger.info") as mock_info,
    ):
        mock_em.send = AsyncMock()

        await bus.emit(
            StreamEvent(
                action="progress",
                stage="preprocess",
                sub_stage="semantic_chunking_embedding",
                percent=3.3,
                sub_percent=33.0,
            )
        )
        await bus.emit(
            StreamEvent(
                action="progress",
                stage="preprocess",
                sub_stage="paragraph_embedding",
                percent=6.6,
                sub_percent=66.0,
            )
        )
        await bus.emit(StreamEvent(action="progress", stage="annotate", sub_stage="phase1", percent=10.0))

    assert mock_debug.call_count == 2
    assert mock_info.call_count == 1


@pytest.mark.asyncio
async def test_emit_stage_complete_uses_stage_end_percent_instead_of_global_100() -> None:
    """
    验证阶段完成事件写回的 percent 使用当前阶段终点，而不是错误地统一写成 100。

    创建时间: 2026-04-28
    创建者: Codex
    任务: fix-stage-complete-percent-range
    说明: 前端和 DB 都按全局 percent 解释阶段进度；
          preprocess complete 若被写成 100，会污染当前阶段判断与后续 backfill 语义。
    """
    task_manager = MagicMock()
    bus = AnalysisEventBus(task_id="test-task", task_manager=task_manager)

    with patch("src.api.services.event_manager.event_manager") as mock_em:
        mock_em.send = AsyncMock()

        await bus.emit_stage_complete("preprocess")
        await bus.emit_stage_complete("annotate")

    preprocess_update = task_manager.update_task.call_args_list[0].kwargs
    annotate_update = task_manager.update_task.call_args_list[1].kwargs

    assert preprocess_update["progress"] == 10.0
    assert annotate_update["progress"] == 80.0
