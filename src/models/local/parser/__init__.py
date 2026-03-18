"""
解析模块

创建时间: 2026-03-18
创建者: TraeAI
任务: code-quality-refactor - Task 9 拆分parser.py
说明: 标注结果解析模块，包含JSON解析、标注构建、伏笔解析等功能

修改时间: 2026-03-18
修改者: TraeAI
任务: code-quality-refactor - Task 9 拆分parser.py
修改内容: 从单文件拆分为子模块
"""

from __future__ import annotations

from .annotation_builder import (
    build_annotation,
    make_empty_annotation,
)
from .disambiguation import (
    DisambiguationParseError,
    parse_alias_map,
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
    # thinking
    "ThinkingExtraction",
    "extract_thinking_unified",
    "extract_think_content",
    # json_utils
    "try_parse_json",
    "fix_json",
    # annotation_builder
    "make_empty_annotation",
    "build_annotation",
    # foreshadowing
    "parse_foreshadowing_result",
    "validate_foreshadowing_result",
    # disambiguation
    "DisambiguationParseError",
    "parse_alias_map",
    # utils
    "parse_active_entities",
]
