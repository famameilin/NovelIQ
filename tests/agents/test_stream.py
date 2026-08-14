"""Agent 流式事件封装测试：chunk 聚合、事件推送、降级路径"""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest
from langchain_core.messages import AIMessage, AIMessageChunk

from src.agents.stream import (
    AgentStream,
    StreamChunkAggregator,
    emit_tool_results,
    run_model_call,
)


def _collect_events() -> list[tuple[str, str, str]]:
    """构造收集事件的 emitter 与记录容器（action, content, status）"""
    events: list[tuple[str, str, str]] = []

    async def emitter(event) -> None:
        events.append((event.action, event.content, event.status or ""))

    return events, emitter


class _StreamingLLM:
    """支持 astream 的测试模型"""

    def __init__(self, chunks: list[AIMessageChunk]) -> None:
        self.chunks = chunks
        self.captured_messages: list[list] = []

    def bind_tools(self, tools):
        del tools
        return self

    async def astream(self, messages):
        self.captured_messages.append(list(messages))
        for chunk in self.chunks:
            yield chunk


class _NonStreamingLLM:
    """仅支持 ainvoke 的测试模型（降级路径）"""

    def __init__(self, response: AIMessage) -> None:
        self.response = response

    def bind_tools(self, tools):
        del tools
        return self

    async def ainvoke(self, messages):
        del messages
        return self.response


class _FlakyStreamingLLM:
    """2026-08-11 用于模拟流式输出中途断流的测试模型（前 fail_count 次调用抛异常）"""

    def __init__(self, chunks: list[AIMessageChunk], fail_count: int) -> None:
        self.chunks = chunks
        self.fail_count = fail_count
        self.captured_messages: list[list] = []

    def bind_tools(self, tools):
        del tools
        return self

    async def astream(self, messages):
        self.captured_messages.append(list(messages))
        if self.fail_count > 0:
            self.fail_count -= 1
            raise ConnectionError("stream interrupted mid-way")
        for chunk in self.chunks:
            yield chunk


class _RetryWithUsageLLM:
    """2026-08-12 用于模拟断流重试且两次尝试各自上报用量的测试模型（首次尝试产出后断流）"""

    def __init__(
        self,
        failing_chunks: list[AIMessageChunk],
        success_chunks: list[AIMessageChunk],
    ) -> None:
        self.failing_chunks = failing_chunks
        self.success_chunks = success_chunks
        self.captured_messages: list[list] = []

    def bind_tools(self, tools):
        del tools
        return self

    async def astream(self, messages):
        self.captured_messages.append(list(messages))
        if len(self.captured_messages) == 1:
            for chunk in self.failing_chunks:
                yield chunk
            raise ConnectionError("stream interrupted mid-way")
        for chunk in self.success_chunks:
            yield chunk


class _ConfigDisabledStreamingLLM:
    """2026-08-12 用于模拟 stream_enabled=False 的模型（有 astream 但 streaming 配置关闭）"""

    def __init__(self, response: AIMessage) -> None:
        self.response = response
        self.streaming = False
        self.ainvoke_calls = 0
        self.astream_calls = 0

    def bind_tools(self, tools):
        del tools
        return self

    async def ainvoke(self, messages):
        del messages
        self.ainvoke_calls += 1
        return self.response

    async def astream(self, messages):
        del messages
        self.astream_calls += 1
        yield AIMessageChunk(content="不应流出")


class _FlakyNonStreamingLLM:
    """2026-08-13 用于模拟非流式路径前 fail_count 次调用抛异常的测试模型"""

    def __init__(
        self,
        response: AIMessage,
        fail_count: int,
        error: Exception | None = None,
    ) -> None:
        self.response = response
        self.fail_count = fail_count
        self.error = error or ConnectionError("network down")
        self.ainvoke_calls = 0

    def bind_tools(self, tools):
        del tools
        return self

    async def ainvoke(self, messages):
        del messages
        self.ainvoke_calls += 1
        if self.fail_count > 0:
            self.fail_count -= 1
            raise self.error
        return self.response


