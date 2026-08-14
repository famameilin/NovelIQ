"""LangChain 模型桥接测试"""

from unittest.mock import patch

from src.agents.llm import build_chat_model
from src.config import TaskModelConfig


def test_build_chat_model_passes_top_p_and_streaming_config() -> None:
    """
    2026-08-04 用于验证模型构建透传 top_p 与 stream_enabled 流式开关
    """
    config = TaskModelConfig(
        base_url="https://api.example.com/v1",
        model="test-model",
        api_key="test-key",
        top_p=0.42,
        stream_enabled=True,
    )

    with patch("src.agents.llm.ChatOpenAI") as chat_openai:
        build_chat_model(config=config)

    kwargs = chat_openai.call_args.kwargs
    assert kwargs["top_p"] == 0.42
    assert kwargs["streaming"] is True
    assert kwargs["max_retries"] == 0


def test_build_chat_model_streaming_follows_stream_enabled_for_local_endpoint() -> None:
    """
    2026-08-12 用于验证本地端点同样遵循 stream_enabled（产品已决策不再区分本地/云端）
    """
    config = TaskModelConfig(
        base_url="http://localhost:8000/v1",
        model="test-model",
        api_key="test-key",
        stream_enabled=True,
    )

    with patch("src.agents.llm.ChatOpenAI") as chat_openai:
        build_chat_model(config=config)

    assert chat_openai.call_args.kwargs["streaming"] is True


def test_build_chat_model_disables_streaming_when_stream_enabled_false() -> None:
    """
    2026-08-12 用于验证 stream_enabled=False 时关闭流式调用
    """
    config = TaskModelConfig(
        base_url="https://api.example.com/v1",
        model="test-model",
        api_key="test-key",
        stream_enabled=False,
    )

    with patch("src.agents.llm.ChatOpenAI") as chat_openai:
        build_chat_model(config=config)

    assert chat_openai.call_args.kwargs["streaming"] is False


def test_reasoning_content_patch_preserves_delta_reasoning() -> None:
    """
    2026-08-14 D9：验证 langchain-openai 私有函数补丁生效——Qwen 系网关
    delta.reasoning_content 被合并进 AIMessageChunk.additional_kwargs，
    防止依赖升级后补丁静默失效（思考内容丢失）
    """
    import langchain_openai.chat_models.base as base
    from langchain_core.messages import AIMessageChunk

    from src.agents.llm import _install_reasoning_content_patch

    _install_reasoning_content_patch()

    delta = {
        "role": "assistant",
        "content": "正式输出",
        "reasoning_content": "思考中",
    }
    chunk = base._convert_delta_to_message_chunk(delta, AIMessageChunk)

    assert isinstance(chunk, AIMessageChunk)
    assert chunk.content == "正式输出"
    assert chunk.additional_kwargs.get("reasoning_content") == "思考中"
