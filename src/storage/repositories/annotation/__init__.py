"""
标注数据 Repository 包

创建时间: 2026-03-18
创建者: TraeAI
任务: code-quality-refactor - 拆分annotation_repository
说明: 标注数据仓库模块，包含标注插入、查询、角色操作等
"""

from __future__ import annotations

from . import characters, foreshadowing_threads, inserts, locations, queries
from .repository import AnnotationRepository

__all__ = [
    "AnnotationRepository",
    "characters",
    "foreshadowing_threads",
    "inserts",
    "locations",
    "queries",
]
