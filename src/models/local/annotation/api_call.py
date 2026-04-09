"""
创建时间: 2026-03-18
创建者: TraeAI
任务: code-quality-refactor - Task 9 拆分annotation_client
说明: API调用和验证相关逻辑

修改时间: 2026-03-21
修改者: TraeAI
任务: migrate-litellm-to-openai-sdk
修改内容: 使用 OpenAI SDK，移除 get_model_with_provider 调用
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, TypeVar, cast

from loguru import logger

from src.models.local.parser import extract_thinking_unified, try_parse_json
from src.models.local.validator import (
    validate_chunk_annotation,
    validate_names_in_sources,
)

from .context import NameValidationMaxRetriesExceededError

if TYPE_CHECKING:
    from src.models.local.schema import ChunkAnnotation

T = TypeVar("T")


def parse_annotation(content: str) -> ChunkAnnotation:
    """
    解析标注结果

    创建时间: 2026-03-16
    创建者: TraeAI
    任务: 重构本地标注客户端集成 Instructor
    修改内容: 添加说明，此方法作为 fallback 使用，Instructor 会自动解析

    修改时间: 2026-03-18
    创建者: TraeAI
    任务: code-quality-refactor - Task 9 拆分annotation_client
    修改内容: 从 AnnotationClient 类方法提取为独立函数
    """
    from src.models.local.parser import build_annotation, make_empty_annotation

    parsed = try_parse_json(content)
    if parsed is None:
        logger.error(
            "json parse failed after all fix attempts, content preview: {}", content[:500] if content else "empty"
        )
        return make_empty_annotation()
    if not isinstance(parsed, dict):
        logger.error("annotate_chunk response not dict, got type: {}", type(parsed).__name__)
        return make_empty_annotation()
    return build_annotation(parsed)


def extract_names_from_annotation(annotation: ChunkAnnotation) -> list[str]:
    """
    从标注结果中提取所有名字

    创建时间: 2026-03-18
    创建者: TraeAI
    任务: code-quality-refactor - Task 9 拆分annotation_client
    说明: 从 AnnotationClient 类方法提取为独立函数

    修改时间: 2026-03-29
    修改者: TraeAI
    任务: remove-unused-annotation-fields
    修改内容: 移除 relations 相关逻辑
    """
    names: set[str] = set()
    for character in annotation.characters:
        if character.name:
            names.add(character.name)
    for dialogue in annotation.dialogues:
        if dialogue.speaker:
            for s in dialogue.speaker:
                names.add(s)
    return list(names)


def validate_annotation(
    result: ChunkAnnotation,
    sources: dict,
    chunk_id: int | None,
    content_clean: str = "",
) -> ChunkAnnotation:
    """
    验证标注结果中的人名是否在原文中出现

    创建时间: 2026-03-14
    创建者: TraeAI
    任务: 简化重试逻辑
    说明: 只验证，不重试。验证失败直接抛异常

    修改时间: 2026-03-16
    修改者: TraeAI
    修改内容: 添加 content_clean 参数，在异常中包含原始输出

    修改时间: 2026-03-18
    创建者: TraeAI
    任务: code-quality-refactor - Task 9 拆分annotation_client
    修改内容: 从 AnnotationClient 类方法提取为独立函数

    修改时间: 2026-03-27
    修改者: Codex
    任务: fix-character-appearance-validation-conflict
    修改内容: 将“来源不存在”和“relations/dialogues 悬空引用”分开校验，
        不再要求 character_appearances 中的名字强制同步到 characters
    """
    names_in_result = extract_names_from_annotation(result)
    hallucinated_names = set(validate_names_in_sources(names_in_result, sources))
    _, dangling_names = validate_chunk_annotation(result, {character.name for character in result.characters})
    invalid_names = hallucinated_names | set(dangling_names)

    if invalid_names:
        invalid_names_sorted = sorted(invalid_names)
        validation_details = {
            "hallucinated_names": sorted(hallucinated_names),
            "dangling_names": sorted(set(dangling_names)),
        }
        logger.error(
            "annotate_chunk found invalid names: {} chunk_id={}",
            invalid_names_sorted,
            chunk_id,
        )
        raise NameValidationMaxRetriesExceededError(
            f"名字验证失败: {invalid_names_sorted}",
            invalid_names=invalid_names_sorted,
            bad_output=content_clean,
            validation_details=validation_details,
        )

    return result


def execute_validation_retry_call(
    client: Any,
    retry_messages: list[dict],
    chunk_id: int | None,
    config: Any,
    parse_annotation_func: Any,
) -> tuple[ChunkAnnotation, str]:
    """
    执行单次验证重试调用

    创建时间: 2026-03-17
    创建者: TraeAI
    任务: code-quality-refactor - 提取API调用逻辑
    说明: 从_retry_with_validation中提取的API调用逻辑

    修改时间: 2026-03-18
    创建者: TraeAI
    任务: code-quality-refactor - Task 9 拆分annotation_client
    修改内容: 从 AnnotationClient 类方法提取为独立函数

    修改时间: 2026-03-21
    修改者: TraeAI
    任务: migrate-litellm-to-openai-sdk
    修改内容: 使用 OpenAI SDK，移除 extra_body，添加 reasoning_effort 支持
    """
    config.validate()

    client_obj = client._client
    if client_obj is None:
        raise ValueError("client is required")

    enable_thinking = config.thinking_enabled

    request_params = {
        "model": config.model,
        "messages": cast(Any, retry_messages),
        "temperature": config.temperature,
        "top_p": config.top_p,
    }

    if enable_thinking:
        request_params["reasoning_effort"] = "medium"

    response = client_obj.chat.completions.create(**request_params)
    message = response.choices[0].message
    content = message.content or ""

    extraction = extract_thinking_unified(
        content=content,
        reasoning_content=getattr(message, "reasoning_content", None),
        support_reasoning_content=True,
        support_think_tags=True,
    )

    thinking_content = extraction.thinking_content
    content_clean = extraction.content_without_thinking

    logger.info(
        "annotate_chunk retry response: thinking_chars={} response_chars={}",
        len(thinking_content) if thinking_content else 0,
        len(content_clean),
    )

    result = parse_annotation(content_clean)
    return result, content_clean


def log_annotation_start(
    novel_id: str | None,
    task_type: str,
    model: str | None,
    thinking_enabled: bool,
    is_cloud: bool,
    text: str,
    prev_summary: str | None,
    chunk_id: int | None,
    phase: str = "",
) -> None:
    """
    封装标注开始日志

    创建时间: 2026-03-13
    创建者: TraeAI
    任务: refactor-model-interaction-layer
    说明: 从 annotate_chunk 拆分出的开始日志逻辑

    修改时间: 2026-03-17
    修改者: TraeAI
    任务: 优化云端模型日志，显示更多调用信息
    修改内容: 添加 novel_id、phase 参数到日志

    修改时间: 2026-03-18
    创建者: TraeAI
    任务: code-quality-refactor - Task 9 拆分annotation_client
    修改内容: 从 AnnotationClient 类方法提取为独立函数
    """
    if is_cloud:
        logger.info(
            "[云端模型] annotate_chunk 开始: "
            "novel_id={} chunk_id={} phase={} "
            "task_type={} model={} text_len={} thinking_enabled={}",
            novel_id,
            chunk_id,
            phase,
            task_type,
            model,
            len(text),
            thinking_enabled,
        )
    else:
        logger.debug(
            "annotate_chunk start: "
            "novel_id={} chunk_id={} phase={} "
            "task_type={} model={} text_len={} "
            "has_summary={} thinking_enabled={}",
            novel_id,
            chunk_id,
            phase,
            task_type,
            model,
            len(text),
            prev_summary is not None,
            thinking_enabled,
        )


def should_use_stream(config: Any) -> bool:
    """
    判断是否应该使用流式响应模式

    创建时间: 2026-03-16
    创建者: TraeAI
    任务: 启用云端Stream模式
    说明: 根据配置和是否为云端API决定是否使用流式模式

    修改时间: 2026-03-18
    创建者: TraeAI
    任务: code-quality-refactor - Task 9 拆分annotation_client
    修改内容: 从 AnnotationClient 类方法提取为独立函数
    """
    if not config.stream_enabled:
        return False

    return True
