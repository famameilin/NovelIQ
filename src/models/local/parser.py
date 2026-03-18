"""
创建时间: 2026-03-12
创建者: TraeAI
任务: 项目文件结构整理与拆解 - 从 unified_client.py 拆分解析模块

本模块包含标注结果的解析逻辑，包括 JSON 解析和 ChunkAnnotation 构建。

修改时间: 2026-03-12
修改者: TraeAI
任务: fix-annotation-disambiguation-issues
修改内容:
- 更新 build_annotation 函数，解析 character_appearances 和 chunk_summary 新字段
- 更新 make_empty_annotation 函数，确保包含新字段的默认值

修改时间: 2026-03-18
修改者: TraeAI
任务: code-quality-refactor - Task 9 拆分parser.py
修改内容:
- 将模块拆分为子包 src.models.local.parser
- 保留此文件作为兼容性转发，所有导出从子包导入
- 保持向后兼容，现有导入路径不变
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
