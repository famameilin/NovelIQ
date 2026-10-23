"""上下文容量测量、区间选择与摘要压缩行为"""

from __future__ import annotations

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage

from src.agents.context_compaction import (
    build_fallback_note,
    build_summary_messages,
    build_visible_messages,
    context_limits,
    frame_summary,
    measure_context_tokens,
    message_tokens,
    response_text,
    select_compaction,
    split_prefix,
)
from tests.agents.test_diagnosis_agent import _analysis_payload, build_graph, call, run_graph


def _ai(content: str = "", *, tool_calls=None, prompt_tokens: int | None = None) -> AIMessage:
    usage = (
        {"input_tokens": prompt_tokens, "output_tokens": 10, "total_tokens": prompt_tokens + 10}
        if prompt_tokens is not None
        else None
    )
    return AIMessage(content=content, tool_calls=tool_calls or [], usage_metadata=usage)


def _tool(text: str = "ok") -> ToolMessage:
    return ToolMessage(content=text, tool_call_id="call-1")


def _round(code: str, prompt_tokens: int) -> AIMessage:
    return _ai(
        tool_calls=[call("execute_code", {"code": code}, id=f"call-{prompt_tokens}")],
        prompt_tokens=prompt_tokens,
    )


def test_measure_context_tokens_prefers_provider_prompt_tokens() -> None:
    first = _ai(tool_calls=[call("execute_code", {"code": "x"})], prompt_tokens=1000)
    messages = [SystemMessage(content="sys"), HumanMessage(content="task"), first, _tool("receipt")]
    expected = 1000 + message_tokens(first) + message_tokens(messages[-1])
    assert measure_context_tokens(messages) == expected


def test_measure_context_tokens_falls_back_to_local_estimate() -> None:
    messages = [
        SystemMessage(content="sys"),
        HumanMessage(content="task"),
        _ai(tool_calls=[call("execute_code", {"code": "x"})]),
        _tool("receipt"),
    ]
    expected = 500 + sum(message_tokens(message) for message in messages)
    assert measure_context_tokens(messages, tool_schema_tokens=500) == expected


def test_split_prefix_keeps_initial_task_and_tool_rounds() -> None:
    first = _ai(tool_calls=[call("execute_code", {"code": "a"})])
    second = _ai(tool_calls=[call("execute_code", {"code": "b"})])
    messages = [
        SystemMessage(content="sys"),
        HumanMessage(content="task"),
        first,
        _tool("a"),
        second,
        _tool("b"),
    ]
    prefix, blocks = split_prefix(messages)
    assert prefix == messages[:2]
    assert blocks == [[first, messages[3]], [second, messages[5]]]


def test_select_compaction_drops_oldest_whole_rounds_and_keeps_prefix() -> None:
    first = _ai(tool_calls=[call("execute_code", {"code": "a"})])
    second = _ai(tool_calls=[call("execute_code", {"code": "b"})])
    third = _ai(tool_calls=[call("execute_code", {"code": "c"})])
    messages = [
        SystemMessage(content="sys"),
        HumanMessage(content="task"),
        first,
        _tool("a"),
        second,
        _tool("b"),
        third,
        _tool("c"),
    ]
    selection = select_compaction(messages, retain_tokens=0)
    assert selection is not None
    shadowed, kept = selection
    assert shadowed == [first, messages[3], second, messages[5]]
    assert kept == [messages[0], messages[1], third, messages[7]]
    assert select_compaction(messages, retain_tokens=10**9) is None


def test_build_visible_messages_inserts_summary_after_prefix() -> None:
    first = _ai(tool_calls=[call("execute_code", {"code": "a"})])
    second = _ai(content="tail")
    messages = [SystemMessage(content="sys"), HumanMessage(content="task"), first, _tool("a"), second]
    visible = build_visible_messages(messages, summary="CHECKPOINT", shadowed_count=2)
    assert visible[0].type == "system"
    assert visible[1].content == "task"
    assert visible[2].content == "CHECKPOINT"
    assert visible[3] is second


