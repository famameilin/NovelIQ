"""
创建时间: 2026-03-18
创建者: TraeAI
任务: code-quality-refactor - Task 9 拆分annotation_client
说明: Phase2 伏笔分析逻辑

修改时间: 2026-03-18
修改者: TraeAI
任务: code-quality-refactor - Task 3 统一重试机制
修改内容: 使用 AnnotationRetryHandler 统一重试逻辑

修改时间: 2026-03-19
修改者: TraeAI
任务: 添加模型交互记录保存
修改内容: 添加 save_model_interaction 工具函数
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING, Any

from loguru import logger

from src.models.local.retry_handler import AnnotationRetryHandler, RetryConfig
from src.models.local.schema import ForeshadowingResult

from .context import PHASE_MAX_RETRIES, Phase2MaxRetriesExceededError
from .messages import _build_foreshadowing_messages

if TYPE_CHECKING:
    from src.models.annotation import AnnotationClient


def _save_interaction(
    client: AnnotationClient,
    run_id: str | None,
    chunk_id: int | None,
    phase: str,
    attempt_number: int,
    messages: list[dict],
    content_clean: str,
    thinking_content: str | None,
    duration_ms: int,
    is_cloud: bool,
) -> None:
    """
    保存模型交互记录

    创建时间: 2026-03-19
    创建者: TraeAI
    任务: 添加模型交互记录保存

    修改时间: 2026-03-19
    修改者: TraeAI
    任务: 使用 client 的 _session 属性保存交互记录
    修改内容: 优先使用 client._session，如果没有则创建新 session
    """
    if not run_id:
        return

    try:
        from src.storage.repositories.model_interaction_repository import ModelInteractionRepository

        prompt_text = "\n\n".join([f"{msg['role']}: {msg['content']}" for msg in messages])

        # 优先使用 client 的 _session
        if hasattr(client, '_session') and client._session is not None:
            repo = ModelInteractionRepository(client._session)
            repo.save_interaction(
                run_id=run_id,
                chunk_id=chunk_id,
                interaction_type="annotate",
                phase=phase,
                attempt_number=attempt_number,
                model_name=client._config.model if hasattr(client._config, 'model') else None,
                model_provider="cloud" if is_cloud else "local",
                prompt=prompt_text,
                response=content_clean,
                thinking=thinking_content,
                response_chars=len(content_clean),
                thinking_chars=len(thinking_content) if thinking_content else 0,
                has_thinking=bool(thinking_content and thinking_content.strip()),
                status="success",
                duration_ms=duration_ms,
            )
        else:
            # 没有 _session，创建新 session
            from src.storage.db import get_session_factory
            Session = get_session_factory()
            session = Session()
            try:
                repo = ModelInteractionRepository(session)
                repo.save_interaction(
                    run_id=run_id,
                    chunk_id=chunk_id,
                    interaction_type="annotate",
                    phase=phase,
                    attempt_number=attempt_number,
                    model_name=client._config.model if hasattr(client._config, 'model') else None,
                    model_provider="cloud" if is_cloud else "local",
                    prompt=prompt_text,
                    response=content_clean,
                    thinking=thinking_content,
                    response_chars=len(content_clean),
                    thinking_chars=len(thinking_content) if thinking_content else 0,
                    has_thinking=bool(thinking_content and thinking_content.strip()),
                    status="success",
                    duration_ms=duration_ms,
                )
            finally:
                session.close()
    except Exception as e:
        logger.warning(f"Failed to save model interaction: {e}")


def _do_phase2(
    client: AnnotationClient,
    messages: list[dict],
    text: str,
    prev_chunk_summary: str | None,
    chunk_id: int | None,
    run_id: str | None = None,
    attempt_number: int = 1,
) -> ForeshadowingResult:
    """
    执行Phase2单次调用

    创建时间: 2026-03-18
    创建者: TraeAI
    任务: code-quality-refactor - 提取Phase2单次调用逻辑

    修改时间: 2026-03-19
    修改者: TraeAI
    任务: 添加模型交互记录保存
    修改内容: 添加 run_id 和 attempt_number 参数，保存交互记录
    """
    start_time = time.time()
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

    duration_ms = int((time.time() - start_time) * 1000)

    # 保存交互记录
    _save_interaction(
        client=client,
        run_id=run_id,
        chunk_id=chunk_id,
        phase="phase2",
        attempt_number=attempt_number,
        messages=messages,
        content_clean=content_clean,
        thinking_content=thinking_content,
        duration_ms=duration_ms,
        is_cloud=is_cloud,
    )

    client._log_prompt_response(
        chunk_id, content_clean, thinking_content, extraction, messages, text, prev_chunk_summary
    )

    client._record_token_usage(response, "phase2", chunk_id)

    return result


def annotate_chunk_phase2(
    client: AnnotationClient,
    text: str,
    prev_chunk_summary: str | None = None,
    chunk_id: int | None = None,
    prev_chunk_text: str | None = None,
    next_chunk_text: str | None = None,
    novel_title: str | None = None,
    main_characters: str | None = None,
    position_pct: float | None = None,
    chapter_id: int | None = None,
    cloud_client: AnnotationClient | None = None,
    run_id: str | None = None,
    rag_retriever: Any | None = None,
) -> ForeshadowingResult | None:
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

    修改时间: 2026-03-19
    修改者: TraeAI
    任务: 添加模型交互记录保存
    修改内容: 添加 run_id 参数，传递 attempt_number
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

    def operation(local_client: AnnotationClient, retry_messages: list[dict] | None = None) -> ForeshadowingResult:
        """执行单次Phase2调用"""
        msgs = retry_messages if retry_messages else messages
        return _do_phase2(local_client, msgs, text, prev_chunk_summary, chunk_id, run_id, handler.state.attempt)

    return handler.execute(operation)
