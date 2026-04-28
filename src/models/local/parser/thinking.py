"""
思考内容提取模块

说明: 提取思考内容相关逻辑
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal


@dataclass
class ThinkingExtraction:
    """思考内容提取结果"""

    thinking_content: str | None
    content_without_thinking: str
    thinking_format: Literal["reasoning_content", "think_tag", "none"]
    thinking_tokens: int


def extract_thinking_unified(
    content: str,
    reasoning_content: str | None = None,
    support_reasoning_content: bool = True,
    support_think_tags: bool = True,
) -> ThinkingExtraction:
    """
    统一提取思考内容，支持多种格式：
    1. reasoning_content 属性（DeepSeek/Qwen）- 最高优先级
    2. <think> 标签（Qwen fallback）
    3. 无思考内容
    """
    # 优先级1: reasoning_content 属性
    if support_reasoning_content and reasoning_content:
        return ThinkingExtraction(
            thinking_content=reasoning_content.strip(),
            content_without_thinking=content,
            thinking_format="reasoning_content",
            thinking_tokens=len(reasoning_content) // 2,
        )

    # 优先级2: <think> 标签
    if support_think_tags:
        think_match = re.search(r"<think>([\s\S]*?)</think>", content)
        if think_match:
            thinking = think_match.group(1).strip()
            content_clean = re.sub(r"<think>[\s\S]*?</think>\s*", "", content)
            return ThinkingExtraction(
                thinking_content=thinking,
                content_without_thinking=content_clean,
                thinking_format="think_tag",
                thinking_tokens=len(thinking) // 2,
            )

    # 无思考内容
    return ThinkingExtraction(
        thinking_content=None,
        content_without_thinking=content,
        thinking_format="none",
        thinking_tokens=0,
    )


def extract_think_content(content: str) -> str | None:
    """从响应中提取 think 块的内容（不包含标签）"""
    match = re.search(r"<think>([\s\S]*?)</think>", content)
    if match:
        return match.group(1).strip()
    return None
