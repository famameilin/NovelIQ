"""Agent 模型用量审计测试"""

from types import SimpleNamespace
from unittest.mock import MagicMock

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from src.model_pool.usage import (
    build_token_usage_callback,
    estimate_agent_token_usage,
    extract_agent_token_usage,
)
from src.utils.token_counter import count_tokens


def test_extract_agent_token_usage_reads_langchain_usage_metadata() -> None:
    """验证 LangChain 标准 usage_metadata 被解析为统一用量"""
    message = AIMessage(
        content="完成",
        usage_metadata={"input_tokens": 12, "output_tokens": 8, "total_tokens": 20},
    )

    usage = extract_agent_token_usage(message)

    assert usage is not None
    assert usage.prompt_tokens == 12
    assert usage.completion_tokens == 8
    assert usage.total_tokens == 20


def test_extract_agent_token_usage_reads_deepseek_raw_usage() -> None:
    """验证 DeepSeek 原始 usage 结构被解析为统一用量"""
    message = AIMessage(
        content="完成",
        response_metadata={
            "token_usage": {
                "prompt_tokens": 100,
                "completion_tokens": 20,
                "total_tokens": 120,
                "prompt_cache_hit_tokens": 30,
            }
        },
    )

    usage = extract_agent_token_usage(message)

    assert usage is not None
    assert usage.prompt_tokens == 100
    assert usage.completion_tokens == 20
    assert usage.total_tokens == 120
    assert usage.cache_read_tokens == 30
    assert usage.estimated is False


def test_extract_agent_token_usage_reads_cache_read_aliases() -> None:
    """验证缓存命中 token 的三种网关字段别名探测顺序"""
    langchain_style = AIMessage(
        content="x",
        usage_metadata={
            "input_tokens": 12,
            "output_tokens": 8,
            "total_tokens": 20,
            "input_token_details": {"cache_read": 4},
        },
    )
    deepseek_style = AIMessage(
        content="x",
        response_metadata={
            "token_usage": {
                "prompt_tokens": 12,
                "completion_tokens": 8,
                "total_tokens": 20,
                "prompt_cache_hit_tokens": 6,
            }
        },
    )
    openai_style = AIMessage(
        content="x",
        response_metadata={
            "token_usage": {
                "prompt_tokens": 12,
                "completion_tokens": 8,
                "total_tokens": 20,
                "prompt_tokens_details": {"cached_tokens": 9},
            }
        },
    )
    no_cache = AIMessage(
        content="x",
        usage_metadata={"input_tokens": 12, "output_tokens": 8, "total_tokens": 20},
    )

    assert extract_agent_token_usage(langchain_style).cache_read_tokens == 4
    assert extract_agent_token_usage(deepseek_style).cache_read_tokens == 6
    assert extract_agent_token_usage(openai_style).cache_read_tokens == 9
    assert extract_agent_token_usage(no_cache).cache_read_tokens is None


def test_extract_agent_token_usage_reads_cost() -> None:
    """验证网关费用字段读取与字符串转 float 行为"""
    numeric_cost = AIMessage(
        content="x",
        usage_metadata={"input_tokens": 1, "output_tokens": 2, "total_tokens": 3, "cost": 0.5},
    )
    string_total_cost = AIMessage(
        content="x",
        response_metadata={
            "token_usage": {
                "prompt_tokens": 1,
                "completion_tokens": 2,
                "total_tokens": 3,
                "total_cost": "0.0033",
            }
        },
    )
    invalid_cost = AIMessage(
        content="x",
        response_metadata={
            "token_usage": {
                "prompt_tokens": 1,
                "completion_tokens": 2,
                "total_tokens": 3,
                "total_cost": "not-a-number",
            }
        },
    )
    no_cost = AIMessage(
        content="x",
        usage_metadata={"input_tokens": 1, "output_tokens": 2, "total_tokens": 3},
    )

    assert extract_agent_token_usage(numeric_cost).cost == 0.5
    assert extract_agent_token_usage(string_total_cost).cost == 0.0033
    assert extract_agent_token_usage(invalid_cost).cost is None
    assert extract_agent_token_usage(no_cost).cost is None


def test_extract_agent_token_usage_reads_reasoning_tokens() -> None:
    """验证 usage_metadata.output_token_details.reasoning 被读取"""
    message = AIMessage(
        content="x",
        usage_metadata={
            "input_tokens": 10,
            "output_tokens": 5,
            "total_tokens": 15,
            "output_token_details": {"reasoning": 3},
        },
    )

    assert extract_agent_token_usage(message).reasoning_tokens == 3


def test_estimate_agent_token_usage_returns_estimated_records_per_ai_message() -> None:
    """验证无 Provider 用量时按消息文本估算每个 AI 响应"""
    messages = [
        HumanMessage(content="你好，请分析这段内容"),
        AIMessage(content="分析结果"),
        ToolMessage(content="ok", tool_call_id="call_1"),
        AIMessage(content="最终结论"),
    ]

    estimates = estimate_agent_token_usage(messages)

    assert len(estimates) == 2
    for estimate in estimates:
        assert estimate.estimated is True
        assert estimate.cache_read_tokens is None
        assert estimate.cost is None
        assert estimate.total_tokens == estimate.prompt_tokens + estimate.completion_tokens
    assert estimates[0].prompt_tokens >= count_tokens("你好，请分析这段内容")
    assert estimates[1].prompt_tokens > estimates[0].prompt_tokens + estimates[0].completion_tokens
    assert estimates[0].completion_tokens == count_tokens("分析结果")
    assert estimates[1].completion_tokens == count_tokens("最终结论")


