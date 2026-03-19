"""
消歧API调用模块

创建时间: 2026-03-18
创建者: TraeAI
任务: code-quality-refactor - Task 9 拆分disambiguation_client.py
说明: 提取消歧API调用相关逻辑
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Dict, List, cast

from loguru import logger

from src.utils.token_counter import count_messages_tokens, count_tokens

from ..litellm_utils import get_model_with_provider
from ..schema import DisambiguateResponseModel

if TYPE_CHECKING:
    from src.config import TaskModelConfig
    from ..base import BaseModelClient


def call_disambiguate_api(
    client: BaseModelClient,
    config: TaskModelConfig,
    messages: List[Dict[str, str]],
    log_type: str,
    is_cloud: bool,
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
    """
    if not config.model:
        raise ValueError("model is required")

    if client._client is None:
        raise ValueError("client is required")

    model_name = get_model_with_provider(config.model, config)

    request_params: dict[str, Any] = {
        "model": model_name,
        "messages": cast(Any, messages),
        "temperature": config.temperature,
        "top_p": config.top_p,
        "presence_penalty": config.presence_penalty,
        "response_format": client._build_json_schema(DisambiguateResponseModel),
    }

    # 使用tiktoken估算prompt token数量
    model_for_token_count = config.model or "gpt-4"
    prompt_tokens = count_messages_tokens(messages, model_for_token_count)

    # 使用流式模式并实时输出到控制台（仅云端API）
    response = client._call_api_stream(request_params, is_cloud=is_cloud)

    # 提取 thinking_content（如果存在）
    thinking_content = None
    if hasattr(response, "choices") and response.choices:
        message = response.choices[0].message
        thinking_content = getattr(message, "reasoning_content", None)
        if thinking_content:
            logger.debug(f"Extracted thinking_content: {len(thinking_content)} chars")

    parsed_response = client._parse_structured_response(response, DisambiguateResponseModel)

    # 将 thinking_content 附加到响应对象以便日志记录
    if thinking_content:
        parsed_response._thinking_content = thinking_content  # type: ignore[attr-defined]

    # 估算completion token并记录token使用
    response_content = (
        response.choices[0].message.content if hasattr(response, "choices") and response.choices else ""
    )
    completion_tokens = count_tokens(response_content, model_for_token_count)
    total_tokens = prompt_tokens + completion_tokens

    client._record_token_usage_estimated(
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        total_tokens=total_tokens,
        call_type=log_type,
    )

    return parsed_response
