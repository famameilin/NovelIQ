from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from src.diagnosis.normalization import normalize_character_key, normalize_topic_label_input
from src.diagnosis.vocabulary import GENRE_LABEL_VALUES, STYLE_LABEL_VALUES
from src.event_trees.organization_models import NarrativeOrganization
from src.fact_graph.character_reference_policy import is_global_character_surface_name

ValueLogicType = Literal["善义有价值", "强者为王", "混合型"]
FocusStructureType = Literal["single", "dual", "ensemble"]


class AgentAnalysis(BaseModel):
    """
    小说整体诊断结果：题材与风格标签、价值观与叙事结构评价、角色弧线评分与核心阵容。
    """

    model_config = ConfigDict(frozen=True)

    novel_id: str | None = None
    narrative_organization: NarrativeOrganization | None = Field(
        default=None, description="由本轮全书组织工具草稿收口保存，finish 无需重复提交"
    )
    foreshadow_expectation: float | None = Field(
        default=None,
        ge=0,
        le=1,
        description=(
            "伏笔回收预期。该值由后端伏笔树根属性确定性计算，diagnosis LLM 不负责估算；持久化前会用 payload 值收口。"
        ),
    )
    arc_scores: dict[str, float] = Field(
        default_factory=dict,
        description=(
            "重点角色的弧线评分（0-10）：key 必须是本 run 正式角色的规范名，不是章节/事件/剧情线标题，也不是实体 UUID"
        ),
    )
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
    focus_characters: list[str] = Field(default_factory=list, description="焦点人物：每项必须是本 run 正式角色的规范名")
    main_characters: list[str] = Field(default_factory=list, description="主要人物：每项必须是本 run 正式角色的规范名")
    core_cast: list[str] = Field(default_factory=list, description="核心阵容：每项必须是本 run 正式角色的规范名")
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
                raise ValueError(f"value_logic_type 只能是 {valid_types}，实际 {v}")
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
                raise ValueError(
                    f"genre_labels 不支持标签 {label}；可用值：{'/'.join(GENRE_LABEL_VALUES)}"
                )
            seen.add(label)
            normalized.append(label)
        if len(normalized) > 3:
            raise ValueError("genre_labels 最多 3 项")
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
                raise ValueError(
                    f"style_labels 不支持标签 {label}；可用值：{'/'.join(STYLE_LABEL_VALUES)}"
                )
            seen.add(label)
            normalized.append(label)
        if len(normalized) > 3:
            raise ValueError("style_labels 最多 3 项")
        return normalized

    @field_validator("topic_labels", mode="before")
    @classmethod
    def validate_topic_labels(cls, values: object) -> dict[str, str]:
        return normalize_topic_label_input(values)

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
                raise ValueError(f"diagnosis 角色名单含未解析引用：{name}（须用本 run 正式角色规范名）")
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
                raise ValueError(f"arc_scores 含未解析引用：{name}（须用本 run 正式角色规范名）")
            score = float(raw_score)
            normalized[name] = score
        return normalized

    def to_dict(self) -> dict:
        """转换为对外和持久化使用的当前结构"""
        return {
            "novel_id": self.novel_id,
            "narrative_organization": self.narrative_organization.model_dump(mode="json")
            if self.narrative_organization is not None
            else None,
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


class AgentAnalysisSubmission(AgentAnalysis):
    """报告写入面：拒绝未声明字段并执行提示词承诺的硬校验"""

    model_config = ConfigDict(frozen=True, extra="forbid")

    @field_validator("theme_color", mode="before")
    @classmethod
    def reject_invalid_theme_color(cls, v: object) -> object:
        if v is None:
            return v
        if not isinstance(v, str) or not re.match(r"^#([0-9A-Fa-f]{6}|[0-9A-Fa-f]{3})$", v.strip()):
            raise ValueError("theme_color 必须是 #RRGGBB 或 #RGB 十六进制颜色")
        return v

    @field_validator("narrative_arc_type")
    @classmethod
    def reject_empty_arc_type(cls, v: str | None) -> str | None:
        if v is not None and not v.strip():
            raise ValueError("narrative_arc_type 不能为空字符串")
        return v

    @field_validator("arc_scores", mode="before")
    @classmethod
    def reject_equivalent_score_keys(cls, values: object) -> object:
        """原始键在基础规范化前先查等价重复"""
        if isinstance(values, dict):
            seen: dict[str, str] = {}
            for name in values:
                if not isinstance(name, str):
                    continue
                key = normalize_character_key(name)
                if key in seen:
                    raise ValueError(f"arc_scores 包含等价重复角色: {seen[key]} / {name}")
                seen[key] = name
        return values

    @field_validator("arc_scores")
    @classmethod
    def validate_arc_scores_strict(cls, values: dict[str, float]) -> dict[str, float]:
        seen: dict[str, str] = {}
        for name, score in values.items():
            key = normalize_character_key(name)
            if key in seen:
                raise ValueError(f"arc_scores 包含等价重复角色: {seen[key]} / {name}")
            seen[key] = name
            if not 0 <= score <= 10:
                raise ValueError(f"arc_scores[{name}] 必须在 0–10 之间")
        return values

    @field_validator("focus_characters", "main_characters", "core_cast", mode="before")
    @classmethod
    def reject_equivalent_raw_role_names(cls, values: object) -> object:
        """原始名单在基础规范化前先查等价重复"""
        if isinstance(values, list):
            seen: dict[str, str] = {}
            for name in values:
                if not isinstance(name, str):
                    continue
                key = normalize_character_key(name)
                if key in seen:
                    raise ValueError(f"角色名单包含等价重复: {seen[key]} / {name}")
                seen[key] = name
        return values

    @field_validator("focus_characters", "main_characters", "core_cast")
    @classmethod
    def reject_equivalent_role_names(cls, values: list[str]) -> list[str]:
        seen: dict[str, str] = {}
        for name in values:
            key = normalize_character_key(name)
            if key in seen:
                raise ValueError(f"角色名单包含等价重复: {seen[key]} / {name}")
            seen[key] = name
        return values
