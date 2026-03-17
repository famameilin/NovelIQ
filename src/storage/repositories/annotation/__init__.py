"""
标注数据 Repository 包

创建时间: 2026-03-18
创建者: TraeAI
任务: code-quality-refactor - 拆分annotation_repository
说明: 标注数据仓库模块，包含标注插入、查询、角色操作等
"""

from __future__ import annotations

# 导出主 Repository 类
from .repository import AnnotationRepository

# 导出各模块函数（供内部使用）
from . import characters
from . import inserts
from . import queries

__all__ = [
    "AnnotationRepository",
    "characters",
    "inserts",
    "queries",
]
