"""
伏笔解析模块

创建时间: 2026-03-18
创建者: TraeAI
任务: code-quality-refactor - Task 9 拆分parser.py
说明: 提取伏笔解析相关逻辑
"""

from __future__ import annotations

from typing import Any

from ..schema import ForeshadowingConfidence, ForeshadowingResult, ForeshadowingType


def parse_foreshadowing_result(data: dict[str, Any]) -> ForeshadowingResult:
    """
    解析伏笔分析结果

    创建时间: 2026-03-14
    创建者: TraeAI
    任务: Chunk 双次调用分析拆分
    """
    has_foreshadowing = data.get("has_foreshadowing", False)

    foreshadowing_type_raw = data.get("foreshadowing_type")
    valid_foreshadowing_types = ["causal", "thematic"]
    if has_foreshadowing and foreshadowing_type_raw in valid_foreshadowing_types:
        foreshadowing_type: ForeshadowingType | None = foreshadowing_type_raw
    else:
        foreshadowing_type = None

    confidence_raw = data.get("confidence", "high")
    valid_confidences = ["high", "medium", "low"]
    confidence: ForeshadowingConfidence = confidence_raw if confidence_raw in valid_confidences else "high"

    return ForeshadowingResult(
        has_foreshadowing=has_foreshadowing,
        foreshadowing_type=foreshadowing_type,
        anchor_text=data.get("anchor_text", ""),
        anchor_reason=data.get("anchor_reason", ""),
        confidence=confidence,
    )


def validate_foreshadowing_result(result: ForeshadowingResult, chunk_text: str) -> bool:
    """
    硬校验：anchor_text 必须是原文的真实子串。

    创建时间: 2026-03-14
    创建者: TraeAI
    任务: Chunk 双次调用分析拆分

    返回 False 则丢弃该条记录，不入库。
    """
    if not result.has_foreshadowing:
        return True

    if result.confidence == "low":
        return False

    if not result.anchor_text or len(result.anchor_text.strip()) < 5:
        return False

    if result.anchor_text not in chunk_text:
        return False

    return True
