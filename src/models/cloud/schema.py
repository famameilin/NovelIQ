from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Literal, Union

ValueLogicType = Literal["善义有价值", "强者为王", "混合型"]


@dataclass(frozen=True)
class CloudAnalysis:
    novel_id: str | None
    foreshadow_rate: float | None
    arc_scores: Union[List[float], Dict[str, float]] = field(default_factory=list)
    narrative_type: str | None = None
    topic_labels: List[str] = field(default_factory=list)
    diagnosis: str | None = None
    value_logic_type: ValueLogicType | str | None = None
    value_logic_reason: str | None = None
    power_stance_score: int | None = None
    power_stance_reason: str | None = None
    common_people_dignity: int | None = None
    dignity_reason: str | None = None
    cultural_depth_score: int | None = None
    cultural_depth_reason: str | None = None
    emotion_curve_type: str | None = None

    def validate(self) -> None:
        if self.foreshadow_rate is not None:
            if self.foreshadow_rate < 0 or self.foreshadow_rate > 1:
                raise ValueError("foreshadow_rate out of range")
        if self.power_stance_score is not None:
            if not isinstance(self.power_stance_score, int):
                raise ValueError("power_stance_score must be int")
            if self.power_stance_score < 0 or self.power_stance_score > 5:
                raise ValueError("power_stance_score out of range")
        if self.common_people_dignity is not None:
            if not isinstance(self.common_people_dignity, int):
                raise ValueError("common_people_dignity must be int")
            if self.common_people_dignity < 0 or self.common_people_dignity > 5:
                raise ValueError("common_people_dignity out of range")
        if self.cultural_depth_score is not None:
            if not isinstance(self.cultural_depth_score, int):
                raise ValueError("cultural_depth_score must be int")
            if self.cultural_depth_score < 0 or self.cultural_depth_score > 5:
                raise ValueError("cultural_depth_score out of range")
        if self.value_logic_type is not None:
            valid_types = ("善义有价值", "强者为王", "混合型")
            if self.value_logic_type not in valid_types:
                raise ValueError(f"value_logic_type must be one of {valid_types}, got: {self.value_logic_type}")

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
            "emotion_curve_type": self.emotion_curve_type,
        }
