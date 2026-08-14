"""
解析模块

说明: 提供现行运行路径仍使用的 JSON、思考内容与通用文本解析工具
"""

from __future__ import annotations

from .json_utils import (
    fix_json,
    try_parse_json,
)
from .thinking import (
    ThinkingExtraction,
    extract_think_content,
    extract_thinking_unified,
)
from .utils import parse_active_entities

__all__ = [
    # 思考参数
    "ThinkingExtraction",
    "extract_thinking_unified",
    "extract_think_content",
    # JSON 工具
    "try_parse_json",
    "fix_json",
    # 通用工具
    "parse_active_entities",
]
