"""
创建时间: 2026-03-18
创建者: TraeAI
任务: code-quality-refactor - Task 9 拆分annotation_client
说明: Phase2 伏笔分析逻辑
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from loguru import logger

from src.models.local.schema import ForeshadowingResult

from .context import PHASE_MAX_RETRIES, Phase2MaxRetriesExceededError
from .messages import _build_foreshadowing_messages

if TYPE_CHECKING:
    from src.models.local.annotation_client import AnnotationClient


def _do_phase2(
    client: "AnnotationClient",
    messages: list[dict],
    text: str,
    prev_chunk_summary: str | None,
    chunk_id: int | None,
) -> "ForeshadowingResult":
    """
    执行Phase2单次调用

    创建时间: 2026-03-18
    创建者: TraeAI
    任务: code-quality-refactor - 提取Phase2单次调用逻辑
    """
    is_cloud = client._is_cloud_api()
    client._log_annotation_start(is_cloud, text, prev_chunk_summary, chunk_id, "phase2")

    enable_thinking = client._config.thinking_enabled

    result, response = client._call_annotation_api(
        messages=messages,
        enable_thinking=enable_thinking,
        chunk_id=chunk_id,
        response_model=ForeshadowingResult,
    )

    content_clean, thinking_content, extraction = client._process_annotation_response(response, is_cloud, chunk_id, "phase2")

    client._log_prompt_response(
        chunk_id, content_clean, thinking_content, extraction, messages, text, prev_chunk_summary
    )

    client._record_token_usage(response, "phase2", chunk_id)

    return result


def annotate_chunk_phase2(
    client: "AnnotationClient",
    text: str,
    prev_chunk_summary: str | None = None,
    chunk_id: int | None = None,
    prev_chunk_text: str | None = None,
    next_chunk_text: str | None = None,
    novel_title: str | None = None,
    main_characters: str | None = None,
    position_pct: float | None = None,
    chapter_id: int | None = None,
    cloud_client: "AnnotationClient | None" = None,
) -> "ForeshadowingResult | None":
    """
    第二次调用：伏笔分析（带独立重试机制）

    创建时间: 2026-03-14
    创建者: TraeAI
    任务: Chunk 双次调用分析拆分

    修改时间: 2026-03-14
    修改者: TraeAI
    任务: Phase1/Phase2独立重试机制
    修改内容: 添加独立重试逻辑，本地3次失败后云端fallback

    修改时间: 2026-03-16
    修改者: TraeAI
    任务: 重构本地标注客户端集成 Instructor
    修改内容: 使用 Instructor 结构化输出，直接返回 ForeshadowingResult
    """
    messages = _build_foreshadowing_messages(
        text=text,
        prev_chunk_summary=prev_chunk_summary,
        chunk_id=chunk_id,
        prev_chunk_text=prev_chunk_text,
        next_chunk_text=next_chunk_text,
        novel_title=novel_title,
        main_characters=main_characters,
        position_pct=position_pct,
        chapter_id=chapter_id,
    )

    last_error: Exception | None = None
    for attempt in range(PHASE_MAX_RETRIES):
        try:
            logger.debug("phase2 attempt {}/{} chunk_id={}", attempt + 1, PHASE_MAX_RETRIES, chunk_id)
            result = _do_phase2(client, messages, text, prev_chunk_summary, chunk_id)
            if attempt > 0:
                logger.info("phase2 succeeded on attempt {} chunk_id={}", attempt + 1, chunk_id)
            return result
        except Exception as e:
            last_error = e
            logger.error("phase2 attempt {}/{} failed: {} chunk_id={}", attempt + 1, PHASE_MAX_RETRIES, str(e), chunk_id)

    if cloud_client is not None:
        logger.warning("phase2 local model failed after {} attempts, falling back to cloud model chunk_id={}", PHASE_MAX_RETRIES, chunk_id)
        try:
            logger.debug("phase2 cloud attempt chunk_id={}", chunk_id)
            result = _do_phase2(cloud_client, messages, text, prev_chunk_summary, chunk_id)
            logger.info("phase2 cloud succeeded chunk_id={}", chunk_id)
            return result
        except Exception as e:
            last_error = e
            logger.error("phase2 cloud failed: {} chunk_id={}", str(e), chunk_id)

    logger.error("phase2 failed after all retries chunk_id={}: {}", chunk_id, str(last_error))
    raise Phase2MaxRetriesExceededError(f"phase2 failed after {PHASE_MAX_RETRIES} local + 1 cloud retries: {str(last_error)}")
