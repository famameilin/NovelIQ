"""
RAG 可选模型调用审计辅助。

创建时间: 2026-04-24
任务: llm-mention-rerank-audit
说明: 为 mention extraction / level3 rerank 复用同一套
      model_interactions + token_usage 审计逻辑，避免各边界模块各自拼接。
"""

from __future__ import annotations

import time
from collections.abc import Callable
from typing import Any

from pydantic import BaseModel

from src.models.interactions import record_model_interaction


def _stringify_structured_response(response_data: BaseModel) -> str:
    """
    创建时间: 2026-04-24
    任务: llm-mention-rerank-audit
    说明: 在 mock/结构化响应对象没有原始 choices 时，退化为稳定的结构化文本，
          保证 model_interactions 至少能留下可回放的响应载荷。
    """
    try:
        return response_data.model_dump_json(ensure_ascii=False)
    except TypeError:
        return str(response_data.model_dump())


async def audited_structured_model_call[TResponseModel: BaseModel, TNormalized](
    client: Any,
    *,
    messages: list[dict[str, str]],
    response_model: type[TResponseModel],
    normalize_response: Callable[[TResponseModel], TNormalized],
    interaction_type: str,
    phase: str,
    call_type: str,
    enable_thinking: bool,
    timeout: float | None,
    run_id: str | None,
    chunk_id: int | None,
) -> TNormalized:
    """
    创建时间: 2026-04-24
    任务: llm-mention-rerank-audit
    说明: 执行一次结构化模型调用，并统一补齐成功/失败审计和 token 记账。
    """
    start_time = time.time()
    response: Any = None
    parsed_response: TResponseModel | None = None
    response_text = ""
    thinking_content: str | None = None
    reasoning_tokens: int | None = None
    is_cloud = client.is_cloud_api() if hasattr(client, "is_cloud_api") else False

    try:
        response = await client._call_api(
            messages,
            enable_thinking=enable_thinking,
            response_model=response_model,
            timeout=timeout,
        )
        if isinstance(response, response_model):
            parsed_response = response
            response_text = _stringify_structured_response(parsed_response)
        else:
            response_text = client._extract_response_text_for_token_usage(response)
            parsed_response = client._parse_structured_response(response, response_model)
            response_text = response_text or _stringify_structured_response(parsed_response)

            if hasattr(response, "choices") and response.choices:
                response_message = response.choices[0].message
                _content_clean, thinking_content = client._extract_response_content(response_message)

        reasoning_tokens = client._extract_reasoning_tokens(response)
        normalized = normalize_response(parsed_response)
    except Exception as exc:
        duration_ms = int((time.time() - start_time) * 1000)
        if response is not None and not response_text:
            response_text = client._extract_response_text_for_token_usage(response)
        if response is not None:
            client._record_estimated_token_usage_from_response(messages, response, call_type, chunk_id)
        else:
            client._record_estimated_token_usage_from_messages(messages, "", call_type, chunk_id)
        record_model_interaction(
            run_id=run_id,
            chunk_id=chunk_id,
            interaction_type=interaction_type,
            phase=phase,
            attempt_number=1,
            messages=messages,
            response_text=response_text,
            thinking_content=thinking_content,
            reasoning_tokens=reasoning_tokens,
            requested_thinking=enable_thinking,
            duration_ms=duration_ms,
            model_name=client._config.model if hasattr(client, "_config") else None,
            model_provider="cloud" if is_cloud else "local",
            status="error",
            error_message=str(exc),
            session=getattr(client, "_session", None),
        )
        raise

    duration_ms = int((time.time() - start_time) * 1000)
    record_model_interaction(
        run_id=run_id,
        chunk_id=chunk_id,
        interaction_type=interaction_type,
        phase=phase,
        attempt_number=1,
        messages=messages,
        response_text=response_text,
        thinking_content=thinking_content,
        reasoning_tokens=reasoning_tokens,
        requested_thinking=enable_thinking,
        duration_ms=duration_ms,
        model_name=client._config.model if hasattr(client, "_config") else None,
        model_provider="cloud" if is_cloud else "local",
        session=getattr(client, "_session", None),
    )
    client._record_estimated_token_usage_from_messages(messages, response_text, call_type, chunk_id)
    return normalized
