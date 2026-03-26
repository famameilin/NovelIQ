"""
创建时间: 2026-03-18
创建者: TraeAI
任务: code-quality-refactor - Task 8 拆分annotation_client
说明: 响应处理和thinking提取逻辑
"""

from __future__ import annotations

from typing import Any

from loguru import logger

from src.models.local.parser import extract_thinking_unified


def process_annotation_response(
    response: Any,
    is_cloud: bool,
    novel_id: str | None,
    chunk_id: int | None,
    phase: str = "",
) -> tuple[str, str | None, Any]:
    """
    封装响应处理和thinking提取

    创建时间: 2026-03-13
    创建者: TraeAI
    任务: refactor-model-interaction-layer
    说明: 从 annotate_chunk 拆分出的响应处理逻辑

    修改时间: 2026-03-17
    修改者: TraeAI
    任务: 优化云端模型日志，显示更多调用信息
    修改内容: 添加 chunk_id、phase、novel_id 参数到日志

    修改时间: 2026-03-18
    修改者: TraeAI
    任务: code-quality-refactor - Task 8 拆分annotation_client
    修改内容: 从 AnnotationClient 类方法提取为独立函数

    Args:
        response: API 响应对象
        is_cloud: 是否为云端模型
        novel_id: 小说ID（可选）
        chunk_id: 文本块ID（可选）
        phase: 当前阶段（可选）

    Returns:
        tuple: (content_clean, thinking_content, extraction)
            - content_clean: 清理后的内容（不含思考内容）
            - thinking_content: 提取的思考内容
            - extraction: 完整的提取结果对象
    """
    message = response.choices[0].message
    content = message.content or ""
    reasoning_content = getattr(message, "reasoning_content", None)

    extraction = extract_thinking_unified(
        content=content,
        reasoning_content=reasoning_content,
        support_reasoning_content=True,
        support_think_tags=True,
    )

    thinking_content = extraction.thinking_content
    content_clean = extraction.content_without_thinking

    has_thinking = bool(thinking_content and thinking_content.strip())
    has_response = bool(content_clean and content_clean.strip())

    if is_cloud:
        logger.info(
            "[云端模型] annotate_chunk 响应: novel_id={} chunk_id={} phase={} has_thinking={} thinking_chars={} has_response={} response_chars={}",
            novel_id,
            chunk_id,
            phase,
            has_thinking,
            len(thinking_content) if thinking_content else 0,
            has_response,
            len(content_clean),
        )
    else:
        logger.info(
            "annotate_chunk response: novel_id={} chunk_id={} phase={} has_thinking={} thinking_chars={} has_response={} response_chars={}",
            novel_id,
            chunk_id,
            phase,
            has_thinking,
            len(thinking_content) if thinking_content else 0,
            has_response,
            len(content_clean),
        )
        logger.debug(
            "annotate_chunk response received: novel_id={} chunk_id={} phase={} chars={} thinking_chars={} thinking_format={}",
            novel_id,
            chunk_id,
            phase,
            len(content_clean),
            len(thinking_content) if thinking_content else 0,
            extraction.thinking_format,
        )

    return content_clean, thinking_content, extraction


def log_prompt_response(
    analysis_logger: Any,
    chunk_id: int | None,
    content_clean: str,
    thinking_content: str | None,
    extraction: Any,
    messages: list[dict],
    text: str,
    prev_summary: str | None,
    model: str,
    task_type: str,
) -> None:
    """
    封装prompt和response日志记录

    创建时间: 2026-03-13
    创建者: TraeAI
    任务: refactor-model-interaction-layer
    说明: 从 annotate_chunk 拆分出的prompt/response日志记录逻辑

    修改时间: 2026-03-18
    修改者: TraeAI
    任务: code-quality-refactor - Task 8 拆分annotation_client
    修改内容: 从 AnnotationClient 类方法提取为独立函数
    """
    if not analysis_logger:
        return

    metadata = {
        "model": model,
        "task_type": task_type,
        "text_len": len(text),
        "has_summary": prev_summary is not None,
    }
    if thinking_content:
        metadata["thinking_content"] = thinking_content
        metadata["thinking_format"] = extraction.thinking_format
        metadata["thinking_tokens"] = extraction.thinking_tokens
    analysis_logger.log_prompt(
        messages=messages,
        response=content_clean,
        metadata=metadata,
        chunk_id=chunk_id,
    )


def log_annotation_result(
    analysis_logger: Any,
    chunk_id: int | None,
    result: Any,
    content_clean: str,
    thinking_content: str | None,
    extraction: Any,
) -> None:
    """
    封装标注结果日志记录

    创建时间: 2026-03-13
    创建者: TraeAI
    任务: refactor-model-interaction-layer
    说明: 从 annotate_chunk 拆分出的标注结果日志记录逻辑

    修改时间: 2026-03-18
    修改者: TraeAI
    任务: code-quality-refactor - Task 8 拆分annotation_client
    修改内容: 从 AnnotationClient 类方法提取为独立函数
    """
    if not analysis_logger:
        return

    annotation_metadata = {}
    if thinking_content:
        annotation_metadata["thinking_content"] = thinking_content
        annotation_metadata["thinking_format"] = extraction.thinking_format
    analysis_logger.log_annotation(
        chunk_id=chunk_id or 0,
        annotation=result.to_dict(),
        raw_response=content_clean,
        metadata=annotation_metadata,
    )
