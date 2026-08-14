"""
协议接口子模块初始化

导出协议语义类型，供调用方逐步替代裸字典和裸结构
"""

from __future__ import annotations

from .annotation import AnnotationRepositoryProtocol
from .chunk import ChunkRepositoryProtocol
from .diagnosis import DiagnosisRepositoryProtocol
from .run import RunRepositoryProtocol
from .stats import StatsRepositoryProtocol
from .types import (
    AnnotationRecord,
    ChunkCounts,
    ChunkCurveRow,
    ChunkTextRow,
    CloudAnalysisRecord,
    ForeshadowingChunk,
    GlobalContextRecord,
    GlobalStatValue,
    HighTensionChunk,
    PivotBlock,
    PivotMoment,
    RelationChangeRow,
    RepositoryRecord,
    RepositoryScalar,
    RepositoryValue,
    RunRecord,
    TokenUsageStatsRecord,
)

__all__ = [
    "AnnotationRepositoryProtocol",
    "ChunkRepositoryProtocol",
    "DiagnosisRepositoryProtocol",
    "RunRepositoryProtocol",
    "StatsRepositoryProtocol",
    "AnnotationRecord",
    "ChunkCounts",
    "ChunkCurveRow",
    "ChunkTextRow",
    "CloudAnalysisRecord",
    "ForeshadowingChunk",
    "GlobalContextRecord",
    "GlobalStatValue",
    "HighTensionChunk",
    "PivotBlock",
    "PivotMoment",
    "RelationChangeRow",
    "RepositoryRecord",
    "RepositoryScalar",
    "RepositoryValue",
    "RunRecord",
    "TokenUsageStatsRecord",
]
