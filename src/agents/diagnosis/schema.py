from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from src.config.constants.diagnosis import GENRE_LABEL_VALUES, STYLE_LABEL_VALUES
from src.utils.character_reference_policy import is_global_character_surface_name

ValueLogicType = Literal["善义有价值", "强者为王", "混合型"]
FocusStructureType = Literal["single", "dual", "ensemble"]
class CloudAnalysis(BaseModel):
    """
    云端分析数据结构

    说明: 从 dataclass 迁移至 Pydantic BaseModel，使用 field_validator 替代手动验证
    """

    model_config = ConfigDict(frozen=True)

    novel_id: str | None = None
    foreshadow_expectation: float | None = Field(
        default=None,
        ge=0,
        le=1,
        description=(
            "伏笔回收预期。该值由后端伏笔树根属性确定性计算，"
            "diagnosis LLM 不负责估算；持久化前会用 payload 值收口。"
        ),
    )
    arc_scores: dict[str, float] = Field(default_factory=dict)
    genre_labels: list[str] = Field(default_factory=list)
    style_labels: list[str] = Field(default_factory=list)
    # 标签必须与本轮模型的实际 topic_id 一一对应
    topic_labels: dict[str, str] = Field(default_factory=dict)
    diagnosis: str | None = None
    value_logic_type: ValueLogicType | str | None = None
    value_logic_reason: str | None = None
    power_stance_score: int | None = Field(default=None, ge=0, le=5)
    power_stance_reason: str | None = None
    common_people_dignity: int | None = Field(default=None, ge=0, le=5)
    dignity_reason: str | None = None
    cultural_depth_score: int | None = Field(default=None, ge=0, le=5)
    cultural_depth_reason: str | None = None
    narrative_arc_type: str | None = Field(
        default=None,
        max_length=4,
        description="叙事弧类型短标签，4 字以内（如 三幕式/英雄之旅）；不写句子、不写箭头链",
    )
    focus_structure: FocusStructureType | None = None
    focus_characters: list[str] = Field(default_factory=list)
    main_characters: list[str] = Field(default_factory=list)
    core_cast: list[str] = Field(default_factory=list)
    theme_color: str | None = Field(
        default=None,
        description="小说主题色，十六进制格式，如 #4A90D9",
    )

    @field_validator("theme_color")
    @classmethod
    def validate_theme_color(cls, v: str | None) -> str | None:
        if v is None:
            return v
        # 去除首尾空白
        v = v.strip()
        # 校验十六进制格式 (#RRGGBB 或 #RGB)
        import re

        if not re.match(r"^#([0-9A-Fa-f]{6}|[0-9A-Fa-f]{3})$", v):
            return None  # 非法格式返回 None，由前端兜底
        return v

    @field_validator("value_logic_type")
    @classmethod
    def validate_value_logic_type(cls, v: ValueLogicType | str | None) -> ValueLogicType | str | None:
        if v is not None:
            valid_types = ("善义有价值", "强者为王", "混合型")
            if v not in valid_types:
                raise ValueError(f"value_logic_type must be one of {valid_types}, got: {v}")
        return v

    @field_validator("genre_labels")
    @classmethod
    def validate_genre_labels(cls, values: list[str]) -> list[str]:
        normalized: list[str] = []
        seen: set[str] = set()
        for value in values:
            label = value.strip()
            if not label or label in seen:
                continue
            if label not in GENRE_LABEL_VALUES:
                raise ValueError(f"genre_labels contains unsupported label: {label}")
            seen.add(label)
            normalized.append(label)
        if len(normalized) > 3:
            raise ValueError("genre_labels cannot exceed 3 items")
        return normalized

    @field_validator("style_labels")
    @classmethod
    def validate_style_labels(cls, values: list[str]) -> list[str]:
        normalized: list[str] = []
        seen: set[str] = set()
        for value in values:
            label = value.strip()
            if not label or label in seen:
                continue
            if label not in STYLE_LABEL_VALUES:
                raise ValueError(f"style_labels contains unsupported label: {label}")
            seen.add(label)
            normalized.append(label)
        if len(normalized) > 3:
            raise ValueError("style_labels cannot exceed 3 items")
        return normalized

    @field_validator("topic_labels")
    @classmethod
    def validate_topic_labels(cls, values: dict[str, str]) -> dict[str, str]:
        normalized: dict[str, str] = {}
        for raw_id, raw_label in values.items():
            topic_id = str(raw_id)
            label = raw_label.strip()
            if not topic_id.isdecimal() or not label:
                raise ValueError("topic_labels must map non-negative topic IDs to non-empty labels")
            normalized[str(int(topic_id))] = label
        return normalized

    @field_validator("focus_characters", "main_characters", "core_cast")
    @classmethod
    def validate_character_lists(cls, values: list[str]) -> list[str]:
        """校验正式角色名单只包含可进入主链的全局角色"""
        normalized: list[str] = []
        seen: set[str] = set()
        for value in values:
            name = value.strip()
            if not name or name in seen:
                continue
            if not is_global_character_surface_name(name):
                raise ValueError(f"diagnosis character list contains unresolved reference: {name}")
            seen.add(name)
            normalized.append(name)
        return normalized

    @field_validator("arc_scores")
    @classmethod
    def validate_arc_scores(cls, values: dict[str, float]) -> dict[str, float]:
        """校验角色弧线分数只使用全局角色名"""
        normalized: dict[str, float] = {}
        for raw_name, raw_score in values.items():
            name = raw_name.strip()
            if not name:
                continue
            if not is_global_character_surface_name(name):
                raise ValueError(f"arc_scores contains unresolved reference: {name}")
            score = float(raw_score)
            normalized[name] = score
        return normalized

    def to_dict(self) -> dict:
        """转换为对外和持久化使用的当前结构"""
        return {
            "novel_id": self.novel_id,
            "foreshadow_expectation": self.foreshadow_expectation,
            "arc_scores": dict(self.arc_scores),
            "genre_labels": list(self.genre_labels),
            "style_labels": list(self.style_labels),
            "topic_labels": self.topic_labels.copy(),
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
            "focus_structure": self.focus_structure,
            "focus_characters": list(self.focus_characters),
            "main_characters": list(self.main_characters),
            "core_cast": list(self.core_cast),
            "theme_color": self.theme_color,
        }
