"""
RAG 可选模型调用审计辅助。

为 mention extraction / level3 rerank 复用同一套
      model_interactions + token_usage 审计逻辑，避免各边界模块各自拼接。
"""

from __future__ import annotations

import time
from collections.abc import Callable
from typing import Any

from loguru import logger
from pydantic import BaseModel

from src.models.interactions import record_model_interaction
from src.models.structured_output import StructuredOutputError, StructuredOutputRequest, call_structured_output


def _stringify_structured_response(response_data: BaseModel) -> str:
    """
    在 mock/结构化响应对象没有原始 choices 时，退化为稳定的结构化文本，
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
    执行一次结构化模型调用，并统一补齐成功/失败审计和 token 记账。

    支持调用方传入 provider 原生 response_format，解决云端只支持 json_object
              但项目仍需要 Pydantic 校验内部结构的场景。

    改为调用项目级 structured_output 适配层，raw_response_format/mode 选择不再由 RAG 业务模块传入。

    仅在 provider 已返回 raw_response 时补记 token，避免本地 prompt 合同校验失败被误记为模型消耗。

    补充结构化模型调用开始、成功和失败日志，暴露 mention/rerank 阶段的长等待来源。
    """
    start_time = time.time()
    response: Any = None
    parsed_response: TResponseModel | None = None
    response_text = ""
    thinking_content: str | None = None
    reasoning_tokens: int | None = None
    structured_result: Any = None
    is_cloud = client.is_cloud_api() if hasattr(client, "is_cloud_api") else False
    model_name = getattr(getattr(client, "_config", None), "model", None)

    logger.info(
        "structured model call start: run_id={} chunk_id={} interaction_type={} call_type={} model={} "
        "provider={} timeout_s={} thinking={}",
        run_id,
        chunk_id,
        interaction_type,
        call_type,
        model_name,
        "cloud" if is_cloud else "local",
        timeout,
        enable_thinking,
    )

    try:
        structured_result = await call_structured_output(
            client,
            StructuredOutputRequest(
                messages=messages,
                response_model=response_model,
                call_type=call_type,
                enable_thinking=enable_thinking,
                timeout=timeout,
            ),
        )
        response = structured_result.raw_response
        parsed_response = structured_result.parsed
        response_text = structured_result.response_text or _stringify_structured_response(parsed_response)
        thinking_content = structured_result.thinking_content
        reasoning_tokens = structured_result.reasoning_tokens
        normalized = normalize_response(parsed_response)
    except Exception as exc:
        duration_ms = int((time.time() - start_time) * 1000)
        if isinstance(exc, StructuredOutputError):
            response = exc.raw_response
            response_text = exc.response_text
            thinking_content = exc.thinking_content
            reasoning_tokens = exc.reasoning_tokens
        elif structured_result is not None:
            response = structured_result.raw_response
            response_text = structured_result.response_text
            thinking_content = structured_result.thinking_content
            reasoning_tokens = structured_result.reasoning_tokens
        if response is not None and not response_text:
            response_text = client._extract_response_text_for_token_usage(response)
        if response is not None:
            client._record_estimated_token_usage_from_response(messages, response, call_type, chunk_id)
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
        logger.warning(
            "structured model call failed: run_id={} chunk_id={} interaction_type={} call_type={} model={} "
            "duration_ms={} error={}",
            run_id,
            chunk_id,
            interaction_type,
            call_type,
            model_name,
            duration_ms,
            str(exc),
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
    logger.info(
        "structured model call complete: run_id={} chunk_id={} interaction_type={} call_type={} model={} "
        "duration_ms={} response_chars={} thinking_chars={}",
        run_id,
        chunk_id,
        interaction_type,
        call_type,
        model_name,
        duration_ms,
        len(response_text or ""),
        len(thinking_content or ""),
    )
    return normalized
