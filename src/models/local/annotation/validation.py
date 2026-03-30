"""
创建时间: 2026-03-18
创建者: TraeAI
任务: code-quality-refactor - Task 8 拆分annotation_client
说明: 标注结果验证和重试逻辑
"""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING

from loguru import logger

from src.models.local.parser import make_empty_annotation
from src.models.local.prompts import build_retry_prompt
from src.models.local.validator import validate_names_in_sources

if TYPE_CHECKING:
    from src.models.local.schema import ChunkAnnotation


def validate_annotation_names(
    annotation: ChunkAnnotation,
    sources: dict,
    extract_names_func: Callable[[ChunkAnnotation], list[str]],
) -> list[str]:
    """
    验证标注结果中的名字

    创建时间: 2026-03-17
    创建者: TraeAI
    任务: code-quality-refactor - 提取名字验证逻辑
    说明: 提取名字并验证是否在有效来源中

    修改时间: 2026-03-18
    修改者: TraeAI
    任务: code-quality-refactor - Task 8 拆分annotation_client
    修改内容: 从 AnnotationClient 类方法提取为独立函数

    Args:
        annotation: 标注结果对象
        sources: 包含文本来源信息的字典
        extract_names_func: 从标注结果中提取名字的函数

    Returns:
        无效名字列表，如果全部有效则返回空列表
    """
    names_in_result = extract_names_func(annotation)
    return validate_names_in_sources(names_in_result, sources)


def retry_with_validation(
    original_user_prompt: str,
    bad_output: str,
    invalid_names: list[str],
    sources: dict,
    chunk_id: int | None,
    max_retries: int,
    execute_retry_call_func: Callable[[list[dict], int | None], tuple[ChunkAnnotation, str]],
    validate_names_func: Callable[[ChunkAnnotation, dict], list[str]],
) -> tuple[ChunkAnnotation, list[str]]:
    """
    名字验证失败后的内部重试

    修改时间: 2026-03-17
    修改者: TraeAI
    任务: code-quality-refactor - 重构_retry_with_validation
    修改内容:
    - 提取_execute_validation_retry_call方法
    - 提取_validate_annotation_names方法
    - 简化主函数逻辑

    修改时间: 2026-03-18
    修改者: TraeAI
    任务: code-quality-refactor - Task 8 拆分annotation_client
    修改内容: 从 AnnotationClient 类方法提取为独立函数

    Args:
        original_user_prompt: 原始用户提示
        bad_output: 错误的输出内容
        invalid_names: 无效名字列表
        sources: 包含文本来源信息的字典
        chunk_id: 文本块ID（可选）
        max_retries: 最大重试次数
        execute_retry_call_func: 执行重试调用的函数
        validate_names_func: 验证名字的函数

    Returns:
        (result, current_invalid_names)
            - result: 最终的标注结果
            - current_invalid_names: 仍然无效的名字列表
    """
    result = make_empty_annotation()
    current_invalid_names = invalid_names
    retry_prompt = build_retry_prompt(original_user_prompt, bad_output, invalid_names)

    for retry_count in range(max_retries):
        logger.info(
            "annotate_chunk retry attempt {}/{} chunk_id={}",
            retry_count + 1,
            max_retries,
            chunk_id,
        )

        retry_messages = [{"role": "user", "content": retry_prompt}]

        try:
            result, content_clean = execute_retry_call_func(retry_messages, chunk_id)

            current_invalid_names = validate_names_func(result, sources)

            if not current_invalid_names:
                logger.info(
                    "annotate_chunk retry succeeded on attempt {} chunk_id={}",
                    retry_count + 1,
                    chunk_id,
                )
                return result, []

            logger.warning(
                "annotate_chunk retry {} still has invalid names: {} chunk_id={}",
                retry_count + 1,
                current_invalid_names,
                chunk_id,
            )

            retry_prompt = build_retry_prompt(original_user_prompt, content_clean, current_invalid_names)

        except Exception as e:
            logger.error(
                "annotate_chunk retry {} failed with error: {} chunk_id={}",
                retry_count + 1,
                str(e),
                chunk_id,
            )

    return result, current_invalid_names
