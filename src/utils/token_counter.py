"""
Token计数工具模块

创建时间: 2026-03-17
创建者: TraeAI
任务: 使用tiktoken估算token数量
说明: 为流式API提供token使用估算功能

本模块提供基于tiktoken的token计数功能，支持多种模型编码器。
对于中文内容，使用cl100k_base编码器（GPT-4/GPT-3.5-turbo使用的编码器）。
"""

from __future__ import annotations

from typing import Optional

import tiktoken
from loguru import logger


# 默认编码器（cl100k_base是GPT-4和GPT-3.5-turbo使用的编码器）
DEFAULT_ENCODING = "cl100k_base"

# 模型到编码器的映射
MODEL_ENCODING_MAP = {
    "gpt-4": "cl100k_base",
    "gpt-4o": "o200k_base",
    "gpt-4o-mini": "o200k_base",
    "gpt-3.5-turbo": "cl100k_base",
    "text-embedding-3": "cl100k_base",
    "text-embedding-ada-002": "cl100k_base",
}

# 缓存编码器实例
_encoding_cache: dict[str, tiktoken.Encoding] = {}


def _get_encoding(encoding_name: str) -> tiktoken.Encoding:
    """
    获取编码器实例（带缓存）

    Args:
        encoding_name: 编码器名称

    Returns:
        tiktoken.Encoding: 编码器实例
    """
    if encoding_name not in _encoding_cache:
        _encoding_cache[encoding_name] = tiktoken.get_encoding(encoding_name)
    return _encoding_cache[encoding_name]


def _get_encoding_for_model(model_name: str) -> str:
    """
    根据模型名称获取对应的编码器名称

    Args:
        model_name: 模型名称

    Returns:
        str: 编码器名称
    """
    model_name_lower = model_name.lower()

    # 精确匹配
    if model_name_lower in MODEL_ENCODING_MAP:
        return MODEL_ENCODING_MAP[model_name_lower]

    # 前缀匹配
    for model_prefix, encoding in MODEL_ENCODING_MAP.items():
        if model_prefix in model_name_lower:
            return encoding

    # 默认使用cl100k_base
    return DEFAULT_ENCODING


def count_tokens(text: str, model: Optional[str] = None) -> int:
    """
    计算文本的token数量

    Args:
        text: 要计算的文本
        model: 模型名称（用于选择编码器），默认为None使用cl100k_base

    Returns:
        int: token数量

    Example:
        >>> count_tokens("Hello, world!")
        4
        >>> count_tokens("你好，世界！", model="gpt-4")
        6
    """
    if not text:
        return 0

    try:
        encoding_name = _get_encoding_for_model(model) if model else DEFAULT_ENCODING
        encoding = _get_encoding(encoding_name)
        return len(encoding.encode(text))
    except Exception as e:
        logger.warning(f"Failed to count tokens: {e}, falling back to character count estimation")
        # 回退方案：中文字符按2个token估算，其他按1个token估算
        return sum(2 if ord(char) > 127 else 1 for char in text)


def count_messages_tokens(messages: list[dict[str, str]], model: Optional[str] = None) -> int:
    """
    计算消息列表的token数量

    按照OpenAI的格式计算：
    - 每条消息有4个额外token（角色标记等）
    - 最后加上2个token

    Args:
        messages: 消息列表，格式为[{"role": "user", "content": "..."}, ...]
        model: 模型名称

    Returns:
        int: token数量
    """
    if not messages:
        return 0

    try:
        encoding_name = _get_encoding_for_model(model) if model else DEFAULT_ENCODING
        encoding = _get_encoding(encoding_name)

        total_tokens = 0
        for message in messages:
            # 每条消息的基础token开销
            total_tokens += 4

            # 角色token
            role = message.get("role", "")
            if role:
                total_tokens += len(encoding.encode(role))

            # 内容token
            content = message.get("content", "")
            if content:
                total_tokens += len(encoding.encode(content))

        # 最后加上2个token
        total_tokens += 2

        return total_tokens
    except Exception as e:
        logger.warning(f"Failed to count message tokens: {e}, using simple estimation")
        # 简单估算：每条消息100个token
        return len(messages) * 100


def estimate_completion_tokens(prompt_tokens: int, ratio: float = 1.5) -> int:
    """
    估算完成token数量

    Args:
        prompt_tokens: 提示token数量
        ratio: 完成token与提示token的比例，默认为1.5

    Returns:
        int: 估算的完成token数量
    """
    return int(prompt_tokens * ratio)


def format_token_count(count: int) -> str:
    """
    格式化token数量为易读字符串

    Args:
        count: token数量

    Returns:
        str: 格式化后的字符串
    """
    if count >= 1_000_000:
        return f"{count / 1_000_000:.2f}M"
    elif count >= 1_000:
        return f"{count / 1_000:.1f}K"
    else:
        return str(count)
