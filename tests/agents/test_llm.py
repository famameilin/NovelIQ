"""LangChain 模型桥接测试"""

from unittest.mock import patch

from src.agents.llm import build_chat_model
from src.config import TaskModelConfig


def test_build_chat_model_passes_top_p_and_cloud_streaming() -> None:
    """
    2026-08-04 用于验证云端 Agent 模型接收 top_p 与流式配置
    """
    config = TaskModelConfig(
        base_url="https://api.example.com/v1",
        model="test-model",
        api_key="test-key",
        top_p=0.42,
        stream_enabled=True,
        stream_cloud_only=True,
    )

    with patch("src.agents.llm.ChatOpenAI") as chat_openai:
        build_chat_model(config=config)

    kwargs = chat_openai.call_args.kwargs
    assert kwargs["top_p"] == 0.42
    assert kwargs["streaming"] is True


def test_build_chat_model_disables_cloud_only_streaming_for_local_endpoint() -> None:
    """
    2026-08-04 用于验证 cloud_only 配置不会对本地服务错误开启流式调用
    """
    config = TaskModelConfig(
        base_url="http://localhost:8000/v1",
        model="test-model",
        api_key="test-key",
        stream_enabled=True,
        stream_cloud_only=True,
    )

    with patch("src.agents.llm.ChatOpenAI") as chat_openai:
        build_chat_model(config=config)

    assert chat_openai.call_args.kwargs["streaming"] is False
