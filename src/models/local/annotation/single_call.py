"""
单次标注调用模块

创建时间: 2026-03-18
创建者: TraeAI
任务: code-quality-refactor - Task 8 拆分annotation_client
说明: 提取单次标注调用相关逻辑
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from src.models.local.retry_handler import AnnotationRetryHandler, RetryConfig

from .context import PHASE_MAX_RETRIES, AnnotationContext, Phase1MaxRetriesExceededError
from .messages import _build_messages

if TYPE_CHECKING:
    from src.models.local.annotation_client import AnnotationClient
    from src.models.local.schema import ChunkAnnotation


def execute_single_call(
    client: "AnnotationClient",
    ctx: AnnotationContext,
    messages: list[dict],
) -> tuple["ChunkAnnotation", Any]:
    """
    执行单次标注调用

    创建时间: 2026-03-17
    创建者: TraeAI
    任务: code-quality-refactor - 提取单次调用逻辑

    修改时间: 2026-03-18
    修改者: TraeAI
    任务: code-quality-refactor - Task 8 拆分annotation_client
    修改内容: 提取为独立模块函数
    """
    is_cloud = client._is_cloud_api()
    enable_thinking = client._config.thinking_enabled
    response = client._call_annotation_api(messages, enable_thinking, ctx.chunk_id)

    content_clean, thinking_content, extraction = client._process_annotation_response(
        response, is_cloud, ctx.chunk_id, "single_call"
    )

    client._log_prompt_response(
        ctx.chunk_id, content_clean, thinking_content, extraction, messages, ctx.text, ctx.prev_summary
    )

    result = client._parse_annotation(content_clean)

    sources = {
        "text": ctx.text,
        "prev_tail_text": ctx.prev_tail_text or "",
        "active_entities": [],
        "alias_map": ctx.alias_map or {},
        "next_preview": ctx.next_preview or "",
    }

    result = client._validate_annotation(result, sources, ctx.chunk_id, content_clean)

    client._record_token_usage(response, "single_call", ctx.chunk_id)

    return result, response


def annotate_single_call_with_retry(
    client: "AnnotationClient",
    ctx: AnnotationContext,
) -> "ChunkAnnotation":
    """
    单次标注调用（带重试）

    创建时间: 2026-03-17
    创建者: TraeAI
    任务: code-quality-refactor - 提取单次调用逻辑

    修改时间: 2026-03-18
    修改者: TraeAI
    任务: code-quality-refactor - Task 3 统一重试机制
    修改内容: 使用 AnnotationRetryHandler 替代自定义重试逻辑

    修改时间: 2026-03-18
    修改者: TraeAI
    任务: code-quality-refactor - Task 8 拆分annotation_client
    修改内容: 提取为独立模块函数
    """
    from src.models.local.schema import ChunkAnnotation

    messages = _build_messages(
        ctx.text,
        ctx.prev_summary,
        ctx.alias_map,
        ctx.global_context,
        ctx.prev_tail_text,
        ctx.active_entities,
        ctx.rag_evidence,
        ctx.known_aliases,
        ctx.next_preview,
        ctx.chunk_id,
    )

    is_cloud = client._is_cloud_api()
    client._log_annotation_start(is_cloud, ctx.text, ctx.prev_summary, ctx.chunk_id, "single_call")

    config = RetryConfig(
        max_retries=PHASE_MAX_RETRIES,
        operation_name="single_call",
        chunk_id=ctx.chunk_id,
    )
    handler = AnnotationRetryHandler[ChunkAnnotation](
        config=config,
        local_client=client,
        cloud_client=ctx.cloud_client,
        exception_type=Phase1MaxRetriesExceededError,
    )

    def operation(c: "AnnotationClient", retry_messages: list[dict] | None = None) -> "ChunkAnnotation":
        """执行单次调用"""
        msgs = retry_messages if retry_messages else messages
        annotation, _ = execute_single_call(c, ctx, msgs)
        return annotation

    return handler.execute(operation)
