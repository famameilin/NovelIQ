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

修改时间: 2026-03-27
修改者: TraeAI
任务: 创建统一的模型交互记录接口
修改内容: 使用 record_model_interaction 替代本地 _save_interaction 函数
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING

from src.config import settings
from src.models.interactions import record_model_interaction
from src.models.local.retry_handler import AnnotationRetryHandler, RetryConfig
from src.models.local.schema import ForeshadowingResult

from .context import Phase2MaxRetriesExceededError
from .messages import _build_foreshadowing_messages

if TYPE_CHECKING:
    from src.models.annotation import AnnotationClient


async def _do_phase2(
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

    修改时间: 2026-04-09
    修改者: TraeAI
    任务: 重构 AnnotationClient 使用 async
    修改内容: 改为 async def

    修改时间: 2026-04-22
    修改者: Codex
    任务: unify-estimated-token-accounting
    修改内容: Phase2 token_usage 改为统一估算口径，不再依赖 provider usage

    修改时间: 2026-04-22
    修改者: Codex
    任务: fix-token-coverage-fallback-bucket
    修改内容: fallback 标注客户端执行 Phase2 时，token_usage 仍归入 annotation 主业务桶，
              避免 coverage 把已入账调用误判成缺口
    """
    start_time = time.time()
    is_cloud = client._is_cloud_api()
    client._log_annotation_start(is_cloud, text, prev_chunk_summary, chunk_id, "phase2")

    enable_thinking = client._config.thinking_enabled

    result, response = await client._call_annotation_api(
        messages=messages,
        enable_thinking=enable_thinking,
        chunk_id=chunk_id,
        response_model=ForeshadowingResult,
        call_type="phase2",
    )

    try:
        content_clean, thinking_content, extraction = client._process_annotation_response(
            response, is_cloud, chunk_id, "phase2"
        )

        duration_ms = int((time.time() - start_time) * 1000)
        extract_reasoning_tokens = getattr(client, "_extract_reasoning_tokens", None)
        reasoning_tokens = extract_reasoning_tokens(response) if callable(extract_reasoning_tokens) else None

        record_model_interaction(
            run_id=run_id,
            chunk_id=chunk_id,
            interaction_type="annotate",
            phase="phase2",
            attempt_number=attempt_number,
            messages=messages,
            response_text=content_clean,
            thinking_content=thinking_content,
            reasoning_tokens=reasoning_tokens,
            requested_thinking=enable_thinking,
            duration_ms=duration_ms,
            model_name=client._config.model if hasattr(client._config, "model") else None,
            model_provider="cloud" if is_cloud else "local",
            session=client._session if hasattr(client, "_session") else None,
        )

        client._log_prompt_response(
            chunk_id, content_clean, thinking_content, extraction, messages, text, prev_chunk_summary
        )

        # 中文注释：这里按 annotation 主业务桶落账，避免 fallback 通道把 coverage 桶名拆散。
        client._record_estimated_token_usage_from_messages(
            messages,
            content_clean,
            "phase2",
            chunk_id,
            task_type="annotation",
        )
    except Exception:
        client._record_estimated_token_usage_from_response(
            messages,
            response,
            "phase2",
            chunk_id,
            task_type="annotation",
        )
        raise

    return result


async def annotate_chunk_phase2(
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
    fallback_client: AnnotationClient | None = None,
    run_id: str | None = None,
    evidence_bundle=None,
) -> ForeshadowingResult | None:
    """
    第二次调用：伏笔分析（带独立重试机制）

    创建时间: 2026-03-14
    创建者: TraeAI
    任务: Chunk 双次调用分析拆分

    修改时间: 2026-04-09
    修改者: TraeAI
    任务: 重构 AnnotationClient 使用 async
    修改内容: 改为 async def
    """
    from src.models.local.schema import ForeshadowingResult

    phase_max_retries = settings.runtime.annotation.phase_max_retries
    config = RetryConfig(
        max_retries=phase_max_retries,
        operation_name="phase2",
        chunk_id=chunk_id,
    )
    handler = AnnotationRetryHandler[ForeshadowingResult](
        config=config,
        primary_client=client,
        fallback_client=fallback_client,
        exception_type=Phase2MaxRetriesExceededError,
    )

    # 中文注释：Phase2 只消费调用方已经准备好的 evidence_bundle，
    # 避免在本阶段继续分叉出新的取证链路，扩大这轮收口任务的边界。
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
        evidence_bundle=evidence_bundle,
    )

    async def operation(
        primary_client: AnnotationClient,
        retry_messages: list[dict] | None = None,
    ) -> ForeshadowingResult:
        """执行单次Phase2调用"""
        msgs = retry_messages if retry_messages else messages
        return await _do_phase2(
            primary_client,
            msgs,
            text,
            prev_chunk_summary,
            chunk_id,
            run_id,
            handler.state.attempt,
        )

    return await handler.execute(operation)