@pytest.mark.asyncio
async def test_agent_stream_emits_thinking_and_output_events() -> None:
    events, emitter = _collect_events()
    stream = AgentStream(emitter, chunk_id=7, sub_stage="chapter_agent")

    await stream.thinking("正在推理，规划下一步动作...")
    await stream.output("模型说了一句")
    await stream.tool_call_started("resolve_case")
    await stream.tool_call_succeeded("resolve_case", "accepted")
    await stream.tool_call_failed("write_metrics", "参数错误")

    assert events == [
        ("thinking", "正在推理，规划下一步动作...", ""),
        ("output", "模型说了一句", ""),
        ("tool_call", "resolve_case", "started"),
        ("tool_call", "resolve_case", "success"),
        ("tool_call", "write_metrics", "failed"),
    ]


@pytest.mark.asyncio
async def test_agent_stream_skips_empty_content() -> None:
    events, emitter = _collect_events()
    stream = AgentStream(emitter)

    await stream.thinking("")
    await stream.output("")

    assert events == []


@pytest.mark.asyncio
async def test_aggregator_merges_text_and_reasoning_and_tool_calls() -> None:
    events, emitter = _collect_events()
    stream = AgentStream(emitter)
    aggregator = StreamChunkAggregator(stream)

    await aggregator.add_chunk(AIMessageChunk(content="章节", additional_kwargs={"reasoning_content": "先分析"}))
    await aggregator.add_chunk(AIMessageChunk(content="开始了"))
    await aggregator.add_chunk(
        AIMessageChunk(
            content="",
            tool_call_chunks=[
                {"name": "resolve_case", "args": '{"case_id"', "id": "call_1", "index": 0},
            ],
        )
    )
    await aggregator.add_chunk(
        AIMessageChunk(
            content="",
            tool_call_chunks=[
                {"name": "", "args": ': "c1"}', "id": "", "index": 0},
            ],
        )
    )

    message = aggregator.finish()

    assert message.content == "章节开始了"
    assert message.additional_kwargs["reasoning_content"] == "先分析"
    assert message.tool_calls == [
        {
            "name": "resolve_case",
            "args": {"case_id": "c1"},
            "raw_args": '{"case_id": "c1"}',
            "id": "call_1",
            "type": "tool_call",
        }
    ]
    assert len(message.tool_calls) == 1
    # 推理 token 只聚合不推送；工具调用以 tool_call 事件推送
    assert events == [
        ("output", "章节", ""),
        ("output", "开始了", ""),
        ("tool_call", "resolve_case", "started"),
    ]


@pytest.mark.asyncio
async def test_run_model_call_streams_chunks_to_events() -> None:
    events, emitter = _collect_events()
    stream = AgentStream(emitter)
    model = _StreamingLLM(
        [
            AIMessageChunk(content="你好"),
            AIMessageChunk(content="世界"),
        ]
    )

    response = await run_model_call(model, [AIMessage(content="问")], stream)

    assert response.content == "你好世界"
    assert [e for e in events if e[0] == "output"] == [
        ("output", "你好", ""),
        ("output", "世界", ""),
    ]


@pytest.mark.asyncio
async def test_run_model_call_retries_current_request_on_stream_interruption() -> None:
    """2026-08-11 用于验证断流时用同一 messages 重发当前模型请求"""
    events, emitter = _collect_events()
    stream = AgentStream(emitter)
    model = _FlakyStreamingLLM([AIMessageChunk(content="你好世界")], fail_count=1)

    response = await run_model_call(model, [AIMessage(content="问")], stream)

    assert response.content == "你好世界"
    assert len(model.captured_messages) == 2
    assert model.captured_messages[0] == [AIMessage(content="问")]
    assert model.captured_messages[1] == [AIMessage(content="问")]
    retry_events = [e for e in events if e[0] == "thinking" and "重试" in e[1]]
    assert len(retry_events) == 1


@pytest.mark.asyncio
async def test_run_model_call_exhausts_stream_retries_and_raises() -> None:
    """2026-08-11 用于验证 total_attempts=3 语义（总调用 3 次、重试 2 次），耗尽后抛出最后一次异常"""
    events, emitter = _collect_events()
    stream = AgentStream(emitter)
    model = _FlakyStreamingLLM([], fail_count=99)

    with pytest.raises(ConnectionError, match="stream interrupted"):
        await run_model_call(model, [AIMessage(content="问")], stream)

    assert len(model.captured_messages) == 3
    retry_events = [e for e in events if e[0] == "thinking" and "重试" in e[1]]
    assert len(retry_events) == 2


