"""
BaseModelClient 传输层辅助模块。

创建时间: 2026-04-23
任务: p2-base-model-client-split
说明: 从 base.py 中拆出非流式/流式 transport 细节，让客户端主类聚焦上下文与兼容入口。
"""

from __future__ import annotations

from typing import Any

from loguru import logger
from pydantic import BaseModel

from src.models.local.base_stream_emitter import (
    StreamAggregationState,
    build_stream_response,
    emit_stream_delta,
    finalize_stream_content,
    flush_stream_buffers,
)


async def call_api[T: BaseModel](
    client: Any,
    messages: list[dict],
    enable_thinking: bool = False,
    response_model: type[T] | None = None,
    raw_response_format: dict[str, Any] | None = None,
    timeout: float | None = None,
) -> Any:
    """
    执行非流式模型调用。

    创建时间: 2026-04-23
    任务: p2-base-model-client-split
    新建原因: 将 request_params 组装与 SDK 调用从 BaseModelClient 主类中拆离。

    修改时间: 2026-04-24
    修改者: Codex
    任务: fix-llm-call-timeout
    修改内容: 添加显式 timeout 参数，避免调用层因默认超时未设置而长时间阻塞。

    修改时间: 2026-04-24
    任务: deepseek-json-object-compat
    修改内容: 支持调用方显式传入 response_format，兼容只支持 json_object、
              不支持 strict json_schema 的服务商。
    """
    request_params = client._build_request_params(messages, enable_thinking=enable_thinking)
    if raw_response_format is not None:
        request_params["response_format"] = raw_response_format
    elif response_model is not None:
        request_params["response_format"] = client._build_json_schema(response_model)
    if timeout is not None:
        request_params["timeout"] = timeout
    return await client._client.chat.completions.create(**request_params)


async def call_api_stream(
    client: Any,
    request_params: dict[str, Any],
    *,
    is_cloud: bool = False,
    emitter: Any = None,
) -> Any:
    """
    执行流式模型调用并聚合为标准响应对象。

    创建时间: 2026-04-23
    任务: p2-base-model-client-split
    新建原因: 将 stream transport 主循环从 BaseModelClient 主类中抽离。
    """
    request_params["stream"] = True
    logger.debug("Using streaming mode for API call")

    state = StreamAggregationState()

    if is_cloud:
        print(f"[Stream] Starting API call with model={request_params.get('model', 'unknown')}", flush=True)

    stream = await client._client.chat.completions.create(**request_params)
    async for chunk in stream:
        state.chunk_count += 1
        chunk_usage = getattr(chunk, "usage", None)
        if chunk_usage is not None:
            state.usage = chunk_usage
        if not chunk.choices:
            continue
        await emit_stream_delta(
            state,
            chunk.choices[0].delta,
            is_cloud=is_cloud,
            emitter=emitter,
        )

    if is_cloud:
        print(f"\n[Stream] Completed: received {state.chunk_count} chunks", flush=True)

    await flush_stream_buffers(state, emitter)
    full_content, full_reasoning = finalize_stream_content(state)
    return build_stream_response(client._config.model, full_content, full_reasoning, usage=state.usage)
