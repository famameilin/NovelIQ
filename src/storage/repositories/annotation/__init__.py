"""
标注数据 Repository 包

标注数据仓库模块，包含标注插入、查询、角色操作等
"""

from __future__ import annotations

from .continuity import (
    CasePoolRepository,
    CaseResolutionMappingRepository,
    ChapterAnnotationRepository,
    ContinuityFactRepository,
    DatabaseAnnotationQueryService,
    ForeshadowingRepository,
)
from .repository import (
    AnnotationRepository,
    CharacterFactRow,
    ChunkAnnotationRow,
    DialogueFactRow,
    ForeshadowingThreadView,
)

__all__ = [
    "AnnotationRepository",
    "CharacterFactRow",
    "ChunkAnnotationRow",
    "DialogueFactRow",
    "ForeshadowingThreadView",
    "CasePoolRepository",
    "CaseResolutionMappingRepository",
    "ChapterAnnotationRepository",
    "ContinuityFactRepository",
    "DatabaseAnnotationQueryService",
    "ForeshadowingRepository",
]