@pytest.mark.asyncio
async def test_run_model_call_total_attempts_one_disables_retries() -> None:
    """2026-08-12 用于验证 total_attempts=1 时关闭断流重试，只调用一次即失败"""
    events, emitter = _collect_events()
    stream = AgentStream(emitter)
    model = _FlakyStreamingLLM([], fail_count=99)

    with pytest.raises(ConnectionError, match="stream interrupted"):
        await run_model_call(model, [AIMessage(content="问")], stream, total_attempts=1)

    assert len(model.captured_messages) == 1
    retry_events = [e for e in events if e[0] == "thinking" and "重试" in e[1]]
    assert len(retry_events) == 0


@pytest.mark.asyncio
async def test_run_model_call_accumulates_usage_from_failed_attempts() -> None:
    """
    2026-08-12 用于验证断流重试时已失败尝试的 token 用量与最终用量合并记账，
    避免重试丢弃已消耗的 token。
    """
    events, emitter = _collect_events()
    stream = AgentStream(emitter)
    model = _RetryWithUsageLLM(
        failing_chunks=[
            AIMessageChunk(
                content="",
                usage_metadata={"input_tokens": 10, "output_tokens": 2, "total_tokens": 12},
            )
        ],
        success_chunks=[
            AIMessageChunk(
                content="你好",
                usage_metadata={"input_tokens": 12, "output_tokens": 8, "total_tokens": 20},
            ),
            AIMessageChunk(content="世界"),
        ],
    )

    response = await run_model_call(model, [AIMessage(content="问")], stream, total_attempts=2)

    assert response.content == "你好世界"
    assert len(model.captured_messages) == 2
    assert response.usage_metadata == {
        "input_tokens": 22,
        "output_tokens": 10,
        "total_tokens": 32,
    }


@pytest.mark.asyncio
async def test_run_model_call_keeps_retry_output_when_shorter_than_failed_attempt() -> None:
    """2026-08-13 用于验证重试输出比失败尝试已推送内容短时不再整段丢弃

    修复前按字符数跳过（skip_output_chars），重试输出更短（非确定性 LLM）时
    全部内容被清零，消息链正文凭空消失；修复后按公共前缀逐字符比对，
    重试全文保留在消息链中。
    """
    events, emitter = _collect_events()
    stream = AgentStream(emitter)
    model = _RetryWithUsageLLM(
        failing_chunks=[AIMessageChunk(content="你好好好")],
        success_chunks=[AIMessageChunk(content="你好")],
    )

    response = await run_model_call(model, [AIMessage(content="问")], stream, total_attempts=2)

    assert response.content == "你好"
    assert len(model.captured_messages) == 2


@pytest.mark.asyncio
async def test_run_model_call_skips_only_overlapping_prefix_on_retry() -> None:
    """2026-08-13 用于验证重试仅跳过与失败尝试重叠的前缀，非重叠内容完整推送"""
    events, emitter = _collect_events()
    stream = AgentStream(emitter)
    model = _RetryWithUsageLLM(
        failing_chunks=[AIMessageChunk(content="你好好好")],
        success_chunks=[AIMessageChunk(content="你好世界")],
    )

    response = await run_model_call(model, [AIMessage(content="问")], stream, total_attempts=2)

    assert response.content == "你好世界"
    # SSE 事件：失败尝试推送"你好好好"，重试跳过重叠"你好"后推送"世界"
    output_text = "".join(text for kind, text, _extra in events if kind == "output")
    assert output_text == "你好好好世界"


