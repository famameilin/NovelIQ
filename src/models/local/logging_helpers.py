"""
创建时间: 2026-03-13
创建者: TraeAI
任务: refactor-model-interaction-layer

本模块提供日志记录辅助函数，用于统一API调用日志格式。
支持区分云端/本地日志格式，减少客户端代码重复。
"""

from __future__ import annotations

from loguru import logger


def log_api_call_start(
    call_type: str,
    model: str,
    is_cloud: bool,
    extra_info: dict | None = None,
) -> None:
    """
    记录API调用开始日志

    创建时间: 2026-03-13
    创建者: TraeAI
    任务: refactor-model-interaction-layer

    区分云端/本地日志格式：
    - 云端: logger.info("[云端模型] {call_type} 开始: model={} ...")
    - 本地: logger.debug("{call_type} start model={} ...")

    Args:
        call_type: 调用类型，如 "annotate", "disambiguate", "embedding" 等
        model: 模型名称
        is_cloud: 是否为云端API
        extra_info: 额外的日志信息字典
    """
    extra_info = extra_info or {}

    if is_cloud:
        log_parts = [f"[云端模型] {call_type} 开始: model={model}"]
        for key, value in extra_info.items():
            log_parts.append(f"{key}={value}")
        logger.info(" ".join(log_parts))
    else:
        log_parts = [f"{call_type} start model={model}"]
        for key, value in extra_info.items():
            log_parts.append(f"{key}={value}")
        logger.debug(" ".join(log_parts))


def log_api_call_response(
    call_type: str,
    has_thinking: bool,
    thinking_chars: int,
    has_response: bool,
    response_chars: int,
    is_cloud: bool,
) -> None:
    """
    记录API响应日志

    创建时间: 2026-03-13
    创建者: TraeAI
    任务: refactor-model-interaction-layer

    区分云端/本地日志格式：
    - 云端: logger.info("[云端模型] {call_type} 响应: ...")
    - 本地: logger.info("{call_type} response: ...")

    Args:
        call_type: 调用类型，如 "annotate", "disambiguate", "embedding" 等
        has_thinking: 是否有thinking内容
        thinking_chars: thinking内容字符数
        has_response: 是否有响应内容
        response_chars: 响应内容字符数
        is_cloud: 是否为云端API
    """
    if is_cloud:
        logger.info(
            "[云端模型] {} 响应: has_thinking={} thinking_chars={} has_response={} response_chars={}",
            call_type,
            has_thinking,
            thinking_chars,
            has_response,
            response_chars,
        )
    else:
        logger.info(
            "{} response: has_thinking={} thinking_chars={} has_response={} response_chars={}",
            call_type,
            has_thinking,
            thinking_chars,
            has_response,
            response_chars,
        )


def log_thinking_info(
    thinking_content: str | None,
    thinking_format: str,
    thinking_tokens: int,
) -> dict:
    """
    构建thinking相关的metadata字典

    创建时间: 2026-03-13
    创建者: TraeAI
    任务: refactor-model-interaction-layer

    Args:
        thinking_content: thinking内容字符串
        thinking_format: thinking格式标识
        thinking_tokens: thinking token数量

    Returns:
        包含thinking信息的metadata字典，如果thinking_content为空则返回空字典
    """
    if not thinking_content or not thinking_content.strip():
        return {}

    return {
        "thinking_content": thinking_content,
        "thinking_format": thinking_format,
        "thinking_tokens": thinking_tokens,
    }


def log_api_error(
    call_type: str,
    error: Exception,
    is_cloud: bool,
    extra_info: dict | None = None,
) -> None:
    """
    记录API错误日志

    创建时间: 2026-03-13
    创建者: TraeAI
    任务: refactor-model-interaction-layer

    区分云端/本地日志格式：
    - 云端: logger.info("[云端模型] {call_type} 错误: ...")
    - 本地: logger.error("{call_type} error: ...")

    Args:
        call_type: 调用类型，如 "annotate", "disambiguate", "embedding" 等
        error: 异常对象
        is_cloud: 是否为云端API
        extra_info: 额外的日志信息字典
    """
    extra_info = extra_info or {}
    error_str = str(error)

    if is_cloud:
        log_parts = [f"[云端模型] {call_type} 错误: error={error_str}"]
        for key, value in extra_info.items():
            log_parts.append(f"{key}={value}")
        logger.info(" ".join(log_parts))
    else:
        log_parts = [f"{call_type} error: error={error_str}"]
        for key, value in extra_info.items():
            log_parts.append(f"{key}={value}")
        logger.error(" ".join(log_parts))


def log_api_complete(
    call_type: str,
    is_cloud: bool,
    extra_info: dict | None = None,
) -> None:
    """
    记录API调用完成日志

    创建时间: 2026-03-13
    创建者: TraeAI
    任务: refactor-model-interaction-layer

    Args:
        call_type: 调用类型，如 "annotate", "disambiguate", "embedding" 等
        is_cloud: 是否为云端API
        extra_info: 额外的日志信息字典
    """
    extra_info = extra_info or {}

    if is_cloud:
        log_parts = [f"[云端模型] {call_type} 完成"]
        for key, value in extra_info.items():
            log_parts.append(f"{key}={value}")
        logger.info(" ".join(log_parts))
    else:
        logger.debug("{} complete", call_type)


__all__ = [
    "log_api_call_start",
    "log_api_call_response",
    "log_thinking_info",
    "log_api_error",
    "log_api_complete",
]
