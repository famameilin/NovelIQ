"""事件参与状态与章级事件结果"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from src.event_trees.vocabulary import (
    _EVENT_ONLY_ROLE_WORDS,
    EMOTION_SCORE_DESCRIPTION,
    Confidence,
    EventCauseRole,
    EventParticipantRole,
    RoleFunction,
)
from src.text_processing.normalize import normalize_semantic_text


class StrictModel(BaseModel):
    "事件模型拒绝额外字段"

    model_config = ConfigDict(extra="forbid", use_enum_values=True)


class EventParticipantInput(StrictModel):
    """同时描述事件参与角色和人物动态状态（内部系统形态，实体=规范名）

    模型面参与记录由 write_event 的 characters 数组提交（ParticipantArg），
    服务端在写入点把实体引用翻成规范名并组装成本形态。
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
        """阻止事件专属角色词进入人物功能字段"""
        if isinstance(value, str) and value.strip() in _EVENT_ONLY_ROLE_WORDS:
            raise ValueError(
                "narrative_role 不接受 "
                f"{value.strip()}：地点、行动者等只用于事件参与者的 role 字段；"
                "人物功能使用 主体/客体/发送者/接收者/帮助者/反对者/见证者"
            )
        return value


    @model_validator(mode="after")
    def normalize_participant(self) -> EventParticipantInput:
        """用于规范化参与者（三态字段允许任意缺省，不再成组约束）"""
        self.entity = normalize_semantic_text(self.entity, label="event.participant.entity")
        if self.action is not None:
            self.action = normalize_semantic_text(self.action, label="event.participant.action")
        return self




class BoundEvent(StrictModel):
    """不可变章级事件，来源键不表示包含结构或调用顺序"""

    event_id: str = Field(min_length=1)
    from_chapter_id: int
    to_chapter_id: int
    reason: str | None = None
    title: str = Field(min_length=1)
    problem: str = Field(min_length=1)
    summary: str = Field(min_length=1)
    event_type: str = Field(min_length=1)
    status: Literal["ongoing", "resolved"]
    progress: str | None = None
    node_id: str = Field(min_length=1, description="内部来源键，等于 event_id；不是正式事件身份")
    tree_id: str | None = Field(default=None, description="所属事件树身份；未入树时为 None")
    parent_node_id: str | None = Field(default=None, description="没有父节点时为 None")
    cause_role: EventCauseRole
    description: str = Field(min_length=1)
    evidence_paragraph_id: int | None = Field(default=None, ge=0, description="事件所在段的全局段落 ID")
    participants: list[EventParticipantInput] = Field(default_factory=list)
    is_foreshadow_setup: bool = False
    # 事件携带伏笔可能性
    payoff_likelihood: Confidence | None = None

    @field_validator("title", "problem", "summary", "event_type")
    @classmethod
    def normalize_annotation_event_text(cls, value: str) -> str:
        """事件业务字段必须有实际内容，不能以纯空白通过必填检查"""
        return normalize_semantic_text(value, label="event")

    @model_validator(mode="after")
    def validate_source_identity(self) -> BoundEvent:
        """node_id 仅是现有来源容器键的内部别名，不另造第二个来源身份"""
        if self.event_id != self.node_id:
            raise ValueError("event_id 必须与内部来源 node_id 一致")
        return self


__all__ = [
    "BoundEvent",
    "EventParticipantInput",
]
