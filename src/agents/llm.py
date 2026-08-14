"""
LangChain 模型桥接

将项目 TaskModelConfig（base_url/model/api_key/thinking）桥接到 langchain-openai ChatOpenAI
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from langchain_core.messages import AIMessageChunk, BaseMessageChunk
from langchain_openai import ChatOpenAI
from pydantic import SecretStr

from src.config import TaskModelConfig, TaskType, load_task_config

_reasoning_content_patch_installed = False


def _install_reasoning_content_patch() -> None:
    """
    2026-08-10 用于修复 langchain-openai 流式解析丢弃 reasoning_content 的问题

    langchain-openai 1.4.1/1.4.3 的 _convert_delta_to_message_chunk 只提取
    content / function_call / tool_calls，Qwen 系网关返回的 delta.reasoning_content
    被静默丢弃（官方 docstring 明确不转发），导致审计与流式聚合探测不到思考内容。
    这里包装该函数，把 reasoning_content 增量合并进 additional_kwargs。
    """
    global _reasoning_content_patch_installed
    if _reasoning_content_patch_installed:
        return

    import langchain_openai.chat_models.base as base

    original = base._convert_delta_to_message_chunk

    def _patched_convert(
        delta: Mapping[str, Any],
        default_class: type[BaseMessageChunk],
    ) -> BaseMessageChunk:
        message = original(delta, default_class)
        reasoning = delta.get("reasoning_content")
        if reasoning and isinstance(message, AIMessageChunk):
            previous = message.additional_kwargs.get("reasoning_content", "")
            message.additional_kwargs["reasoning_content"] = previous + str(reasoning)
        return message

    base._convert_delta_to_message_chunk = _patched_convert  # type: ignore[assignment]
    _reasoning_content_patch_installed = True


def build_chat_model(
    task_type: TaskType = "annotation",
    config: TaskModelConfig | None = None,
) -> ChatOpenAI:
    """
    根据任务类型构建 ChatOpenAI 实例

    - 复用项目统一的模型配置（base_url / model / api_key / temperature）
    - thinking 启用时透传 `extra_body={"think": True}`（Qwen 系 OpenAI 兼容服务）
    - 构建时安装 reasoning_content 流式补丁（幂等）
    """
    _install_reasoning_content_patch()
    cfg = config or load_task_config(task_type)
    cfg.validate()

    extra_body: dict[str, object] | None = None
    if cfg.thinking_enabled:
        extra_body = {"think": True}

    streaming = cfg.stream_enabled

    return ChatOpenAI(
        model=cfg.model or "",
        base_url=cfg.base_url,
        api_key=SecretStr(cfg.api_key) if cfg.api_key else None,
        temperature=cfg.temperature,
        top_p=cfg.top_p,
        timeout=cfg.timeout_s if cfg.timeout_s is not None else 120,
        streaming=streaming,
        # 2026-08-12 断流重试由 stream.py 按 total_attempts 统一负责；
        # SDK 层再叠加 max_retries 会让最坏请求次数成倍膨胀（流式中断时叠加后最多 8 次）。
        # 关闭 SDK 层重试，重试次数只由 total_attempts 一处配置决定。
        max_retries=0,
        extra_body=extra_body,
    )
