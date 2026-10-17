"""
标注数据 Repository 包

标注数据仓库模块，包含标注记录查询、work 状态、对话/事实/伏笔读投影
"""

from __future__ import annotations

from .repository import (
    AnnotationRepository,
    ChapterAnnotationRow,
    CharacterFactRow,
    DialogueFactRow,
    ForeshadowingTreeView,
)
from .rows import (
    AnnotationWorkRow,
    DialogueRecordRow,
    ForeshadowingEdgeRow,
    GraphFactRow,
    SavedAnnotationRecord,
)

__all__ = [
    "AnnotationRepository",
    "AnnotationWorkRow",
    "ChapterAnnotationRow",
    "CharacterFactRow",
    "DialogueFactRow",
    "DialogueRecordRow",
    "ForeshadowingEdgeRow",
    "ForeshadowingTreeView",
    "GraphFactRow",
    "SavedAnnotationRecord",
]
