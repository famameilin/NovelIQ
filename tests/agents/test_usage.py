"""Agent 模型用量审计测试"""

from unittest.mock import MagicMock, patch

from langchain_core.messages import AIMessage

from src.agents.usage import extract_agent_token_usage, record_agent_token_usage


def test_extract_agent_token_usage_reads_langchain_usage_metadata() -> None:
    """
    2026-08-04 用于验证 LangChain 标准 usage_metadata 被解析为统一用量
    """
    message = AIMessage(
        content="完成",
        usage_metadata={"input_tokens": 12, "output_tokens": 8, "total_tokens": 20},
    )

    usage = extract_agent_token_usage(message)

    assert usage is not None
    assert usage.prompt_tokens == 12
    assert usage.completion_tokens == 8
    assert usage.total_tokens == 20


def test_record_agent_token_usage_skips_missing_or_zero_provider_usage() -> None:
    """
    2026-08-04 用于防止无 Provider 用量的 Agent 响应伪造零 Token 已覆盖记录
    """
    session = MagicMock()
    llm = MagicMock(model_name="agent-model")
    messages = [
        AIMessage(content="无用量"),
        AIMessage(content="零用量", usage_metadata={"input_tokens": 0, "output_tokens": 0, "total_tokens": 0}),
    ]

    with patch("src.agents.usage.StatsRepository") as stats_repository:
        record_agent_token_usage(
            session=session,
            run_id="run-1",
            novel_id="novel-1",
            task_type="annotation",
            call_type="agent",
            chunk_id=3,
            llm=llm,
            messages=messages,
        )

    stats_repository.return_value.insert_token_usage.assert_not_called()


def test_record_agent_token_usage_persists_each_response_with_provider_usage() -> None:
    """
    2026-08-04 用于验证多轮 Agent 调用逐条落入 annotation Token 账本
    """
    session = MagicMock()
    llm = MagicMock(model_name="agent-model")
    messages = [
        AIMessage(content="取证", usage_metadata={"input_tokens": 9, "output_tokens": 3, "total_tokens": 12}),
        AIMessage(content="完成", usage_metadata={"input_tokens": 11, "output_tokens": 5, "total_tokens": 16}),
    ]

    with patch("src.agents.usage.StatsRepository") as stats_repository:
        record_agent_token_usage(
            session=session,
            run_id="run-1",
            novel_id="novel-1",
            task_type="annotation",
            call_type="agent",
            chunk_id=3,
            llm=llm,
            messages=messages,
        )

    assert stats_repository.return_value.insert_token_usage.call_count == 2
    first_call = stats_repository.return_value.insert_token_usage.call_args_list[0].kwargs
    assert first_call["prompt_tokens"] == 9
    assert first_call["completion_tokens"] == 3
    assert first_call["total_tokens"] == 12
