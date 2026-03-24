"""
Parser 兼容性转发模块

创建时间: 2026-03-12
创建者: TraeAI
任务: 项目文件结构整理与拆解 - 拆分解析模块

修改历史:
- 2026-03-12: 更新 build_annotation 函数，解析 character_appearances 和 chunk_summary 新字段
- 2026-03-18: 拆分为子包 src.models.local.parser，此文件作为兼容性转发

说明:
- 此文件保留向后兼容，所有功能已移至 src.models.local.parser 子包
"""

from __future__ import annotations

# 从子包导入所有公共API，保持向后兼容
from src.models.local.parser import (
    DisambiguationParseError,
    ThinkingExtraction,
    build_annotation,
    extract_think_content,
    extract_thinking_unified,
    fix_json,
    make_empty_annotation,
    parse_active_entities,
    parse_alias_map,
    parse_foreshadowing_result,
    try_parse_json,
    validate_foreshadowing_result,
)

__all__ = [
    "ThinkingExtraction",
    "extract_thinking_unified",
    "extract_think_content",
    "try_parse_json",
    "fix_json",
    "make_empty_annotation",
    "build_annotation",
    "parse_foreshadowing_result",
    "validate_foreshadowing_result",
    "DisambiguationParseError",
    "parse_alias_map",
    "parse_active_entities",
]
