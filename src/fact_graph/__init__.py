"""事实图：权威读视图（authority）与写入面（graph）

说明: 包级不维护 eager re-export——写入面与读视图互相引用，eager 导入会形成环；
消费者按子模块路径导入（`src.fact_graph.graph` / `src.fact_graph.authority`）。
"""

from __future__ import annotations

from importlib import import_module
from typing import Any

__all__ = [
    "CanonicalEntity",
    "ConfirmedRelation",
    "EntityLifecycle",
    "EntityTypeFact",
    "ExportGraphAuthorityView",
    "ExportRelationSnapshot",
    "GraphAuthorityReport",
    "GraphAuthorityView",
    "GraphChange",
    "KnowledgeGraphAuthorityService",
    "Level1AuthoritySnapshot",
    "ParticipantState",
    "TimelineAuthorityView",
]


def __getattr__(name: str) -> Any:
    """2026-10-06 用于按需加载权威视图出口，避免事实图写入面与存储层形成导入环"""
    if name in __all__:
        return getattr(import_module("src.fact_graph.authority"), name)
    raise AttributeError(f"module 'src.fact_graph' has no attribute {name!r}")
