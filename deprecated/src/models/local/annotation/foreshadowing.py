"""
伏笔分析模块

创建时间: 2026-03-18
创建者: TraeAI
任务: code-quality-refactor - Task 8 拆分annotation_client
说明: 提取伏笔分析相关逻辑
"""

from __future__ import annotations

from src.models.local.schema import ChunkAnnotation, ForeshadowingResult


def build_foreshadowing_from_annotation(
    annotation: ChunkAnnotation,
) -> ForeshadowingResult | None:
    """
    从标注结果构建伏笔分析结果

    创建时间: 2026-03-17
    创建者: TraeAI
    任务: code-quality-refactor - 提取伏笔构建逻辑

    修改时间: 2026-03-18
    修改者: TraeAI
    任务: code-quality-refactor - Task 8 拆分annotation_client
    修改内容: 提取为独立模块函数
    """
    if not annotation.has_foreshadowing:
        return None

    return ForeshadowingResult(
        has_foreshadowing=True,
        foreshadowing_type=annotation.foreshadowing_type,
        anchor_text="",
        anchor_reason=annotation.foreshadowing_desc or "",
        confidence="high",
    )