@pytest.mark.asyncio
async def test_run_model_call_uses_ainvoke_when_streaming_disabled() -> None:
    """2026-08-12 用于验证 stream_enabled=False（模型 streaming 配置关闭）时走 ainvoke 非流式路径"""
    events, emitter = _collect_events()
    stream = AgentStream(emitter)
    model = _ConfigDisabledStreamingLLM(AIMessage(content="完整回复"))

    response = await run_model_call(model, [AIMessage(content="问")], stream)

    assert response.content == "完整回复"
    assert model.ainvoke_calls == 1
    assert model.astream_calls == 0
    assert events == [
        ("thinking", "模型未启用流式输出，等待完整回复...", ""),
        ("output", "完整回复", ""),
    ]


def _noop_sleep(monkeypatch) -> list[float]:
    """2026-08-13 用于把 asyncio.sleep 替换为 no-op 并记录退避时长"""
    sleeps: list[float] = []

    async def fake_sleep(seconds: float) -> None:
        sleeps.append(seconds)

    monkeypatch.setattr("src.agents.stream.asyncio.sleep", fake_sleep)
    return sleeps


@pytest.mark.asyncio
async def test_run_model_call_non_streaming_retries_transient_error(monkeypatch) -> None:
    """2026-08-13 P2-6 非流式路径对网络/限流瞬态错误按 total_attempts 重试"""
    events, emitter = _collect_events()
    stream = AgentStream(emitter)
    model = _FlakyNonStreamingLLM(AIMessage(content="完整回复"), fail_count=1)
    sleeps = _noop_sleep(monkeypatch)

    response = await run_model_call(model, [AIMessage(content="问")], stream)

    assert response.content == "完整回复"
    assert model.ainvoke_calls == 2
    assert len(sleeps) == 1
    retry_events = [e for e in events if e[0] == "thinking" and "重试" in e[1]]
    assert len(retry_events) == 1


@pytest.mark.asyncio
async def test_run_model_call_non_streaming_does_not_retry_non_transient(monkeypatch) -> None:
    """2026-08-13 P2-6 非流式路径对确定性错误（非网络/限流）不重试"""
    model = _FlakyNonStreamingLLM(
        AIMessage(content=""),
        fail_count=99,
        error=RuntimeError("bad request"),
    )
    sleeps = _noop_sleep(monkeypatch)

    with pytest.raises(RuntimeError, match="bad request"):
        await run_model_call(model, [AIMessage(content="问")], None)

    assert model.ainvoke_calls == 1
    assert sleeps == []


@pytest.mark.asyncio
async def test_run_model_call_non_streaming_exhausts_transient_retries(monkeypatch) -> None:
    """2026-08-13 P2-6 非流式路径重试耗尽后抛出最后一次异常（次数 = total_attempts - 1）"""
    model = _FlakyNonStreamingLLM(AIMessage(content=""), fail_count=99)
    sleeps = _noop_sleep(monkeypatch)

    with pytest.raises(ConnectionError, match="network down"):
        await run_model_call(model, [AIMessage(content="问")], None, total_attempts=2)

    assert model.ainvoke_calls == 2
    assert len(sleeps) == 1


@pytest.mark.asyncio
async def test_run_model_call_retry_backoff_is_exponential_and_capped(monkeypatch) -> None:
    """2026-08-13 P2-12 重试退避指数递增（1s/2s）且上限 3s，仅对瞬态错误生效"""
    model = _FlakyStreamingLLM([], fail_count=99)
    sleeps = _noop_sleep(monkeypatch)

    with pytest.raises(ConnectionError, match="stream interrupted"):
        await run_model_call(model, [AIMessage(content="问")], None, total_attempts=3)

    assert model.captured_messages == [[AIMessage(content="问")] for _ in range(3)]
    assert sleeps == [1.0, 2.0]


def test_retry_backoff_seconds_exponential_with_cap() -> None:
    """2026-08-13 P2-12 退避公式：0.5s × 2^attempt，attempt≥1，上限 3s"""
    from src.agents.stream import _retry_backoff_seconds

    assert _retry_backoff_seconds(1) == 1.0
    assert _retry_backoff_seconds(2) == 2.0
    assert _retry_backoff_seconds(3) == 3.0
    assert _retry_backoff_seconds(10) == 3.0


