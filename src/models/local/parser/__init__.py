"""
解析模块

说明: 标注结果解析模块，包含JSON解析、标注构建、伏笔解析等功能
"""

from __future__ import annotations

from .annotation_builder import (
    build_annotation,
    make_empty_annotation,
)
from .foreshadowing import (
    parse_foreshadowing_result,
    validate_foreshadowing_result,
)
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
    # 标注构建器
    "make_empty_annotation",
    "build_annotation",
    # 伏笔处理
    "parse_foreshadowing_result",
    "validate_foreshadowing_result",
    # 通用工具
    "parse_active_entities",
]
