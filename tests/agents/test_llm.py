"""LangChain 模型桥接测试"""


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
