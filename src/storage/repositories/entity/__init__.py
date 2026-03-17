"""
实体数据 Repository 包

创建时间: 2026-03-18
创建者: TraeAI
任务: code-quality-refactor - 拆分entity_repository
说明: 实体数据仓库模块，包含实体查询、关系、元数据等操作
"""

from __future__ import annotations

# 导出主 Repository 类
from .repository import EntityRepository

# 导出各模块函数（供内部使用）
from . import metadata
from . import queries
from . import relations

__all__ = [
    "EntityRepository",
    "metadata",
    "queries",
    "relations",
]
