"""
创建时间: 2026-03-18
创建者: TraeAI
任务: code-quality-refactor - 拆分protocols.py
说明: 协议接口子模块初始化

修改时间: 2026-04-23
任务: P2-基础设施解耦
修改内容: 导出协议语义类型，供调用方逐步替代裸字典和裸结构。
"""

from __future__ import annotations

from .annotation import AnnotationRepositoryProtocol
from .chunk import ChunkRepositoryProtocol
from .diagnosis import DiagnosisRepositoryProtocol
from .run import RunRepositoryProtocol
from .stats import StatsRepositoryProtocol
from .types import (
    AnnotationRecord,
    CharacterDisambigData,
    ChunkCounts,
    ChunkCurveRow,
    ChunkTextRow,
    ChunkTopicWeight,
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
    "CharacterDisambigData",
    "ChunkCounts",
    "ChunkCurveRow",
    "ChunkTextRow",
    "ChunkTopicWeight",
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
