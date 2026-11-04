"""事件工具的实体引用、字段纠错与规范化输入"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from src.event_trees.vocabulary import (
    _EVENT_ONLY_ROLE_WORDS,
    EMOTION_SCORE_DESCRIPTION,
    EVENT_ROLE_FIELD_HINT,
    PERSON_ROLE_FIELD_HINT,
    Confidence,
    EventParticipantRole,
    RoleFunction,
    clamp_emotion_score,
    normalize_event_participant_role,
    normalize_role_function,
)
from src.fact_graph.inputs import EntityNameRef
from src.fact_graph.vocabulary import _TONE_CHINESE_WORDS
from src.text_processing.normalize import normalize_semantic_text


def _enum_values_text(enum_cls: type[StrEnum]) -> str:
    """用于把枚举成员渲染成取值域文本（提示词与回执的取值同取枚举，不手抄）"""
    return "、".join(str(member.value) for member in enum_cls)


class ParticipantArg(EntityNameRef):
    """事件的一个参与者（write_event.characters 数组元素）

    role 可省略或写偏，缺省按实体登记类型取；character 条目的
    narrative_role/action/emotion 必填，叙事功能同义词归一、情绪分值钳制，
    拒绝面只留字段误用（事件角色词写进叙事功能、语气词写进情绪分值）。
    """

    role: EventParticipantRole | None = Field(
        default=None,
        description=(
            f"参与角色：{EVENT_ROLE_FIELD_HINT}；取 {_enum_values_text(EventParticipantRole)}"
            "（地点角色用于 location 或 organization 实体）；可省略，缺省按实体登记类型取"
            "（character→主体、location→地点、其余→客体）"
        ),
    )
    narrative_role: RoleFunction | None = Field(
        default=None,
        description=(
            f"character 参与者必填的人物叙事功能（{PERSON_ROLE_FIELD_HINT}）："
            f"{_enum_values_text(RoleFunction)}；近义词自动归一"
        ),
    )
    action: str | None = Field(
        default=None,
        min_length=1,
        description="character 参与者必填的一句话动作概括（不超过 15 字）",
    )
    emotion: int | None = Field(
        default=None,
        ge=-2,
        le=2,
        description=f"character 参与者必填的动作伴随情绪分值。{EMOTION_SCORE_DESCRIPTION}",
    )

    @field_validator("role", mode="before")
    @classmethod
    def _normalize_role(cls, value: object) -> object:
        """用于把参与角色词归一到闭集（缺省/未收录交生产面按实体类型给默认）"""
        return normalize_event_participant_role(value)

    @field_validator("narrative_role", mode="before")
    @classmethod
    def _reject_event_role_words(cls, value: object) -> object:
        """用于阻止事件专属角色词进入人物功能字段，其余近义词归一（含未收录收敛为主体）"""
        if isinstance(value, str) and value.strip() in _EVENT_ONLY_ROLE_WORDS:
            raise ValueError(
                "narrative_role 不接受 "
                f"{value.strip()}：地点、行动者等只用于事件参与者的 role 字段；"
                "人物功能使用 主体/客体/发送者/接收者/帮助者/反对者/见证者"
            )
        return normalize_role_function(value)

    @field_validator("emotion", mode="before")
    @classmethod
    def _reject_tone_words_in_emotion(cls, value: object) -> object:
        """用于阻止对话语气词进入人物情绪分值字段（语气词指引保留，数值越界改钳制）"""
        if isinstance(value, str) and value.strip() in _TONE_CHINESE_WORDS:
            raise ValueError(
                f"emotion 不接受 {value.strip()}：该字段是整数分值 -2..2"
                "（-2 强烈负面 … 2 强烈正面），语气词是对话 tone 字段的取值"
            )
        return clamp_emotion_score(value)

    @model_validator(mode="after")
    def normalize_participant(self) -> ParticipantArg:
        """用于规范化动作文本（三态字段允许任意缺省，不再做齐套校验）"""
        if self.action is not None:
            self.action = normalize_semantic_text(self.action, label="characters[].action")
        return self


class AnnotationEventItem(BaseModel):
    """标注事件的单项写入参数，证据使用本章段首可见号"""

    model_config = ConfigDict(extra="forbid")

    el: str
    title: str
    problem: str
    summary: str
    event_type: str
    status: str
    evidence: int
    progress: str | None = None
    from_chapter_id: int | None = None
    to_chapter_id: int | None = None
    reason: str | None = None
    isforeshadowing: bool = False
    confidence: Confidence | None = None
    characters: list[ParticipantArg] | None = None
