from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from src.models.local.character_reference_policy import is_global_character_surface_name

ValueLogicType = Literal["善义有价值", "强者为王", "混合型"]
FocusStructureType = Literal["single", "dual", "ensemble"]
GENRE_LABEL_VALUES = ("科幻", "悬疑", "历史", "仙侠", "玄幻", "都市", "通用")
STYLE_LABEL_VALUES = (
    "硬核",
    "史诗",
    "哲思",
    "严肃",
    "黑暗",
    "慢热",
    "高概念",
    "实验性",
    "热血",
    "轻松",
    "寓言性",
    "冷峻",
    "权谋",
    "爽文",
)


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
            "伏笔回收预期。该值由后端 setup thread ledger 确定性计算，"
            "diagnosis LLM 不负责估算；持久化前会用 payload 值收口。"
        ),
    )
    arc_scores: dict[str, float] = Field(default_factory=dict)
    genre_labels: list[str] = Field(default_factory=list)
    style_labels: list[str] = Field(default_factory=list)
    topic_labels: list[str] = Field(default_factory=list)
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

    @field_validator("focus_characters", "main_characters", "core_cast")
    @classmethod
    def validate_character_lists(cls, values: list[str]) -> list[str]:
        """
        修改时间: 2026-04-29
        任务: 角色引用分层重构
        修改原因: diagnosis 正式角色名单只能包含 global-character，未解析代词必须触发重试而不是入库。
        """
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
        """
        修改时间: 2026-04-29
        任务: 角色引用分层重构
        修改原因: arc_scores 是 diagnosis 角色合同源头，不能接收“我/她”等局部引用 key。
        """
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

    @model_validator(mode="after")
    def validate_focus_contract(self) -> CloudAnalysis:
        """
        修改时间: 2026-04-30
        任务: diagnosis-latest-only-reference-contract
        修改原因: diagnosis 正式结果仍然必须满足焦点合同，但不再额外依赖 reference_contract_version
                  这层版本门槛；缺字段时直接按当前结构校验即可。
        """
        # 空云端桩和少量测试辅助对象仍可能构造“全空 diagnosis”，
        # 这里允许这种空对象通过；但只要已经进入正式 diagnosis 结果形态，
        # 就必须显式给出完整 focus contract，不能再靠默认值糊成半成品
        has_formal_diagnosis_payload = any(
            (
                self.foreshadow_expectation is not None,
                bool(self.arc_scores),
                bool(self.genre_labels),
                bool(self.style_labels),
                bool(self.topic_labels),
                self.diagnosis is not None,
                self.value_logic_type is not None,
                self.value_logic_reason is not None,
                self.power_stance_score is not None,
                self.power_stance_reason is not None,
                self.common_people_dignity is not None,
                self.dignity_reason is not None,
                self.cultural_depth_score is not None,
                self.cultural_depth_reason is not None,
                self.narrative_arc_type is not None,
                bool(self.main_characters),
                bool(self.core_cast),
                self.theme_color is not None,
            )
        )

        arc_score_names = set(self.arc_scores.keys())

        for label, values in (
            ("focus_characters", self.focus_characters),
            ("main_characters", self.main_characters),
            ("core_cast", self.core_cast),
        ):
            invalid_names = [name for name in values if name not in arc_score_names]
            if invalid_names:
                raise ValueError(f"{label} contains names missing from arc_scores: {invalid_names}")

        if has_formal_diagnosis_payload:
            if self.focus_structure is None:
                raise ValueError("focus_structure is required for formal diagnosis payload")
            if not self.focus_characters:
                raise ValueError("focus_characters is required for formal diagnosis payload")
            if not self.main_characters:
                raise ValueError("main_characters is required for formal diagnosis payload")
            if not self.core_cast:
                raise ValueError("core_cast is required for formal diagnosis payload")
            if not self.topic_labels:
                raise ValueError("topic_labels is required for formal diagnosis payload")
            if not self.genre_labels:
                raise ValueError("genre_labels is required for formal diagnosis payload")
            if not self.style_labels:
                raise ValueError("style_labels is required for formal diagnosis payload")
            if len(self.main_characters) > 5:
                raise ValueError("main_characters cannot exceed 5 items")
            if len(self.core_cast) > 10:
                raise ValueError("core_cast cannot exceed 10 items")

        if self.focus_structure is None:
            if self.focus_characters:
                raise ValueError("focus_structure is required when focus_characters is not empty")
            return self

        focus_count = len(self.focus_characters)
        expected_count_by_structure = {
            "single": 1,
            "dual": 2,
        }
        if self.focus_structure in expected_count_by_structure:
            expected_count = expected_count_by_structure[self.focus_structure]
            if focus_count != expected_count:
                raise ValueError(
                    f"focus_structure={self.focus_structure} requires exactly {expected_count} focus_characters, "
                    f"got {focus_count}"
                )
        elif self.focus_structure == "ensemble" and focus_count < 3:
            raise ValueError("focus_structure=ensemble requires at least 3 focus_characters")

        return self

    def to_dict(self) -> dict:
        """
        修改时间: 2026-04-30
        任务: diagnosis-latest-only-reference-contract
        修改原因: 诊断结果对外和持久化都改为 latest-only，不再暴露 reference_contract_version。
        """
        return {
            "novel_id": self.novel_id,
            "foreshadow_expectation": self.foreshadow_expectation,
            "arc_scores": dict(self.arc_scores),
            "genre_labels": list(self.genre_labels),
            "style_labels": list(self.style_labels),
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
            "focus_structure": self.focus_structure,
            "focus_characters": list(self.focus_characters),
            "main_characters": list(self.main_characters),
            "core_cast": list(self.core_cast),
            "theme_color": self.theme_color,
        }