@pytest.mark.asyncio
async def test_aggregator_announces_tool_by_name_across_retries() -> None:
    """2026-08-13 P2-8 重试后 index 相同但工具名不同时补发 started 事件（按名抑制）"""
    events, emitter = _collect_events()
    stream = AgentStream(emitter)
    # 首次尝试已宣布 write_metrics（index 0），重试改调 finish（同一 index）
    aggregator = StreamChunkAggregator(stream, announced_tools={"write_metrics"})
    await aggregator.add_chunk(
        AIMessageChunk(
            content="",
            tool_call_chunks=[{"name": "finish", "args": "{}", "id": "c1", "index": 0}],
        )
    )
    assert events == [("tool_call", "finish", "started")]

    # 同一工具名不再重复宣布（无论 index 是否变化）
    aggregator2 = StreamChunkAggregator(stream, announced_tools={"finish"})
    await aggregator2.add_chunk(
        AIMessageChunk(
            content="",
            tool_call_chunks=[{"name": "finish", "args": "{}", "id": "c2", "index": 1}],
        )
    )
    assert events == [("tool_call", "finish", "started")]


@pytest.mark.asyncio
async def test_aggregator_accumulates_usage_metadata_into_final_message() -> None:
    """
    2026-08-10 用于验证流式 chunk 的用量数值字段被累加并挂到完整 AIMessage
    """
    events, emitter = _collect_events()
    stream = AgentStream(emitter)
    aggregator = StreamChunkAggregator(stream)

    await aggregator.add_chunk(
        AIMessageChunk(
            content="你好",
            usage_metadata={"input_tokens": 10, "output_tokens": 2, "total_tokens": 12},
        )
    )
    await aggregator.add_chunk(
        AIMessageChunk(
            content="世界",
            usage_metadata={
                "input_tokens": 0,
                "output_tokens": 5,
                "total_tokens": 15,
                "input_token_details": {"cache_read": 4},
            },
        )
    )

    message = aggregator.finish()

    assert message.usage_metadata == {
        "input_tokens": 10,
        "output_tokens": 7,
        "total_tokens": 27,
        "input_token_details": {"cache_read": 4},
    }


@pytest.mark.asyncio
async def test_aggregator_accumulates_raw_gateway_usage_from_metadata() -> None:
    """
    2026-08-10 用于验证 DeepSeek 原始 token_usage 出现在响应元数据时也被累积
    """
    events, emitter = _collect_events()
    stream = AgentStream(emitter)
    aggregator = StreamChunkAggregator(stream)

    await aggregator.add_chunk(
        AIMessageChunk(
            content="",
            response_metadata={
                "token_usage": {
                    "prompt_tokens": 100,
                    "completion_tokens": 20,
                    "total_tokens": 120,
                    "prompt_cache_hit_tokens": 30,
                }
            },
        )
    )

    message = aggregator.finish()

    assert message.usage_metadata == {
        "prompt_tokens": 100,
        "completion_tokens": 20,
        "total_tokens": 120,
        "prompt_cache_hit_tokens": 30,
    }


@pytest.mark.asyncio
async def test_aggregator_prefers_standard_usage_metadata_over_raw_gateway_usage() -> None:
    """
    2026-08-13 P1-3 用于验证同一 chunk 双源（标准 usage_metadata + provider 原始
    token_usage）时只累计标准字段，避免用量翻倍；原始字段仅在标准字段缺失时回退
    """
    events, emitter = _collect_events()
    stream = AgentStream(emitter)
    aggregator = StreamChunkAggregator(stream)

    await aggregator.add_chunk(
        AIMessageChunk(
            content="你好",
            usage_metadata={"input_tokens": 10, "output_tokens": 2, "total_tokens": 12},
            response_metadata={
                "token_usage": {
                    "prompt_tokens": 100,
                    "completion_tokens": 20,
                    "total_tokens": 120,
                }
            },
        )
    )
    # 标准字段缺失的 chunk 仍走原始字段回退
    await aggregator.add_chunk(
        AIMessageChunk(
            content="世界",
            response_metadata={
                "token_usage": {
                    "prompt_tokens": 50,
                    "completion_tokens": 10,
                    "total_tokens": 60,
                }
            },
        )
    )

    message = aggregator.finish()

    assert message.usage_metadata == {
        "input_tokens": 10,
        "output_tokens": 2,
        "total_tokens": 72,
        "prompt_tokens": 50,
        "completion_tokens": 10,
    }


