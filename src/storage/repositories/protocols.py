"""
Repository 协议接口定义

将协议接口拆分到子模块

同步导出 AnnotationRepositoryProtocol，避免兼容入口遗漏协议类型
"""

from __future__ import annotations

from .protocols import (
    AnnotationRepositoryProtocol,
    DiagnosisRepositoryProtocol,
    RunRepositoryProtocol,
    StatsRepositoryProtocol,
)

__all__ = [
    "AnnotationRepositoryProtocol",
    "DiagnosisRepositoryProtocol",
    "RunRepositoryProtocol",
    "StatsRepositoryProtocol",
]
