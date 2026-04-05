"""
标注相关常量

创建时间: 2026-03-28
创建者: TraeAI
任务: consolidate-codebase-architecture
说明: 从各模块提取的标注相关硬编码常量
"""

from __future__ import annotations

EMOTION_SCORE_MAPPING: dict[str, int] = {
    "strong_positive": 2,
    "mild_positive": 1,
    "neutral": 0,
    "mild_negative": -1,
    "strong_negative": -2,
}

PHASE_MAX_RETRIES: int = 3
PHASE3_MAX_RETRIES: int = 3
VALIDATION_MAX_RETRIES: int = 3

SYMMETRIC_RELATION_TYPES: frozenset[str] = frozenset({"家族", "友情", "盟友"})

__all__ = [
    "EMOTION_SCORE_MAPPING",
    "PHASE_MAX_RETRIES",
    "PHASE3_MAX_RETRIES",
    "VALIDATION_MAX_RETRIES",
    "SYMMETRIC_RELATION_TYPES",
]
