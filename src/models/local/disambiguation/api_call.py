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

    修改时间: 2026-04-22
    修改者: Codex
    任务: count-failed-llm-calls
    修改内容: 结构化解析失败时仍补记 token，避免请求已完成却被遗漏

    修改时间: 2026-04-24
    任务: structured-output-adapter-instructor-unification
    修改内容: 消歧结构化调用改走项目级 structured_output 适配层，保留 stream/emitter 与 cloud-safe schema。

    修改时间: 2026-04-24
    任务: fix-structured-output-review-findings
    修改内容: 仅当结构化适配层带回 raw_response 时补记 token，避免本地前置错误污染 token_usage。

    修改时间: 2026-04-24
    任务: unify-disambig-transport-record-arrays
    修改内容: 消歧传输层统一使用记录数组响应模型，解析后再归一化回内部 dict 模型。
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
