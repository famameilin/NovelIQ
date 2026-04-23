"""
创建时间: 2026-03-12
创建者: TraeAI
任务: refactor-model-interaction-layer
说明: Repository 协议接口定义

修改时间: 2026-03-18
修改者: TraeAI
任务: code-quality-refactor - 拆分protocols.py
修改内容: 将协议接口拆分到子模块

修改时间: 2026-04-23
任务: P2-基础设施解耦
修改内容: 同步导出 AnnotationRepositoryProtocol，避免兼容入口遗漏协议类型。
"""

from __future__ import annotations

from .protocols import (
    AnnotationRepositoryProtocol,
    ChunkRepositoryProtocol,
    DiagnosisRepositoryProtocol,
    RunRepositoryProtocol,
    StatsRepositoryProtocol,
)

__all__ = [
    "AnnotationRepositoryProtocol",
    "ChunkRepositoryProtocol",
    "DiagnosisRepositoryProtocol",
    "RunRepositoryProtocol",
    "StatsRepositoryProtocol",
]