@pytest.mark.asyncio
async def test_aggregator_finish_omits_usage_metadata_without_usage_chunks() -> None:
    events, emitter = _collect_events()
    stream = AgentStream(emitter)
    aggregator = StreamChunkAggregator(stream)

    await aggregator.add_chunk(AIMessageChunk(content="没有用量"))
    message = aggregator.finish()

    assert message.usage_metadata is None


@pytest.mark.asyncio
async def test_run_model_call_streams_usage_metadata_into_response() -> None:
    events, emitter = _collect_events()
    stream = AgentStream(emitter)
    model = _StreamingLLM(
        [
            AIMessageChunk(content="你好"),
            AIMessageChunk(
                content="世界",
                usage_metadata={"input_tokens": 12, "output_tokens": 8, "total_tokens": 20},
            ),
        ]
    )

    response = await run_model_call(model, [AIMessage(content="问")], stream)

    assert response.usage_metadata == {"input_tokens": 12, "output_tokens": 8, "total_tokens": 20}


@pytest.mark.asyncio
async def test_run_model_call_falls_back_to_ainvoke() -> None:
    events, emitter = _collect_events()
    stream = AgentStream(emitter)
    tool_call = {"name": "finish", "args": {}, "id": "c1", "type": "tool_call"}
    model = _NonStreamingLLM(AIMessage(content="完整回复", tool_calls=[tool_call]))

    response = await run_model_call(model, [], stream)

    assert response.content == "完整回复"
    assert events == [
        ("thinking", "模型不支持流式输出，等待完整回复...", ""),
        ("output", "完整回复", ""),
        ("tool_call", "finish", "started"),
    ]


@pytest.mark.asyncio
async def test_run_model_call_without_stream_uses_plain_ainvoke() -> None:
    model = _NonStreamingLLM(AIMessage(content="回复"))
    response = await run_model_call(model, [], None)
    assert response.content == "回复"


@pytest.mark.asyncio
async def test_run_model_call_streams_without_agent_stream() -> None:
    """2026-08-10 用于验证不开启 SSE 时仍优先走 Provider 流式接口"""
    model = _StreamingLLM([AIMessageChunk(content="你好")])

    response = await run_model_call(model, [], None)

    assert response.content == "你好"
    assert model.captured_messages == [[]]


@pytest.mark.asyncio
async def test_run_model_call_records_ttft_first_visible_and_reasoning_timings(monkeypatch) -> None:
    """2026-08-10 用于验证流式调用逐项计时按 perf_counter_ns 计算"""
    ticks = iter(
        [
            0,
            100_000_000,
            300_000_000,
            400_000_000,
            500_000_000,
        ]
    )
    monkeypatch.setattr("src.agents.stream.perf_counter_ns", lambda: next(ticks))
    model = _StreamingLLM(
        [
            AIMessageChunk(content="", additional_kwargs={"reasoning_content": "先分析"}),
            AIMessageChunk(
                content="正文",
                additional_kwargs={"reasoning_content": "再推理"},
                tool_call_chunks=[{"name": "finish", "args": "{}", "id": "c1", "index": 0}],
            ),
            AIMessageChunk(content="结尾"),
        ]
    )
    captured: dict[str, object] = {}

    def on_turn_complete(message, timing) -> None:
        del message
        captured["timing"] = timing

    response = await run_model_call(model, [], None, on_turn_complete=on_turn_complete)

    assert response.content == "正文结尾"
    timing = captured["timing"]
    assert timing.ttft_ms == 100
    assert timing.first_visible_ms == 300
    assert timing.reasoning_ms == 200
    assert timing.model_ms == 500


@pytest.mark.asyncio
async def test_run_model_call_non_streaming_records_null_ttft(monkeypatch) -> None:
    """2026-08-10 用于验证非流式 Provider 的 TTFT 与推理时间记录为 NULL"""
    ticks = iter([0, 250_000_000])
    monkeypatch.setattr("src.agents.stream.perf_counter_ns", lambda: next(ticks))
    model = _NonStreamingLLM(AIMessage(content="回复"))
    captured: dict[str, object] = {}

    def on_turn_complete(message, timing) -> None:
        del message
        captured["timing"] = timing

    response = await run_model_call(model, [], None, on_turn_complete=on_turn_complete)

    assert response.content == "回复"
    timing = captured["timing"]
    assert timing.ttft_ms is None
    assert timing.first_visible_ms is None
    assert timing.reasoning_ms is None
    assert timing.model_ms == 250