def test_build_summary_messages_includes_system_task_previous_summary_and_shadowed() -> None:
    first = _ai(tool_calls=[call("execute_code", {"code": "a"})])
    prefix = [SystemMessage(content="sys"), HumanMessage(content="task")]
    shadowed = [first, _tool("a")]
    built = build_summary_messages(prefix, previous_summary="PREV", shadowed=shadowed)
    assert built[0].type == "system"
    assert built[1].content == "task"
    assert built[2].content == "PREV"
    assert built[3] is first
    assert built[4].type == "tool"
    assert "压缩引擎" in str(built[-1].content)


def test_build_summary_messages_starts_with_user_turn_without_prefix() -> None:
    built = build_summary_messages([], previous_summary=None, shadowed=[_ai(content="a")])
    assert built[0].type == "human"
    assert "压缩引擎" in str(built[-1].content)


def test_frame_summary_wraps_checkpoint() -> None:
    framed = frame_summary("## 主要任务与范围\n- 测试")
    assert "自动压缩摘要" in framed
    assert "<compacted-summary>" in framed
    assert "测试" in framed


def test_fallback_note_reports_removed_rounds() -> None:
    note = build_fallback_note([_ai(tool_calls=[call("execute_code", {"code": "a"})]), _tool("a")])
    assert "1 轮" in note
    assert "2 条消息" in note


def test_response_text_extracts_text_blocks() -> None:
    assert response_text(AIMessage(content="hello")) == "hello"
    assert response_text(
        AIMessage(content=[{"type": "text", "text": "a"}, {"type": "image", "url": "x"}])
    ) == "a"
    assert response_text(AIMessage(content="")) == ""


def test_context_limits_use_ninety_percent_trigger_and_sixteen_percent_tail() -> None:
    assert context_limits(128000) == (115200, 20480)


async def test_graph_compacts_with_summary_before_main_request() -> None:
    good = f"write_diagnosis(analysis={_analysis_payload()})\nfinish()"
    summary = "## 主要任务与范围\n- 案例筛选\n## 关键实体与术语\n（无）"
    responses = [
        _round("print('x' * 800)", 900),
        _round("print('y' * 800)", 900),
        AIMessage(content=summary, usage_metadata={"input_tokens": 900, "output_tokens": 20, "total_tokens": 920}),
        _round(good, 300),
    ]
    graph, model, _ = build_graph(responses, maximum=5, context_window_tokens=300)
    result = await run_graph(graph)
    assert result.get("completion_ok") is True
    assert len(model.requests) == 4
    assert "压缩引擎" in str(model.requests[2][-1].content)
    rendered = "\n".join(str(getattr(message, "content", "")) for message in model.requests[3])
    assert "自动压缩摘要" in rendered
    assert summary in rendered
    assert "x" * 100 not in rendered


async def test_graph_without_context_window_keeps_full_history() -> None:
    good = f"write_diagnosis(analysis={_analysis_payload()})\nfinish()"
    responses = [_round("print('x')", 900), _round(good, 300)]
    graph, model, _ = build_graph(responses, maximum=5)
    result = await run_graph(graph)
    assert result.get("completion_ok") is True
    assert len(model.requests) == 2
    assert all("压缩引擎" not in str(getattr(message, "content", "")) for message in model.requests[1])


async def test_graph_falls_back_when_summary_is_empty() -> None:
    good = f"write_diagnosis(analysis={_analysis_payload()})\nfinish()"
    responses = [
        _round("print('x' * 800)", 900),
        _round("print('y' * 800)", 900),
        AIMessage(content="", usage_metadata={"input_tokens": 900, "output_tokens": 0, "total_tokens": 900}),
        _round(good, 300),
    ]
    graph, model, _ = build_graph(responses, maximum=5, context_window_tokens=300)
    result = await run_graph(graph)
    assert result.get("completion_ok") is True
    rendered = "\n".join(str(getattr(message, "content", "")) for message in model.requests[3])
    assert "上下文压缩" in rendered
    assert "自动压缩摘要" not in rendered
