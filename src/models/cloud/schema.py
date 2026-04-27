from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

ValueLogicType = Literal["善义有价值", "强者为王", "混合型"]
FocusStructureType = Literal["single", "dual", "ensemble"]


class DisambiguationAliasMap(BaseModel):
    """
    人名消歧响应数据结构

    创建时间: 2026-03-16
    创建者: TraeAI
    任务: 重构云端消歧客户端集成 Instructor
    说明: 用于 Instructor 结构化输出的响应模型

    修改时间: 2026-03-27
    修改者: TraeAI
    任务: 简化消歧响应模型
    修改内容: 将 merge_target_map 重命名为 alias_map
    """

    model_config = ConfigDict(frozen=True)

    alias_map: dict[str, str] = Field(
        default_factory=dict,
        description="人名到规范名的映射，key 为候选人名，value 为规范名",
    )


class CloudAnalysis(BaseModel):
    """
    云端分析数据结构

    创建时间: 2026-03-16
    创建者: TraeAI
    任务: 迁移数据模型至 Pydantic
    说明: 从 dataclass 迁移至 Pydantic BaseModel，使用 field_validator 替代手动验证

    修改时间: 2026-04-26
    修改者: Codex
    任务: remove-foreshadow-rate-contract
    修改内容: 移除旧 `foreshadow_rate` 兼容字段，统一改为 `foreshadow_expectation`
    单一合同，并承接 diagnosis 阶段对 setup ledger 的正式消费。

    修改时间: 2026-04-27
    修改者: Codex
    任务: protagonist-focus-contract
    修改内容: 废弃单主角合同，新增 `focus_structure` / `focus_characters`，
    并对焦点结构与人物名单一致性做严格校验。
    """

    model_config = ConfigDict(frozen=True)

    novel_id: str | None = None
    foreshadow_expectation: float | None = Field(
        default=None,
        ge=0,
        le=1,
        description=(
            "伏笔回收预期。该值在 diagnosis 阶段基于 setup thread ledger 语义生成，"
            "并作为对外与持久化的单一正式字段。"
        ),
    )
    arc_scores: dict[str, float] = Field(default_factory=dict)
    narrative_type: str | None = None
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

    @field_validator("focus_characters", "main_characters", "core_cast")
    @classmethod
    def validate_character_lists(cls, values: list[str]) -> list[str]:
        """
        修改时间: 2026-04-27
        修改者: Codex
        任务: protagonist-focus-contract
        修改原因: 焦点人物、主要人物、核心角色现在都是正式结构化合同；
        这里统一去除空白名并保留原顺序，避免后续落库和页面展示继续吞脏值。
        """
        normalized: list[str] = []
        seen: set[str] = set()
        for value in values:
            name = value.strip()
            if not name or name in seen:
                continue
            seen.add(name)
            normalized.append(name)
        return normalized

    @field_validator("arc_scores")
    @classmethod
    def validate_arc_scores(cls, values: dict[str, float]) -> dict[str, float]:
        """
        修改时间: 2026-04-27
        修改者: Codex
        任务: protagonist-focus-contract
        修改原因: 新合同不再接受匿名数组形态的弧线分；所有分数都必须是
        `人物名 -> 分数` 的命名字典，供焦点合同和前端统一消费。
        """
        normalized: dict[str, float] = {}
        for raw_name, raw_score in values.items():
            name = raw_name.strip()
            if not name:
                continue
            score = float(raw_score)
            normalized[name] = score
        return normalized

    @model_validator(mode="after")
    def validate_focus_contract(self) -> CloudAnalysis:
        """
        修改时间: 2026-04-27
        修改者: Codex
        任务: protagonist-focus-contract
        修改原因: diagnosis 结果现在允许 single / dual / ensemble，
        必须在模型层阻止“结构标签”和“人物列表”彼此矛盾的脏结果进入数据库。
        """
        arc_score_names = set(self.arc_scores.keys())

        for label, values in (
            ("focus_characters", self.focus_characters),
            ("main_characters", self.main_characters),
            ("core_cast", self.core_cast),
        ):
            invalid_names = [name for name in values if name not in arc_score_names]
            if invalid_names:
                raise ValueError(f"{label} contains names missing from arc_scores: {invalid_names}")

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
        return {
            "novel_id": self.novel_id,
            "foreshadow_expectation": self.foreshadow_expectation,
            "arc_scores": dict(self.arc_scores),
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
            "focus_structure": self.focus_structure,
            "focus_characters": list(self.focus_characters),
            "main_characters": list(self.main_characters),
            "core_cast": list(self.core_cast),
            "theme_color": self.theme_color,
        }
