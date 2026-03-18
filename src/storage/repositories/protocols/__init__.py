"""
创建时间: 2026-03-18
创建者: TraeAI
任务: code-quality-refactor - 拆分protocols.py
说明: 协议接口子模块初始化
"""

from __future__ import annotations

from .annotation import AnnotationRepositoryProtocol
from .chunk import ChunkRepositoryProtocol
from .diagnosis import DiagnosisRepositoryProtocol
from .entity import EntityRepositoryProtocol
from .run import RunRepositoryProtocol
from .stats import StatsRepositoryProtocol

__all__ = [
    "AnnotationRepositoryProtocol",
    "ChunkRepositoryProtocol",
    "DiagnosisRepositoryProtocol",
    "EntityRepositoryProtocol",
    "RunRepositoryProtocol",
    "StatsRepositoryProtocol",
]
