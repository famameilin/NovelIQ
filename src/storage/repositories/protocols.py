"""
创建时间: 2026-03-12
创建者: TraeAI
任务: refactor-model-interaction-layer
说明: Repository 协议接口定义

修改时间: 2026-03-18
修改者: TraeAI
任务: code-quality-refactor - 拆分protocols.py
修改内容: 将协议接口拆分到子模块
"""

from __future__ import annotations

from .protocols import (
    ChunkRepositoryProtocol,
    DiagnosisRepositoryProtocol,
    EntityRepositoryProtocol,
    RunRepositoryProtocol,
    StatsRepositoryProtocol,
)

__all__ = [
    "ChunkRepositoryProtocol",
    "DiagnosisRepositoryProtocol",
    "EntityRepositoryProtocol",
    "RunRepositoryProtocol",
    "StatsRepositoryProtocol",
]
