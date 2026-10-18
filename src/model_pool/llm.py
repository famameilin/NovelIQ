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

from src.config import TaskModelConfig, TaskType
from src.model_pool.configuration import load_task_config

_reasoning_content_patch_installed = False


def _install_reasoning_content_patch() -> None:
    """包装 langchain-openai 的 _convert_delta_to_message_chunk，
    把流式 reasoning_content 增量合并进 additional_kwargs

    langchain-openai 1.4.1/1.4.3 的 _convert_delta_to_message_chunk 只提取
    content / function_call / tool_calls，Qwen 系网关返回的 delta.reasoning_content
    被静默丢弃，导致审计与流式聚合探测不到思考内容。
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
    # 流式必须显式开 include_usage：否则网关不下发 usage 块，token 记账退化成本地估算；
    # 聚合器（stream_aggregator）把末 chunk 的 usage_metadata 装回响应供其上报
    extra_body = {**(extra_body or {}), "stream_options": {"include_usage": True}}

    # LLM 调用固定开启流式；断流重试与计时统一由 stream.py 按 total_attempts 处理
    return ChatOpenAI(
        model=cfg.model or "",
        base_url=cfg.base_url,
        api_key=SecretStr(cfg.api_key) if cfg.api_key else None,
        temperature=cfg.temperature,
        top_p=cfg.top_p,
        # 显式补全上限：思考模式 provider 默认值随模式漂移，思考撑满预算时载荷尾部
        # 会被截断；langchain-openai 新版参数名为 max_completion_tokens
        # （OpenAI 新参数，旧 max_tokens 已弃用）
        max_completion_tokens=cfg.max_tokens,
        # 读超时 180s 必须高于 stream.py 的内容进度看门狗（150s）：层级倒挂会让网关死气
        # 死在 httpx 层，ReadTimeout 空串进审计不可诊断；首字节排队超 120s 属"慢但活着"
        timeout=cfg.timeout_s if cfg.timeout_s is not None else 180,
        streaming=True,
        # 流块间隙看门狗放宽到 600s：网关限流队列/思考停顿超 2 分钟是常态，
        # 真死连接仍由 httpx 读超时兜底
        stream_chunk_timeout=600,
        # 断流重试由 stream.py 按 total_attempts 统一负责，关闭 SDK 层重试：
        # 重试次数只由 total_attempts 一处配置决定
        max_retries=0,
        extra_body=extra_body,
    )