@pytest.mark.asyncio
async def test_aggregator_notes_reasoning_not_streamed(monkeypatch) -> None:
    """
    2026-08-11 用于验证流式响应未探测到思考内容时回合审计记录未流出原因
    """
    ticks = iter([100_000_000, 200_000_000])
    monkeypatch.setattr("src.agents.stream.perf_counter_ns", lambda: next(ticks))
    aggregator = StreamChunkAggregator(None, started_ns=0)

    await aggregator.add_chunk(AIMessageChunk(content="正文"))

    timing = aggregator.timing()
    assert timing.reasoning_ms is None
    assert timing.ttft_ms is not None
    assert timing.timing_notes == ("reasoning_not_streamed",)


@pytest.mark.asyncio
async def test_aggregator_notes_empty_stream_without_payload(monkeypatch) -> None:
    """
    2026-08-11 用于验证流式调用完全未流出任何内容时记录无 payload 原因
    """
    ticks = iter([100_000_000, 200_000_000])
    monkeypatch.setattr("src.agents.stream.perf_counter_ns", lambda: next(ticks))
    aggregator = StreamChunkAggregator(None, started_ns=0)

    await aggregator.add_chunk(AIMessageChunk(content=""))

    timing = aggregator.timing()
    assert timing.ttft_ms is None
    assert timing.reasoning_ms is None
    assert timing.timing_notes == ("provider_stream_no_payload",)


@pytest.mark.asyncio
async def test_aggregator_omits_note_when_reasoning_streamed() -> None:
    """
    2026-08-11 用于验证思考内容正常流出时不再记录未流出原因
    """
    events, emitter = _collect_events()
    stream = AgentStream(emitter)
    aggregator = StreamChunkAggregator(stream)

    await aggregator.add_chunk(
        AIMessageChunk(content="", additional_kwargs={"reasoning_content": "先分析"})
    )

    timing = aggregator.timing()
    assert timing.reasoning_ms is not None
    assert timing.timing_notes == ()


@pytest.mark.asyncio
async def test_run_model_call_non_streaming_notes_provider_fallback(monkeypatch) -> None:
    """
    2026-08-11 用于验证非流式 Provider 降级路径记录 TTFT 与推理时间缺失原因
    """
    ticks = iter([0, 250_000_000])
    monkeypatch.setattr("src.agents.stream.perf_counter_ns", lambda: next(ticks))
    model = _NonStreamingLLM(AIMessage(content="回复"))
    captured: dict[str, object] = {}

    def on_turn_complete(message, timing) -> None:
        del message
        captured["timing"] = timing

    await run_model_call(model, [], None, on_turn_complete=on_turn_complete)

    timing = captured["timing"]
    assert timing.ttft_ms is None
    assert timing.reasoning_ms is None
    assert timing.model_ms == 250
    assert timing.timing_notes == ("provider_non_streaming",)


@pytest.mark.asyncio
async def test_emit_tool_results_marks_failure_by_content() -> None:
    events, emitter = _collect_events()
    stream = AgentStream(emitter)

    class _ToolMessage:
        def __init__(self, name: str, content: str) -> None:
            self.name = name
            self.content = content

    await emit_tool_results(
        stream,
        [
            _ToolMessage("search_text", '{"hits": 3}'),
            _ToolMessage("resolve_case", 'Error: {"error": "超时"}'),
            _ToolMessage("write_metrics", "执行失败：校验不过"),
        ],
    )

    assert events == [
        ("tool_call", "search_text", "success"),
        ("tool_call", "resolve_case", "failed"),
        ("tool_call", "write_metrics", "failed"),
    ]


