"""
Token计数工具模块

说明: 为流式API提供token使用估算功能

本模块提供基于tiktoken的token计数功能，支持多种模型编码器
对于中文内容，使用cl100k_base编码器（GPT-4/GPT-3.5-turbo使用的编码器）
"""

from __future__ import annotations

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

    # 前缀匹配：按前缀长度降序，避免 "gpt-4" 抢先匹配 "gpt-4o-*" 系列
    for model_prefix, encoding in sorted(MODEL_ENCODING_MAP.items(), key=lambda item: len(item[0]), reverse=True):
        if model_prefix in model_name_lower:
            return encoding

    # 默认使用cl100k_base
    return DEFAULT_ENCODING


def count_tokens(text: str, model: str | None = None) -> int:
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
