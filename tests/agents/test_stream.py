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


def _collect_events() -> list[tuple[str, str]]:
    """构造收集事件的 emitter 与记录容器"""
    events: list[tuple[str, str]] = []

    async def emitter(event) -> None:
        events.append((event.action, event.content))

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


@pytest.mark.asyncio
async def test_agent_stream_emits_thinking_and_output_events() -> None:
    events, emitter = _collect_events()
    stream = AgentStream(emitter, chunk_id=7, sub_stage="chapter_agent")

    await stream.thinking("正在推理...")
    await stream.output("模型说了一句")
    await stream.tool_call_started("resolve_case")
    await stream.tool_call_succeeded("resolve_case", "accepted")
    await stream.tool_call_failed("write_metrics", "参数错误")

    assert events == [
        ("thinking", "正在推理..."),
        ("output", "模型说了一句"),
        ("thinking", "正在调用工具 resolve_case"),
        ("thinking", "工具 resolve_case 执行成功：accepted"),
        ("thinking", "工具 write_metrics 执行失败：参数错误"),
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
            "id": "call_1",
            "type": "tool_call",
        }
    ]
    assert aggregator.has_tool_calls()
    assert [e for e in events if e[0] == "thinking"] == [
        ("thinking", "先分析"),
        ("thinking", "正在调用工具 resolve_case"),
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
        ("output", "你好"),
        ("output", "世界"),
    ]


@pytest.mark.asyncio
async def test_run_model_call_falls_back_to_ainvoke() -> None:
    events, emitter = _collect_events()
    stream = AgentStream(emitter)
    tool_call = {"name": "finish", "args": {}, "id": "c1", "type": "tool_call"}
    model = _NonStreamingLLM(AIMessage(content="完整回复", tool_calls=[tool_call]))

    response = await run_model_call(model, [], stream)

    assert response.content == "完整回复"
    assert events == [
        ("thinking", "模型不支持流式输出，等待完整回复..."),
        ("output", "完整回复"),
        ("thinking", "正在调用工具 finish"),
    ]


@pytest.mark.asyncio
async def test_run_model_call_without_stream_uses_plain_ainvoke() -> None:
    model = _NonStreamingLLM(AIMessage(content="回复"))
    response = await run_model_call(model, [], None)
    assert response.content == "回复"


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
        ("thinking", "工具 search_text 执行成功：{\"hits\": 3}"),
        ("thinking", "工具 resolve_case 执行失败：Error: {\"error\": \"超时\"}"),
        ("thinking", "工具 write_metrics 执行失败：执行失败：校验不过"),
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
