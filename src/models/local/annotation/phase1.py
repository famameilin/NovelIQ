"""
创建时间: 2026-03-18
创建者: TraeAI
任务: code-quality-refactor - Task 9 拆分annotation_client
说明: Phase1 基础标注逻辑

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
from typing import TYPE_CHECKING, Dict

from loguru import logger

from src.models.local.parser import parse_active_entities
from src.models.local.prompts import build_retry_prompt
from src.models.local.retry_handler import AnnotationRetryHandler, RetryConfig

from .context import (
    PHASE_MAX_RETRIES,
    Phase1MaxRetriesExceededError,
)
from .messages import _build_annotation_messages_v2

if TYPE_CHECKING:
    from src.models.local.annotation_client import AnnotationClient
    from src.models.local.schema import ChunkAnnotation


def _save_interaction(
    client: "AnnotationClient",
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
    run_id: str | None = None,
    attempt_number: int = 1,
) -> tuple["ChunkAnnotation", str]:
    """
    执行Phase1单次调用

    创建时间: 2026-03-17
    创建者: TraeAI
    任务: code-quality-refactor - 提取_do_phase1方法
    说明: 从_annotate_chunk_phase1中提取的内嵌函数

    修改时间: 2026-03-19
    修改者: TraeAI
    任务: 添加模型交互记录保存
    修改内容: 添加 run_id 和 attempt_number 参数，保存交互记录
    """
    start_time = time.time()
    is_cloud = client._is_cloud_api()
    client._log_annotation_start(is_cloud, text, None, chunk_id, "phase1")

    current_messages = retry_messages if retry_messages else messages

    enable_thinking = client._config.thinking_enabled
    response = client._call_annotation_api(current_messages, enable_thinking, chunk_id)

    content_clean, thinking_content, extraction = client._process_annotation_response(
        response, is_cloud, chunk_id, "phase1"
    )

    duration_ms = int((time.time() - start_time) * 1000)

    # 保存交互记录
    _save_interaction(
        client=client,
        run_id=run_id,
        chunk_id=chunk_id,
        phase="phase1",
        attempt_number=attempt_number,
        messages=current_messages,
        content_clean=content_clean,
        thinking_content=thinking_content,
        duration_ms=duration_ms,
        is_cloud=is_cloud,
    )

    client._log_prompt_response(
        chunk_id, content_clean, thinking_content, extraction, current_messages, text, None
    )

    result = client._parse_annotation(content_clean)

    sources = {
        "text": text,
        "prev_chunk_text": prev_chunk_text or "",
        "active_entities": parse_active_entities(active_entities),
        "alias_map": alias_map or {},
        "next_chunk_text": next_chunk_text or "",
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
    run_id: str | None = None,
) -> "ChunkAnnotation":
    """
    执行Phase1带重试的调用

    创建时间: 2026-03-17
    创建者: TraeAI
    任务: code-quality-refactor - 提取重试逻辑

    修改时间: 2026-03-18
    修改者: TraeAI
    任务: code-quality-refactor - Task 3 统一重试机制
    修改内容: 使用 AnnotationRetryHandler 替代自定义重试逻辑

    修改时间: 2026-03-19
    修改者: TraeAI
    任务: 添加模型交互记录保存
    修改内容: 添加 run_id 参数，传递 attempt_number
    """
    from src.models.local.schema import ChunkAnnotation

    config = RetryConfig(
        max_retries=PHASE_MAX_RETRIES,
        operation_name="phase1",
        chunk_id=chunk_id,
    )
    handler = AnnotationRetryHandler[ChunkAnnotation](
        config=config,
        local_client=client,
        cloud_client=cloud_client,
        exception_type=Phase1MaxRetriesExceededError,
    )

    def operation(local_client: "AnnotationClient", retry_messages: list[dict] | None = None) -> "ChunkAnnotation":
        """执行单次Phase1调用"""
        result, _ = execute_phase1_call(
            local_client, text, messages, alias_map, active_entities,
            prev_chunk_text, next_chunk_text, chunk_id, retry_messages,
            run_id=run_id, attempt_number=handler.state.attempt
        )
        return result

    def build_retry_messages() -> list[dict]:
        """构建重试消息"""
        if handler.state.last_bad_output and handler.state.last_invalid_names:
            original_user_prompt = messages[-1]["content"]
            retry_prompt = build_retry_prompt(
                original_user_prompt,
                handler.state.last_bad_output,
                handler.state.last_invalid_names
            )
            return messages[:-1] + [{"role": "user", "content": retry_prompt}]
        return messages

    return handler.execute(operation, build_retry_messages)


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
    run_id: str | None = None,
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

    修改时间: 2026-03-19
    修改者: TraeAI
    任务: 添加模型交互记录保存
    修改内容: 添加 run_id 参数传递
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
        run_id=run_id,
    )
