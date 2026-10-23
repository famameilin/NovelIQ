"""五个诊断写入面的严格单项契约，批量不改变领域校验"""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

from src.event_trees.organization import NarrativeDescription, NarrativeTitle, OrganizationEvidence


class WriteItem(BaseModel):
    """禁止静默丢弃未事件字段，保留原文证据的原类型"""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)


class EventItem(WriteItem):
    operation: Literal["event"]
    key: str = Field(description="本执行的局部键：同一执行内唯一（不随章节、批次重置），重试沿用同一键")
    title: str
    problem: str
    summary: str
    event_type: str
    status: Literal["ongoing", "resolved"]
    evidence: list[OrganizationEvidence]
    progress: str | None = None
    from_chapter_id: int = Field(alias="from")
    to_chapter_id: int = Field(alias="to")
    reason: str = Field(min_length=1)


class ContainmentItem(WriteItem):
    operation: Literal["contain"]
    parent_event_id: str
    child_event_id: str
    reason: str = Field(min_length=1)
    evidence: list[OrganizationEvidence]


class RelationItem(WriteItem):
    operation: Literal["relation"]
    key: str
    source_kind: Literal["event"]
    source_id: str
    target_kind: Literal["event"]
    target_id: str
    relation_type: str
    reason: str
    evidence: list[OrganizationEvidence]


class RetractItem(WriteItem):
    operation: Literal["retract"]
    kind: Literal["contain", "relation"]
    identifier: str
    reason: str = Field(min_length=1)
    evidence: list[OrganizationEvidence]


class ArcItem(WriteItem):
    operation: Literal["arc"]
    key: str
    kind: Literal["main", "subplot"]
    title: NarrativeTitle
    objective: NarrativeDescription
    role: str
    reason: str
    evidence: list[OrganizationEvidence]
    parent_arc_id: str | None = None


class ArcLinkItem(WriteItem):
    operation: Literal["link"]
    event_id: str
    arc_id: str
    role: str
    reason: str
    evidence: list[OrganizationEvidence]


class OutcomeItem(WriteItem):
    operation: Literal["outcome"]
    key: str
    title: NarrativeTitle
    description: NarrativeDescription
    evidence: list[OrganizationEvidence]


class OutcomeLinkItem(WriteItem):
    operation: Literal["link"]
    event_id: str
    outcome_id: str
    reason: str
    evidence: list[OrganizationEvidence]


EventWriteItem = Annotated[
    EventItem | ContainmentItem | RetractItem | RelationItem,
    Field(discriminator="operation"),
]
ArcWriteItem = Annotated[ArcItem | ArcLinkItem, Field(discriminator="operation")]
OutcomeWriteItem = Annotated[OutcomeItem | OutcomeLinkItem, Field(discriminator="operation")]
