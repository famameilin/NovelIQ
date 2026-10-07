"""
事件域模型：事件参与者的提交与绑定形态、事件树节点、章级绑定结果

说明: 引用事件值域（本包 vocabulary）与事实图侧共享件（StrictModel、实体引用、
人物功能/情绪/伏笔值域）拼出章级产物；事实图反而不引用本模块，两侧单向。

类 docstring 会进模型可见面，一律按"说明"写——这是什么字段、能取哪些值、怎么判。
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import Field, field_validator, model_validator

from src.event_trees.vocabulary import (
    _EVENT_ONLY_ROLE_WORDS,
    EventCauseRole,
    EventParticipantRole,
    normalize_event_participant_role,
)
from src.fact_graph.schema import (
    EMOTION_SCORE_DESCRIPTION,
    EVENT_ROLE_FIELD_HINT,
    PERSON_ROLE_FIELD_HINT,
    EntityRef,
    StrictModel,
    entity_ref_field_description,
    normalize_semantic_text,
)
from src.fact_graph.vocabulary import (
    _TONE_CHINESE_WORDS,
    Confidence,
    RoleFunction,
    clamp_emotion_score,
    normalize_role_function,
)


def _enum_values_text(enum_cls: type[StrEnum]) -> str:
    """用于把枚举成员渲染成取值域文本（提示词与回执的取值同取枚举，不手抄）"""
    return "、".join(str(member.value) for member in enum_cls)


class EventParticipantInput(StrictModel):
    """2026-08-30 用于同时描述事件参与角色和人物动态状态（内部系统形态，实体=规范名）

    2026-09-13 小调用改造后只保留内部形态；2026-09-14 模型面参与记录由
    write_event 的 characters 数组提交（ParticipantArg），服务端在写入点把
    实体引用翻成规范名并组装成本形态。
    """

    entity: str = Field(
        min_length=1,
        description="参与者实体名称，必须是图上已登记实体名（不是 name 字段）",
    )
    role: EventParticipantRole = Field(
        description="参与角色：主体/客体/接收者/帮助者/反对者/见证者/地点（地点作为参与者角色）"
    )
    narrative_role: RoleFunction | None = Field(
        default=None,
        description="仅 character 参与者必填的人物叙事功能：主体/客体/发送者/接收者/帮助者/反对者/见证者",
    )
    action: str | None = Field(
        default=None,
        min_length=1,
        description="仅 character 参与者必填：一句话概括人物在本事件中的动作（不超过 15 字）",
    )
    emotion: int | None = Field(
        default=None,
        ge=-2,
        le=2,
        description=f"仅 character 参与者必填：动作伴随的情绪分值。{EMOTION_SCORE_DESCRIPTION}",
    )

    @field_validator("narrative_role", mode="before")
    @classmethod
    def _reject_event_role_words(cls, value: object) -> object:
        """2026-08-30 用于阻止事件专属角色词进入人物功能字段"""
        if isinstance(value, str) and value.strip() in _EVENT_ONLY_ROLE_WORDS:
            raise ValueError(
                "narrative_role 不接受 "
                f"{value.strip()}：地点、行动者等只用于事件参与者的 role 字段；"
                "人物功能使用 主体/客体/发送者/接收者/帮助者/反对者/见证者"
            )
        return value

    @field_validator("emotion", mode="before")
    @classmethod
    def _reject_tone_words_in_emotion(cls, value: object) -> object:
        """2026-08-30 用于阻止对话语气词进入人物情绪分值字段"""
        if isinstance(value, str) and value.strip() in _TONE_CHINESE_WORDS:
            raise ValueError(
                f"emotion 不接受 {value.strip()}：该字段是整数分值 -2..2"
                "（-2 强烈负面 … 2 强烈正面），语气词是对话 tone 字段的取值"
            )
        return value

    @model_validator(mode="after")
    def normalize_participant(self) -> EventParticipantInput:
        """用于规范化参与者（2026-10-04 起三态字段允许任意缺省，不再成组约束）"""
        self.entity = normalize_semantic_text(self.entity, label="event.participant.entity")
        if self.action is not None:
            self.action = normalize_semantic_text(self.action, label="event.participant.action")
        return self


class ParticipantArg(StrictModel):
    """事件的一个参与者（write_event.characters 数组元素）

    2026-10-04 合同放开：role/narrative_role/action/emotion 均可省略或写偏——缺省值
    与归一在解析层完成（role 按实体登记类型默认、叙事功能同义词归一、情绪分值钳制），
    拒绝面只留字段误用（事件角色词写进叙事功能、语气词写进情绪分值）。
    """

    entityid: EntityRef = Field(description=entity_ref_field_description("参与者实体引用"))
    role: EventParticipantRole | None = Field(
        default=None,
        description=(
            f"参与角色：{EVENT_ROLE_FIELD_HINT}；取 {_enum_values_text(EventParticipantRole)}"
            "（地点角色只用于 location 实体）；可省略，缺省按实体登记类型取"
            "（character→主体、location→地点、其余→客体）"
        ),
    )
    narrative_role: RoleFunction | None = Field(
        default=None,
        description=(
            f"character 参与者的人物叙事功能（{PERSON_ROLE_FIELD_HINT}）："
            f"{_enum_values_text(RoleFunction)}；可省略，近义词自动归一"
        ),
    )
    action: str | None = Field(
        default=None,
        min_length=1,
        description="character 参与者的一句话动作概括（不超过 15 字）；可省略",
    )
    emotion: int | None = Field(
        default=None,
        ge=-2,
        le=2,
        description=f"character 参与者动作伴随的情绪分值，可省略。{EMOTION_SCORE_DESCRIPTION}",
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


class BoundEvent(StrictModel):
    """事件树节点：服务端生成稳定 ID，正式提交绑定本章段落证据"""

    node_id: str = Field(min_length=1, description="服务端派生的节点 id（=落库 event_id）")
    tree_id: str = Field(min_length=1)
    parent_node_id: str | None = Field(default=None, description="root 为 None")
    cause_role: EventCauseRole
    description: str = Field(min_length=1)
    evidence_paragraph_id: int | None = Field(default=None, ge=0, description="事件所在段的全局段落 ID")
    participants: list[EventParticipantInput] = Field(default_factory=list)
    is_foreshadow_setup: bool = False
    # 2026-09-13 伏笔入森林：根事件携带伏笔属性（落库到 event_nodes 根列）
    payoff_likelihood: Confidence | None = None


__all__ = [
    "BoundEvent",
    "EventParticipantInput",
    "ParticipantArg",
]
