"""诊断结果 payload 的字段契约

说明: analysis_outputs 里 kind='agent_analysis' 行的字段面——诊断 agent 提交局部修正
（write_diagnosis 的 patch）、落库读写（stats 仓储）与 api 响应模型（DiagnosisResult）共用同一份，
避免字段在两处漂移。完整结果模型（含领域校验）在 src/agents/diagnosis/schema.py。
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class AgentAnalysisPatch(BaseModel):
    """只提交需要修改的字段；未提交字段沿用上一次完整结果。"""

    model_config = ConfigDict(extra="forbid")

    arc_scores: dict[str, float] | None = None
    genre_labels: list[str] | None = None
    style_labels: list[str] | None = None
    topic_labels: dict[str, str] | None = None
    diagnosis: str | None = None
    value_logic_type: Literal["善义有价值", "强者为王", "混合型"] | str | None = None
    value_logic_reason: str | None = None
    power_stance_score: int | None = Field(default=None, ge=0, le=5)
    power_stance_reason: str | None = None
    common_people_dignity: int | None = Field(default=None, ge=0, le=5)
    dignity_reason: str | None = None
    cultural_depth_score: int | None = Field(default=None, ge=0, le=5)
    cultural_depth_reason: str | None = None
    narrative_arc_type: str | None = Field(default=None, min_length=1, max_length=4)
    focus_structure: Literal["single", "dual", "ensemble"] | None = None
    focus_characters: list[str] | None = None
    main_characters: list[str] | None = None
    core_cast: list[str] | None = None
    theme_color: str | None = None


__all__ = ["AgentAnalysisPatch"]
