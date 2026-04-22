"""
消歧API调用模块

创建时间: 2026-03-18
创建者: TraeAI
任务: code-quality-refactor - Task 9 拆分disambiguation_client.py
说明: 提取消歧API调用相关逻辑

修改时间: 2026-03-21
修改者: TraeAI
任务: migrate-litellm-to-openai-sdk
修改内容: 使用 OpenAI SDK，移除 get_model_with_provider 调用

修改时间: 2026-03-22
修改者: TraeAI
任务: code-quality-review
修改内容: 移除硬编码的 "gpt-4" 默认值，改用 config.model（已通过 validate 确保存在）

修改时间: 2026-04-07
修改者: TraeAI
任务: websocket-streaming-progress
修改内容: 添加 stream_callback 参数支持
"""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from loguru import logger

from src.api.models.events import StreamEvent

from ..schema import CloudDisambiguateResponseModel, DisambiguateResponseModel
from .result_builder import normalize_disambiguate_response

if TYPE_CHECKING:
    from src.config import TaskModelConfig

    from ..base import BaseModelClient


async def call_disambiguate_api(
    client: BaseModelClient,
    config: TaskModelConfig,
    messages: list[dict[str, str]],
    log_type: str,
    emitter: Callable[[StreamEvent], Any] | None = None,
) -> DisambiguateResponseModel:
    """
    统一调用消歧API，处理响应字符串/对象两种情况

    创建时间: 2026-03-13
    创建者: TraeAI
    任务: refactor-model-interaction-layer

    修改时间: 2026-03-16
    修改者: TraeAI
    任务: 重构本地消歧客户端集成 Instructor
    修改内容: 使用 Instructor 实现结构化输出，直接返回 DisambiguateResponseModel

    修改时间: 2026-03-17
    修改者: TraeAI
    任务: 移除 Instructor 依赖
    修改内容: 使用 LiteLLM 的 JSON Schema 模式替代 Instructor

    修改时间: 2026-03-18
    修改者: TraeAI
    任务: code-quality-refactor - Task 9 拆分disambiguation_client.py
    修改内容: 提取为独立模块函数

    修改时间: 2026-03-23
    修改者: TraeAI
    任务: migrate-litellm-to-openai-sdk
    修改内容: 使用 OpenAI SDK，移除 get_model_with_provider 调用

    修改时间: 2026-03-23
    修改者: TraeAI
    任务: fix/disambig-thinking-save
    修改内容: 添加 reasoning_effort 参数，移除 is_cloud 参数（本地和云端统一使用 reasoning_effort）

    修改时间: 2026-04-09
    修改者: TraeAI
    任务: 重构为 async def（适配 AsyncOpenAI）
    """
    if not config.model:
        raise ValueError("model is required")

    if client._client is None:
        raise ValueError("client is required")

    request_params = client._build_request_params(
        messages=messages,
        enable_thinking=config.thinking_enabled,
    )
    response_model: type[DisambiguateResponseModel] | type[CloudDisambiguateResponseModel]
    response_model = CloudDisambiguateResponseModel if client.is_cloud_api() else DisambiguateResponseModel
    request_params["response_format"] = client._build_json_schema(response_model)

    response = await client._call_api_stream(
        request_params,
        is_cloud=client.is_cloud_api(),
        emitter=emitter,
    )

    thinking_content = None
    extract_reasoning_tokens = getattr(client, "_extract_reasoning_tokens", None)
    reasoning_tokens = extract_reasoning_tokens(response) if callable(extract_reasoning_tokens) else None
    if hasattr(response, "choices") and response.choices:
        message = response.choices[0].message
        thinking_content = getattr(message, "reasoning_content", None)
        if thinking_content:
            logger.debug(f"Extracted thinking_content: {len(thinking_content)} chars")

    parsed_response = client._parse_structured_response(response, response_model)
    normalized_response = normalize_disambiguate_response(parsed_response)

    if thinking_content:
        normalized_response = normalized_response.model_copy(update={"thinking_content": thinking_content})
    if reasoning_tokens is not None:
        normalized_response = normalized_response.model_copy(update={"reasoning_tokens": reasoning_tokens})

    response_content = response.choices[0].message.content if hasattr(response, "choices") and response.choices else ""
    client._record_estimated_token_usage_from_messages(messages, response_content, log_type)

    return normalized_response