@pytest.mark.asyncio
async def test_run_model_call_uses_mock_astream_when_present() -> None:
    events, emitter = _collect_events()
    stream = AgentStream(emitter)
    model = _StreamingLLM([])

    response = await run_model_call(model, [], stream)

    assert response.content == ""
    assert model.captured_messages == [[]]


def test_agent_stream_is_async_safe() -> None:
    """AgentStream 方法均为协程，可被 emitter 直接 await"""
    emitter = AsyncMock()
    stream = AgentStream(emitter)
    assert stream._emit is not None


@pytest.mark.asyncio
async def test_aggregator_records_finish_reason_from_response_metadata() -> None:
    """
    2026-08-11 用于验证流式 chunk 的 finish_reason 被采集并挂到完整消息。

    真实 Provider 实测 finish_reason 出现在倒数第二个 chunk 的 response_metadata，
    因此必须扫描全部 chunk 而不是只取最后一个。
    """
    events, emitter = _collect_events()
    stream = AgentStream(emitter)
    aggregator = StreamChunkAggregator(stream)

    await aggregator.add_chunk(AIMessageChunk(content="正文"))
    await aggregator.add_chunk(
        AIMessageChunk(
            content="",
            response_metadata={"finish_reason": "stop", "model_name": "deepseek-v4-flash"},
        )
    )
    await aggregator.add_chunk(AIMessageChunk(content=""))

    message = aggregator.finish()

    assert message.additional_kwargs["finish_reason"] == "stop"


@pytest.mark.asyncio
async def test_aggregator_keeps_latest_finish_reason_when_repeated() -> None:
    """2026-08-11 用于验证 finish_reason 出现多次时保留最后一次（length 优先于 stop）"""
    events, emitter = _collect_events()
    stream = AgentStream(emitter)
    aggregator = StreamChunkAggregator(stream)

    await aggregator.add_chunk(AIMessageChunk(content=""))
    await aggregator.add_chunk(
        AIMessageChunk(content="", response_metadata={"finish_reason": "stop"})
    )
    await aggregator.add_chunk(
        AIMessageChunk(content="", response_metadata={"finish_reason": "length"})
    )

    message = aggregator.finish()

    assert message.additional_kwargs["finish_reason"] == "length"


@pytest.mark.asyncio
async def test_merge_truncated_args_marks_call_instead_of_raw_wrap() -> None:
    """
    2026-08-11 用于验证工具参数 JSON 截断时不再静默包装 {"_raw": ...} 执行，
    而是打截断标记并保留原始文本供诊断与拒绝执行。
    """
    events, emitter = _collect_events()
    stream = AgentStream(emitter)
    aggregator = StreamChunkAggregator(stream)

    await aggregator.add_chunk(
        AIMessageChunk(
            content="",
            tool_call_chunks=[
                {
                    "name": "write_metrics",
                    "args": '{"summary": "主角入门", "emotional_va',
                    "id": "call_1",
                    "index": 0,
                }
            ],
        )
    )
    await aggregator.add_chunk(
        AIMessageChunk(
            content="",
            tool_call_chunks=[
                {"name": "", "args": 'lence": "pos', "id": "", "index": 0},
            ],
        )
    )

    message = aggregator.finish()
    calls = list(message.tool_calls)

    assert len(calls) == 1
    call = calls[0]
    assert call["name"] == "write_metrics"
    assert call["truncated"] is True
    assert call["args"] == {}
    assert call["raw_args"] == '{"summary": "主角入门", "emotional_valence": "pos'
    assert call["truncated_args"] == '{"summary": "主角入门", "emotional_valence": "pos'
    assert "_raw" not in call


def test_merge_tool_call_chunks_carries_raw_args() -> None:
    """2026-08-11 用于验证合并后的工具调用保留原始参数片段供审计"""
    from src.agents.stream import _merge_tool_call_chunks

    chunks = [
        {"index": 0, "name": "push_case", "args": '{"description": "', "id": "call_1"},
        {"index": 0, "name": "", "args": '关键词"}', "id": ""},
    ]
    calls = _merge_tool_call_chunks(chunks)
    assert calls[0]["name"] == "push_case"
    assert calls[0]["args"] == {"description": "关键词"}
    assert calls[0]["raw_args"] == '{"description": "关键词"}'
