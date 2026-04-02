"""
创建时间: 2026-03-18
创建者: TraeAI
任务: code-quality-refactor - Task 8 拆分annotation_client
说明: 响应处理和thinking提取逻辑

修改时间: 2026-03-30
修改者: TraeAI
任务: feature/chunk-summary-timeline-only
修改内容: 添加重复输出检测，防止模型生成循环内容
"""

from __future__ import annotations

import re
from typing import Any

from loguru import logger

from src.models.local.parser import extract_thinking_unified


class RepetitiveOutputError(Exception):
    """
    LLM 输出重复异常

    创建时间: 2026-03-30
    创建者: TraeAI
    任务: feature/chunk-summary-timeline-only
    说明: 当 LLM 输出包含重复模式时抛出，触发重试机制
    """

    pass


def _detect_repetition(content: str, threshold: int = 3000) -> tuple[bool, str | None]:
    """
    检测 LLM 输出是否存在重复模式

    创建时间: 2026-03-30
    创建者: TraeAI
    任务: feature/chunk-summary-timeline-only
    说明: 当响应字符数异常大时，检测是否有重复内容

    Args:
        content: 响应内容
        threshold: 触发检测的字符数阈值

    Returns:
        tuple: (is_repetitive, pattern) - 是否重复，以及检测到的重复模式
    """
    if len(content) < threshold:
        return False, None

    lines = content.split("\n")
    if len(lines) < 3:
        return False, None

    line_counts: dict[str, int] = {}
    for line in lines:
        line = line.strip()
        if len(line) > 20:
            line_counts[line] = line_counts.get(line, 0) + 1

    for line, count in line_counts.items():
        if count >= 3:
            return True, line[:50] + "..." if len(line) > 50 else line

    for pattern in [r'"[^"]+":\s*"[^"]*",?\s*', r"\{[^}]+\},?\s*"]:
        matches = re.findall(pattern, content)
        if len(matches) >= 5:
            match_counts: dict[str, int] = {}
            for m in matches:
                match_counts[m] = match_counts.get(m, 0) + 1
            for m, count in match_counts.items():
                if count >= 3:
                    return True, m[:50] + "..." if len(m) > 50 else m

    return False, None


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

    is_repetitive, repeat_pattern = _detect_repetition(content_clean)
    if is_repetitive:
        logger.error(
            "检测到重复输出: novel_id={} chunk_id={} phase={} response_chars={} pattern={}",
            novel_id,
            chunk_id,
            phase,
            len(content_clean),
            repeat_pattern,
        )
        raise RepetitiveOutputError(f"LLM output contains repetitive pattern: {repeat_pattern}")

    if is_cloud:
        logger.info(
            "[云端模型] annotate_chunk 响应: "
            "novel_id={} chunk_id={} phase={} "
            "has_thinking={} thinking_chars={} "
            "has_response={} response_chars={}",
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
            "annotate_chunk response: "
            "novel_id={} chunk_id={} phase={} "
            "has_thinking={} thinking_chars={} "
            "has_response={} response_chars={}",
            novel_id,
            chunk_id,
            phase,
            has_thinking,
            len(thinking_content) if thinking_content else 0,
            has_response,
            len(content_clean),
        )
        logger.debug(
            "annotate_chunk response received: "
            "novel_id={} chunk_id={} phase={} "
            "chars={} thinking_chars={} thinking_format={}",
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
