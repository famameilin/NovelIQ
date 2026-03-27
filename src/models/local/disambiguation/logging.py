"""
消歧日志模块

创建时间: 2026-03-18
创建者: TraeAI
任务: code-quality-refactor - Task 9 拆分disambiguation_client.py
说明: 提取消歧日志相关逻辑
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

from loguru import logger

if TYPE_CHECKING:
    from src.config.analysis_logger import AnalysisLogger

    from ..schema import DisambiguateResponseModel


def log_disambiguate_start(
    log_type: str,
    count: int,
    is_cloud: bool,
    novel_id: str | None,
    task_type: str,
    model: str | None,
    thinking_enabled: bool,
) -> None:
    """
    统一记录消歧开始日志，区分云端/本地

    创建时间: 2026-03-13
    创建者: TraeAI
    任务: refactor-model-interaction-layer

    修改时间: 2026-03-18
    修改者: TraeAI
    任务: code-quality-refactor - Task 9 拆分disambiguation_client.py
    修改内容: 提取为独立模块函数
    """
    if is_cloud:
        logger.info(
            "[云端模型] {} 开始: novel_id={} task_type={} model={} count={} thinking_enabled={}",
            log_type,
            novel_id,
            task_type,
            model,
            count,
            thinking_enabled,
        )
    else:
        logger.debug(
            "{} start: novel_id={} task_type={} model={} count={} thinking_enabled={}",
            log_type,
            novel_id,
            task_type,
            model,
            count,
            thinking_enabled,
        )


def log_disambiguate_response(
    log_type: str,
    alias_count: int,
    is_cloud: bool,
    novel_id: str | None,
) -> None:
    """
    统一处理消歧响应日志

    创建时间: 2026-03-13
    创建者: TraeAI
    任务: refactor-model-interaction-layer

    修改时间: 2026-03-18
    修改者: TraeAI
    任务: code-quality-refactor - Task 9 拆分disambiguation_client.py
    修改内容: 提取为独立模块函数
    """
    if is_cloud:
        logger.info(
            "[云端模型] {} 响应: novel_id={} alias_count={}",
            log_type,
            novel_id,
            alias_count,
        )
    else:
        logger.info(
            "{} response: novel_id={} alias_count={}",
            log_type,
            novel_id,
            alias_count,
        )


def log_disambiguate_result(
    analysis_logger: AnalysisLogger | None,
    messages: list[dict[str, str]],
    response_data: DisambiguateResponseModel,
    metadata: dict[str, Any],
) -> None:
    """
    统一记录消歧结果日志到 analysis_logger

    创建时间: 2026-03-13
    创建者: TraeAI
    任务: refactor-model-interaction-layer

    修改时间: 2026-03-16
    修改者: TraeAI
    任务: 重构本地消歧客户端集成 Instructor
    修改内容: 适配 DisambiguateResponseModel，简化日志记录

    修改时间: 2026-03-17
    修改者: TraeAI
    任务: 添加 thinking_content 记录
    修改内容: 从响应对象提取并记录 thinking_content

    修改时间: 2026-03-18
    修改者: TraeAI
    任务: code-quality-refactor - Task 9 拆分disambiguation_client.py
    修改内容: 提取为独立模块函数

    修改时间: 2026-03-27
    修改者: TraeAI
    任务: 简化消歧响应模型
    修改内容: 将 merge_target_map 改为 alias_map
    """
    if not analysis_logger:
        return

    response_content = json.dumps(response_data.alias_map, ensure_ascii=False)

    # 添加 thinking_content 到 metadata（如果存在）
    thinking_content = getattr(response_data, "_thinking_content", None)
    if thinking_content:
        metadata["thinking_content"] = thinking_content
        metadata["thinking_format"] = "reasoning_content"
        metadata["thinking_tokens"] = len(thinking_content) // 2

    analysis_logger.log_prompt(
        messages=messages,
        response=response_content,
        metadata=metadata,
        chunk_id=None,
    )