def test_estimate_agent_token_usage_returns_empty_without_ai_messages() -> None:
    """验证没有 AI 响应时估算列表为空"""
    assert estimate_agent_token_usage([HumanMessage(content="hi")]) == []


def test_build_token_usage_callback_records_embedding_usage() -> None:
    """验证 EmbeddingClient 的 token 用量回调逐笔落入账本"""
    bus = MagicMock()
    callback = build_token_usage_callback(bus=bus, run_id="run-1")
    callback("embedding", "embed-model", 10, 10, None, 7)
    message = bus.publish.call_args.args[0]
    assert message.payload["method"] == "nonagent_usage"
    kwargs = message.payload["kwargs"]
    assert kwargs["run_id"] == "run-1"
    assert kwargs["task_type"] == "embedding"
    assert kwargs["call_type"] == "embedding"
    assert kwargs["model"] == "embed-model"
    assert kwargs["prompt_tokens"] == 10
    assert kwargs["total_tokens"] == 10
    assert kwargs["chapter_id"] == 7


def test_turn_usage_records_estimates_missing_usage() -> None:
    """验证回合观察器在 Provider 无用量时记录本地估算"""
    from src.agents.turn_observer import _usage_for_turn

    request = [AIMessage(content="问")]
    response = AIMessage(content="分析结果")

    usage = _usage_for_turn(request, response)

    assert usage is not None
    assert usage["prompt_tokens"] >= 0
    assert usage["completion_tokens"] > 0
    assert usage["cache_read_tokens"] is None
    assert usage["cost"] is None
    assert usage["accounting_source"] == "estimated"


def test_turn_usage_records_keeps_reported_usage() -> None:
    """验证回合观察器实报路径保留缓存/费用/推理明细"""
    from src.agents.turn_observer import _usage_for_turn

    request = [AIMessage(content="问")]
    response = AIMessage(
        content="完成",
        usage_metadata={
            "input_tokens": 100,
            "output_tokens": 20,
            "total_tokens": 120,
            "input_token_details": {"cache_read": 30},
            "output_token_details": {"reasoning": 5},
            "cost": "0.42",
        },
    )

    usage = _usage_for_turn(request, response)

    assert usage is not None
    assert usage["cache_read_tokens"] == 30
    assert usage["cost"] == 0.42
    assert usage["accounting_source"] == "reported"
    assert usage["reasoning_tokens"] == 5


def test_estimation_includes_tool_code_history_and_bound_tool_catalog() -> None:
    from src.agents.turn_observer import _usage_for_turn

    response = AIMessage(content="", tool_calls=[{
        "id": "call", "name": "execute_code", "args": {"code": "print('evidence')" * 100},
    }])
    simple = _usage_for_turn([HumanMessage(content="办案例")], AIMessage(content=""))
    usage = _usage_for_turn([HumanMessage(content="办案例")], response, tool_schema_tokens=500)
    repeated = _usage_for_turn([HumanMessage(content="办案例"), response], response, tool_schema_tokens=500)
    assert usage["completion_tokens"] > 0
    assert usage["prompt_tokens"] == simple["prompt_tokens"] + 500
    assert repeated["prompt_tokens"] >= usage["prompt_tokens"] + usage["completion_tokens"]


def test_provider_catalog_reaches_estimated_turn_usage() -> None:
    from src.agents.stream_audit import ModelCallTiming, _provider_request_metadata
    from src.agents.turn_observer import AgentTurnObserver, _usage_for_turn

    model = SimpleNamespace(bound=SimpleNamespace(model_name="test"), kwargs={"tools": [{
        "type": "function", "function": {
            "name": "execute_code", "description": "真实工具目录与参数" * 200,
            "parameters": {"type": "object", "properties": {"code": {"type": "string"}}},
        },
    }]})
    recorder = MagicMock()
    observer = AgentTurnObserver(recorder, invocation_id=1, context={})
    messages = [HumanMessage(content="办理案例")]
    response = AIMessage(content="", tool_calls=[{
        "name": "execute_code", "args": {"code": "claim_random_case()"}, "id": "call",
    }])
    observer.begin_provider_turn(
        context_summary={}, request_messages=messages,
        provider_request=_provider_request_metadata(model, attempt=1), started_ns=1,
    )
    observer.complete_provider_turn(response_message=response, timing=ModelCallTiming(model_ms=10))
    usage = recorder.finish_turn.call_args.kwargs["token_usage"]
    assert usage["prompt_tokens"] > _usage_for_turn(messages, response)["prompt_tokens"] + 200
    assert usage["completion_tokens"] > 0 and usage["accounting_source"] == "estimated"
    assert usage["cost"] is None


def test_nested_tool_wall_time_includes_outer_interval_without_summing_inner_time() -> None:
    from src.agents.stream_audit import ModelCallTiming
    from src.agents.turn_observer import AgentTurnObserver

    recorder = MagicMock()
    observer = AgentTurnObserver(recorder, invocation_id=1, context={})
    observer.begin_provider_turn(context_summary={}, request_messages=[], provider_request={}, started_ns=1)
    observer.complete_provider_turn(
        response_message=AIMessage(content="", tool_calls=[{
            "name": "execute_code", "args": {"code": "claim_random_case()"}, "id": "outer",
        }]), timing=ModelCallTiming(model_ms=10),
    )
    for name, start, duration in (("claim_random_case", 200, 30), ("execute_code", 100, 200)):
        observer.record_tool_call(
            call_index=0, tool_name=name, request_args={}, response={}, receipt={}, error=None,
            tool_duration_ms=duration, started_ns=start * 1_000_000,
        )
    observer.close_turn()
    assert recorder.update_turn_timings.call_args.kwargs["tool_wall_ms"] == 200
