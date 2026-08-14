"""
标注相关常量

说明: 保留仍被业务代码消费的常量；旧合同残留（角色词/实体类型/变化类型等）
已由 src.agents.annotation.schema 的闭合枚举承载，不再维护副本
"""

from __future__ import annotations

EMOTION_SCORE_MAPPING: dict[str, int] = {
    "strong_positive": 2,
    "mild_positive": 1,
    "neutral": 0,
    "mild_negative": -1,
    "strong_negative": -2,
}

__all__ = [
    "EMOTION_SCORE_MAPPING",
]
