"""
诊断 Agent 局部修正合同
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class CloudAnalysisPatch(BaseModel):
    """2026-08-11 用于 revise_finish 只提交需要修改的字段，未提交字段沿用上一次完整结果"""

    model_config = ConfigDict(extra="forbid")

    arc_scores: dict[str, float] | None = None
    genre_labels: list[str] | None = None
    style_labels: list[str] | None = None
    topic_labels: list[str] | None = None
    diagnosis: str | None = None
    value_logic_type: Literal["善义有价值", "强者为王", "混合型"] | str | None = None
    value_logic_reason: str | None = None
    power_stance_score: int | None = Field(default=None, ge=0, le=5)
    power_stance_reason: str | None = None
    common_people_dignity: int | None = Field(default=None, ge=0, le=5)
    dignity_reason: str | None = None
    cultural_depth_score: int | None = Field(default=None, ge=0, le=5)
    cultural_depth_reason: str | None = None
    narrative_arc_type: str | None = Field(default=None, min_length=1)
    focus_structure: Literal["single", "dual", "ensemble"] | None = None
    focus_characters: list[str] | None = None
    main_characters: list[str] | None = None
    core_cast: list[str] | None = None
    theme_color: str | None = None


__all__ = ["CloudAnalysisPatch"]
