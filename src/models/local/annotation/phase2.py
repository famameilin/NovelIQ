"""
创建时间: 2026-03-18
创建者: TraeAI
任务: code-quality-refactor - Task 9 拆分annotation_client
说明: Phase2 伏笔分析逻辑

修改时间: 2026-03-18
修改者: TraeAI
任务: code-quality-refactor - Task 3 统一重试机制
修改内容: 使用 AnnotationRetryHandler 统一重试逻辑
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from src.models.local.retry_handler import AnnotationRetryHandler, RetryConfig
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

    修改时间: 2026-03-18
    修改者: TraeAI
    任务: code-quality-refactor - Task 3 统一重试机制
    修改内容: 使用 AnnotationRetryHandler 替代自定义重试逻辑
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

    from src.models.local.schema import ForeshadowingResult

    config = RetryConfig(
        max_retries=PHASE_MAX_RETRIES,
        operation_name="phase2",
        chunk_id=chunk_id,
    )
    handler = AnnotationRetryHandler[ForeshadowingResult](
        config=config,
        local_client=client,
        cloud_client=cloud_client,
        exception_type=Phase2MaxRetriesExceededError,
    )

    def operation(local_client: "AnnotationClient", retry_messages: list[dict] | None = None) -> "ForeshadowingResult":
        """执行单次Phase2调用"""
        msgs = retry_messages if retry_messages else messages
        return _do_phase2(local_client, msgs, text, prev_chunk_summary, chunk_id)

    return handler.execute(operation)
