"""
说明: annotation Phase2/3/4 共用的薄执行器，统一模型调用、响应清洗、交互记录与 token 估算。
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel

from src.models.interactions import record_model_interaction


@dataclass(frozen=True)
class AnnotationPhaseCallSpec[T: BaseModel]:
    """
    定义单次 phase 模型调用所需的稳定元信息。
    """

    phase: str
    interaction_type: str
    call_type: str
    messages: list[dict]
    response_model: type[T]
    chunk_id: int | None = None
    run_id: str | None = None
    attempt_number: int = 1


@dataclass(frozen=True)
class AnnotationPhaseCallResult[T: BaseModel]:
    """
    承载单次 phase 调用后的结构化结果与记录元信息。
    """

    parsed: T
    response: Any
    content_clean: str
    thinking_content: str | None
    extraction: Any | None
    duration_ms: int
    reasoning_tokens: int | None


def _dump_parsed_result(parsed: BaseModel) -> str:
    """
    将结构化模型结果转换为可记录文本。
    """
    return str(parsed.model_dump())


async def execute_phase_call[T: BaseModel](
    client: Any,
    spec: AnnotationPhaseCallSpec[T],
) -> AnnotationPhaseCallResult[T]:
    """
    执行一次 Phase2/3/4 结构化 annotation 调用。
    """
    start_time = time.time()
    is_cloud = client._is_cloud_api()
    enable_thinking = client._config.thinking_enabled

    parsed, response = await client._call_annotation_api(
        messages=spec.messages,
        enable_thinking=enable_thinking,
        chunk_id=spec.chunk_id,
        response_model=spec.response_model,
        call_type=spec.call_type,
    )

    try:
        duration_ms = int((time.time() - start_time) * 1000)
        content_clean = _dump_parsed_result(parsed)
        thinking_content = getattr(response, "thinking_content", None)
        extraction = None

        process_response = getattr(client, "_process_annotation_response", None)
        response_choices = getattr(response, "choices", None)
        if callable(process_response) and isinstance(response_choices, (list, tuple)) and response_choices:
            content_clean, thinking_content, extraction = process_response(
                response,
                is_cloud,
                spec.chunk_id,
                spec.phase,
            )

        extract_reasoning_tokens = getattr(client, "_extract_reasoning_tokens", None)
        reasoning_tokens = extract_reasoning_tokens(response) if callable(extract_reasoning_tokens) else None

        record_model_interaction(
            run_id=spec.run_id,
            chunk_id=spec.chunk_id,
            interaction_type=spec.interaction_type,
            phase=spec.phase,
            attempt_number=spec.attempt_number,
            messages=spec.messages,
            response_text=content_clean,
            thinking_content=thinking_content,
            reasoning_tokens=reasoning_tokens,
            requested_thinking=enable_thinking,
            duration_ms=duration_ms,
            model_name=client._config.model if hasattr(client._config, "model") else None,
            model_provider="cloud" if is_cloud else "local",
            session=client._session if hasattr(client, "_session") else None,
        )
        # fallback client 只是执行通道切换，annotation phase 的 token 仍统一归入主业务桶。
        client._record_estimated_token_usage_from_messages(
            spec.messages,
            content_clean,
            spec.phase,
            spec.chunk_id,
            task_type="annotation",
        )
    except Exception:
        client._record_estimated_token_usage_from_response(
            spec.messages,
            response,
            spec.phase,
            spec.chunk_id,
            task_type="annotation",
        )
        raise

    return AnnotationPhaseCallResult(
        parsed=parsed,
        response=response,
        content_clean=content_clean,
        thinking_content=thinking_content,
        extraction=extraction,
        duration_ms=duration_ms,
        reasoning_tokens=reasoning_tokens,
    )
