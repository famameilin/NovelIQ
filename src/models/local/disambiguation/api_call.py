"""
消歧API调用模块

说明: 提取消歧API调用相关逻辑
"""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from loguru import logger

from src.api.models.events import StreamEvent
from src.models.structured_output import StructuredOutputError, StructuredOutputRequest, call_structured_output

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
    """
    if not config.model:
        raise ValueError("model is required")

    if client._client is None:
        raise ValueError("client is required")

    response_model: type[CloudDisambiguateResponseModel] = CloudDisambiguateResponseModel
    structured_result: Any = None
    try:
        structured_result = await call_structured_output(
            client,
            StructuredOutputRequest(
                messages=messages,
                response_model=response_model,
                call_type=log_type,
                enable_thinking=config.thinking_enabled,
                timeout=config.timeout_s,
                stream=True,
                stream_emitter=emitter,
            ),
        )
        parsed_response = structured_result.parsed
        normalized_response = normalize_disambiguate_response(parsed_response)
    except Exception as exc:
        raw_response = None
        if isinstance(exc, StructuredOutputError):
            raw_response = exc.raw_response
        elif structured_result is not None:
            raw_response = structured_result.raw_response
        if raw_response is not None:
            client._record_estimated_token_usage_from_response(messages, raw_response, log_type)
        raise

    thinking_content = structured_result.thinking_content
    reasoning_tokens = structured_result.reasoning_tokens
    response_content = structured_result.response_text
    if thinking_content:
        logger.debug(f"Extracted thinking_content: {len(thinking_content)} chars")

    if thinking_content:
        normalized_response = normalized_response.model_copy(update={"thinking_content": thinking_content})
    if reasoning_tokens is not None:
        normalized_response = normalized_response.model_copy(update={"reasoning_tokens": reasoning_tokens})

    client._record_estimated_token_usage_from_messages(messages, response_content, log_type)

    return normalized_response
