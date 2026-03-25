from __future__ import annotations

from typing import Dict, List, Literal, Union

from pydantic import BaseModel, ConfigDict, Field, field_validator

ValueLogicType = Literal["善义有价值", "强者为王", "混合型"]


class DisambiguationAliasMap(BaseModel):
    """
    人名消歧响应数据结构

    创建时间: 2026-03-16
    创建者: TraeAI
    任务: 重构云端消歧客户端集成 Instructor
    说明: 用于 Instructor 结构化输出的响应模型
    """

    model_config = ConfigDict(frozen=True)

    alias_map: Dict[str, str] = Field(
        default_factory=dict,
        description="人名到规范名的映射，key 为候选人名，value 为规范名",
    )


class CloudAnalysis(BaseModel):
    """
    云端分析数据结构

    修改时间: 2026-03-16
    修改者: TraeAI
    任务: 迁移数据模型至 Pydantic
    修改内容: 从 dataclass 迁移至 Pydantic BaseModel，使用 field_validator 替代手动验证
    """

    model_config = ConfigDict(frozen=True)

    novel_id: str | None = None
    foreshadow_rate: float | None = Field(default=None, ge=0, le=1)
    arc_scores: Union[List[float], Dict[str, float]] = Field(default_factory=list)
    narrative_type: str | None = None
    topic_labels: List[str] = Field(default_factory=list)
    diagnosis: str | None = None
    value_logic_type: ValueLogicType | str | None = None
    value_logic_reason: str | None = None
    power_stance_score: int | None = Field(default=None, ge=0, le=5)
    power_stance_reason: str | None = None
    common_people_dignity: int | None = Field(default=None, ge=0, le=5)
    dignity_reason: str | None = None
    cultural_depth_score: int | None = Field(default=None, ge=0, le=5)
    cultural_depth_reason: str | None = None
    narrative_arc_type: str | None = None

    @field_validator("value_logic_type")
    @classmethod
    def validate_value_logic_type(cls, v: ValueLogicType | str | None) -> ValueLogicType | str | None:
        if v is not None:
            valid_types = ("善义有价值", "强者为王", "混合型")
            if v not in valid_types:
                raise ValueError(f"value_logic_type must be one of {valid_types}, got: {v}")
        return v

    def to_dict(self) -> dict:
        arc_scores_value: Union[List[float], Dict[str, float]]
        if isinstance(self.arc_scores, dict):
            arc_scores_value = dict(self.arc_scores)
        else:
            arc_scores_value = list(self.arc_scores)

        return {
            "novel_id": self.novel_id,
            "foreshadow_rate": self.foreshadow_rate,
            "arc_scores": arc_scores_value,
            "narrative_type": self.narrative_type,
            "topic_labels": list(self.topic_labels),
            "diagnosis": self.diagnosis,
            "value_logic_type": self.value_logic_type,
            "value_logic_reason": self.value_logic_reason,
            "power_stance_score": self.power_stance_score,
            "power_stance_reason": self.power_stance_reason,
            "common_people_dignity": self.common_people_dignity,
            "dignity_reason": self.dignity_reason,
            "cultural_depth_score": self.cultural_depth_score,
            "cultural_depth_reason": self.cultural_depth_reason,
            "narrative_arc_type": self.narrative_arc_type,
        }
