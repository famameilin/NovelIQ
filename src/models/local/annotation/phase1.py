"""
说明: Phase1 基础标注逻辑
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING

from src.config import settings
from src.models.interactions import record_model_interaction
from src.models.local.parser import parse_active_entities
from src.models.local.prompts import build_retry_prompt
from src.models.local.retry_handler import AnnotationRetryHandler, RetryConfig

from .context import Phase1MaxRetriesExceededError
from .messages import _build_annotation_messages_v2

if TYPE_CHECKING:
    from src.models.annotation import AnnotationClient
    from src.models.local.schema import ChunkAnnotation


async def execute_phase1_call(
    client: AnnotationClient,
    text: str,
    messages: list[dict],
    alias_map: dict[str, str] | None,
    active_entities: str | None,
    evidence_bundle,
    chunk_id: int | None,
    retry_messages: list[dict] | None = None,
    run_id: str | None = None,
    attempt_number: int = 1,
) -> tuple[ChunkAnnotation, str]:
    """
    执行Phase1单次调用

    说明: 从_annotate_chunk_phase1中提取的内嵌函数
    """
    start_time = time.time()
    is_cloud = client._is_cloud_api()
    client._log_annotation_start(is_cloud, text, None, chunk_id, "phase1")

    current_messages = retry_messages if retry_messages else messages

    enable_thinking = client._config.thinking_enabled
    response = await client._call_annotation_api(current_messages, enable_thinking, chunk_id)

    try:
        content_clean, thinking_content, extraction = client._process_annotation_response(
            response, is_cloud, chunk_id, "phase1"
        )
    except Exception:
        # 这里的异常说明模型响应已经返回，但响应清洗/重复输出检测失败；
        # 这种场景同样已经真实消耗了 token，需要按响应对象补记成本。
        client._record_estimated_token_usage_from_response(
            current_messages,
            response,
            "phase1",
            chunk_id,
            task_type="annotation",
        )
        raise

    duration_ms = int((time.time() - start_time) * 1000)
    extract_reasoning_tokens = getattr(client, "_extract_reasoning_tokens", None)
    reasoning_tokens = extract_reasoning_tokens(response) if callable(extract_reasoning_tokens) else None

    record_model_interaction(
        run_id=run_id,
        chunk_id=chunk_id,
        interaction_type="annotate",
        phase="phase1",
        attempt_number=attempt_number,
        messages=current_messages,
        response_text=content_clean,
        thinking_content=thinking_content,
        reasoning_tokens=reasoning_tokens,
        requested_thinking=enable_thinking,
        duration_ms=duration_ms,
        model_name=client._config.model if hasattr(client._config, "model") else None,
        model_provider="cloud" if is_cloud else "local",
        session=client._session if hasattr(client, "_session") else None,
    )

    client._log_prompt_response(chunk_id, content_clean, thinking_content, extraction, current_messages, text, None)

    try:
        result = client._parse_annotation(content_clean)

        sources = {
            "text": text,
            "active_entities": parse_active_entities(active_entities),
            "alias_map": alias_map or {},
            "evidence_bundle": evidence_bundle,
        }

        result = client._validate_annotation(result, sources, chunk_id, content_clean)
    except Exception:
        # phase1 的失败经常发生在 JSON 解析或业务校验阶段，
        # 但此时模型响应已经拿到了，仍需要把本次尝试的 token 成本记下来。
        client._record_estimated_token_usage_from_messages(
            current_messages,
            content_clean,
            "phase1",
            chunk_id,
            task_type="annotation",
        )
        raise

    # fallback client 只是执行通道切换，不应把业务口径拆成 annotation_fallback.phase1。
    client._record_estimated_token_usage_from_messages(
        current_messages,
        content_clean,
        "phase1",
        chunk_id,
        task_type="annotation",
    )

    return result, content_clean


async def execute_phase1_with_retry(
    client: AnnotationClient,
    text: str,
    messages: list[dict],
    alias_map: dict[str, str] | None,
    active_entities: str | None,
    evidence_bundle,
    chunk_id: int | None,
    fallback_client: AnnotationClient | None,
    run_id: str | None = None,
) -> ChunkAnnotation:
    """
    执行Phase1带重试的调用
    """
    from src.models.local.schema import ChunkAnnotation

    phase_max_retries = settings.runtime.annotation.phase_max_retries
    config = RetryConfig(
        max_retries=phase_max_retries,
        operation_name="phase1",
        chunk_id=chunk_id,
    )
    handler = AnnotationRetryHandler[ChunkAnnotation](
        config=config,
        primary_client=client,
        fallback_client=fallback_client,
        exception_type=Phase1MaxRetriesExceededError,
    )

    async def operation(primary_client: AnnotationClient, retry_messages: list[dict] | None = None) -> ChunkAnnotation:
        """执行单次Phase1调用"""
        result, _ = await execute_phase1_call(
            primary_client,
            text,
            messages,
            alias_map,
            active_entities,
            evidence_bundle,
            chunk_id,
            retry_messages,
            run_id=run_id,
            attempt_number=handler.state.attempt,
        )
        return result

    def build_retry_messages() -> list[dict]:
        """构建重试消息"""
        if handler.state.last_bad_output:
            original_user_prompt = messages[-1]["content"]
            is_repetitive = (
                handler.state.last_error is not None
                and handler.state.last_error.__class__.__name__ == "RepetitiveOutputError"
            )
            retry_prompt = build_retry_prompt(
                original_user_prompt,
                handler.state.last_bad_output,
                handler.state.last_invalid_names,
                handler.state.last_validation_details,
                is_repetitive=is_repetitive,
            )
            return messages[:-1] + [{"role": "user", "content": retry_prompt}]
        return messages

    return await handler.execute(operation, build_retry_messages)


async def annotate_chunk_phase1(
    client: AnnotationClient,
    text: str,
    alias_map: dict[str, str] | None = None,
    chunk_id: int | None = None,
    novel_title: str | None = None,
    main_characters: str | None = None,
    position_pct: float | None = None,
    chapter_id: int | None = None,
    active_entities: str | None = None,
    evidence_bundle=None,
    fallback_client: AnnotationClient | None = None,
    run_id: str | None = None,
    disambig_context: str | None = None,
) -> ChunkAnnotation:
    """
    第一次调用：基础标注（带独立重试机制）
    """
    messages = _build_annotation_messages_v2(
        text=text,
        alias_map=alias_map,
        chunk_id=chunk_id,
        novel_title=novel_title,
        main_characters=main_characters,
        position_pct=position_pct,
        chapter_id=chapter_id,
        active_entities=active_entities,
        disambig_context=disambig_context,
        evidence_bundle=evidence_bundle,
    )

    return await execute_phase1_with_retry(
        client=client,
        text=text,
        messages=messages,
        alias_map=alias_map,
        active_entities=active_entities,
        evidence_bundle=evidence_bundle,
        chunk_id=chunk_id,
        fallback_client=fallback_client,
        run_id=run_id,
    )
