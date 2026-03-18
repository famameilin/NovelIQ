"""
创建时间: 2026-03-18
创建者: TraeAI
任务: code-quality-refactor - Task 9 拆分annotation_client
说明: Phase1 基础标注逻辑
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Dict

from loguru import logger

from src.models.local.parser import parse_active_entities
from src.models.local.prompts import build_retry_prompt

from .context import (
    PHASE_MAX_RETRIES,
    NameValidationMaxRetriesExceededError,
    Phase1MaxRetriesExceededError,
)
from .messages import _build_annotation_messages_v2

if TYPE_CHECKING:
    from src.models.local.annotation_client import AnnotationClient
    from src.models.local.schema import ChunkAnnotation


def execute_phase1_call(
    client: "AnnotationClient",
    text: str,
    messages: list[dict],
    alias_map: Dict[str, str] | None,
    active_entities: str | None,
    prev_chunk_text: str | None,
    next_chunk_text: str | None,
    chunk_id: int | None,
    retry_messages: list[dict] | None = None,
) -> tuple["ChunkAnnotation", str]:
    """
    执行Phase1单次调用

    创建时间: 2026-03-17
    创建者: TraeAI
    任务: code-quality-refactor - 提取_do_phase1方法
    说明: 从_annotate_chunk_phase1中提取的内嵌函数
    """
    is_cloud = client._is_cloud_api()
    client._log_annotation_start(is_cloud, text, None, chunk_id, "phase1")

    current_messages = retry_messages if retry_messages else messages

    enable_thinking = client._config.thinking_enabled
    response = client._call_annotation_api(current_messages, enable_thinking, chunk_id)

    content_clean, thinking_content, extraction = client._process_annotation_response(
        response, is_cloud, chunk_id, "phase1"
    )

    client._log_prompt_response(
        chunk_id, content_clean, thinking_content, extraction, current_messages, text, None
    )

    result = client._parse_annotation(content_clean)

    sources = {
        "text": text,
        "prev_tail_text": prev_chunk_text or "",
        "active_entities": parse_active_entities(active_entities),
        "alias_map": alias_map or {},
        "next_preview": next_chunk_text or "",
    }

    result = client._validate_annotation(result, sources, chunk_id, content_clean)

    client._record_token_usage(response, "phase1", chunk_id)

    return result, content_clean


def execute_phase1_with_retry(
    client: "AnnotationClient",
    text: str,
    messages: list[dict],
    alias_map: Dict[str, str] | None,
    active_entities: str | None,
    prev_chunk_text: str | None,
    next_chunk_text: str | None,
    chunk_id: int | None,
    cloud_client: "AnnotationClient | None",
) -> "ChunkAnnotation":
    """
    执行Phase1带重试的调用

    创建时间: 2026-03-17
    创建者: TraeAI
    任务: code-quality-refactor - 提取重试逻辑
    """
    last_error: Exception | None = None
    last_invalid_names: list[str] | None = None
    last_bad_output: str = ""
    content_clean: str = ""

    for attempt in range(PHASE_MAX_RETRIES):
        try:
            logger.debug("phase1 attempt {}/{} chunk_id={}", attempt + 1, PHASE_MAX_RETRIES, chunk_id)

            retry_messages = None
            if last_bad_output and last_invalid_names:
                original_user_prompt = messages[-1]["content"]
                retry_prompt = build_retry_prompt(original_user_prompt, last_bad_output, last_invalid_names)
                retry_messages = messages[:-1] + [{"role": "user", "content": retry_prompt}]

            result, content_clean = execute_phase1_call(
                client, text, messages, alias_map, active_entities,
                prev_chunk_text, next_chunk_text, chunk_id, retry_messages
            )

            if attempt > 0:
                logger.info("phase1 succeeded on attempt {} chunk_id={}", attempt + 1, chunk_id)
            return result

        except NameValidationMaxRetriesExceededError as e:
            last_error = e
            last_invalid_names = e.invalid_names
            last_bad_output = e.bad_output or content_clean
            logger.error("phase1 attempt {}/{} failed: {} chunk_id={}", attempt + 1, PHASE_MAX_RETRIES, str(e), chunk_id)
        except Exception as e:
            last_error = e
            last_invalid_names = None
            last_bad_output = content_clean
            logger.error("phase1 attempt {}/{} failed: {} chunk_id={}", attempt + 1, PHASE_MAX_RETRIES, str(e), chunk_id)

    if cloud_client is not None:
        return execute_phase1_cloud_fallback(
            client, text, messages, alias_map, active_entities,
            prev_chunk_text, next_chunk_text, chunk_id, cloud_client,
            last_invalid_names, last_bad_output
        )

    logger.error("phase1 failed after all retries chunk_id={}: {}", chunk_id, str(last_error))
    raise Phase1MaxRetriesExceededError(f"phase1 failed after {PHASE_MAX_RETRIES} retries: {str(last_error)}")


def execute_phase1_cloud_fallback(
    client: "AnnotationClient",
    text: str,
    messages: list[dict],
    alias_map: Dict[str, str] | None,
    active_entities: str | None,
    prev_chunk_text: str | None,
    next_chunk_text: str | None,
    chunk_id: int | None,
    cloud_client: "AnnotationClient",
    last_invalid_names: list[str] | None,
    last_bad_output: str,
) -> "ChunkAnnotation":
    """
    执行Phase1云端fallback

    创建时间: 2026-03-17
    创建者: TraeAI
    任务: code-quality-refactor - 提取云端fallback逻辑
    """
    logger.warning("phase1 local model failed after {} attempts, falling back to cloud model chunk_id={}", PHASE_MAX_RETRIES, chunk_id)

    try:
        logger.debug("phase1 cloud attempt chunk_id={}", chunk_id)

        retry_messages = None
        if last_bad_output and last_invalid_names:
            original_user_prompt = messages[-1]["content"]
            retry_prompt = build_retry_prompt(original_user_prompt, last_bad_output, last_invalid_names)
            retry_messages = messages[:-1] + [{"role": "user", "content": retry_prompt}]

        result, _ = execute_phase1_call(
            cloud_client, text, messages, alias_map, active_entities,
            prev_chunk_text, next_chunk_text, chunk_id, retry_messages
        )

        logger.info("phase1 cloud succeeded chunk_id={}", chunk_id)
        return result

    except Exception as e:
        logger.error("phase1 cloud failed: {} chunk_id={}", str(e), chunk_id)
        raise Phase1MaxRetriesExceededError(f"phase1 failed after {PHASE_MAX_RETRIES} local + 1 cloud retries: {str(e)}")


def annotate_chunk_phase1(
    client: "AnnotationClient",
    text: str,
    alias_map: Dict[str, str] | None = None,
    chunk_id: int | None = None,
    prev_chunk_text: str | None = None,
    next_chunk_text: str | None = None,
    novel_title: str | None = None,
    main_characters: str | None = None,
    position_pct: float | None = None,
    chapter_id: int | None = None,
    active_entities: str | None = None,
    cloud_client: "AnnotationClient | None" = None,
) -> "ChunkAnnotation":
    """
    第一次调用：基础标注（带独立重试机制）

    创建时间: 2026-03-14
    创建者: TraeAI
    任务: Chunk 双次调用分析拆分

    修改时间: 2026-03-17
    修改者: TraeAI
    任务: code-quality-refactor - 重构_annotate_chunk_phase1
    修改内容:
    - 提取_execute_phase1_call方法
    - 简化重试逻辑
    """
    messages = _build_annotation_messages_v2(
        text=text,
        alias_map=alias_map,
        chunk_id=chunk_id,
        prev_chunk_text=prev_chunk_text,
        next_chunk_text=next_chunk_text,
        novel_title=novel_title,
        main_characters=main_characters,
        position_pct=position_pct,
        chapter_id=chapter_id,
        active_entities=active_entities,
    )

    return execute_phase1_with_retry(
        client=client,
        text=text,
        messages=messages,
        alias_map=alias_map,
        active_entities=active_entities,
        prev_chunk_text=prev_chunk_text,
        next_chunk_text=next_chunk_text,
        chunk_id=chunk_id,
        cloud_client=cloud_client,
    )
