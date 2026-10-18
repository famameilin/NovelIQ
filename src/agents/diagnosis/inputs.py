"""五个诊断写入面的严格单项契约，批量不改变领域校验"""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

from src.event_trees.organization import ConflictClaim, NarrativeDescription, NarrativeTitle, OrganizationEvidence


class WriteItem(BaseModel):
    """禁止静默丢弃未声明字段，保留原文证据的原类型"""

    model_config = ConfigDict(extra="forbid")


class IdentityItem(WriteItem):
    operation: Literal["identity"]
    key: str
    title: str
    problem: str
    summary: str
    event_type: str
    status: Literal["ongoing", "resolved"]
    declaration_ids: list[str] = Field(min_length=1)
    stage_order: list[str] = Field(min_length=1)
    current_declaration_id: str
    reason: str = Field(min_length=1)
    evidence: list[OrganizationEvidence]
    progress: str | None = None


class EventItem(WriteItem):
    operation: Literal["event"]
    key: str
    title: str
    problem: str
    summary: str
    event_type: str
    status: Literal["ongoing", "resolved"]
    evidence: list[OrganizationEvidence]
    progress: str | None = None
    compared_event_ids: list[str]
    reason: str = Field(min_length=1)


class ContainmentItem(WriteItem):
    operation: Literal["contain"]
    parent_event_id: str
    child_event_id: str
    reason: str = Field(min_length=1)
    evidence: list[OrganizationEvidence]


class DeclarationReviewItem(WriteItem):
    operation: Literal["declaration_review"]
    declaration_ids: list[str] = Field(min_length=1)
    reason: str = Field(min_length=1)


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


class ComparisonItem(WriteItem):
    operation: Literal["compare"]
    source_declaration_id: str
    target_declaration_ids: list[str] = Field(min_length=1)
    disposition: Literal["same_event", "independent", "related"]
    reason: str = Field(min_length=1)
    evidence: list[OrganizationEvidence]


class RetractItem(WriteItem):
    operation: Literal["retract"]
    kind: Literal["identity", "contain", "relation"]
    identifier: str
    reason: str = Field(min_length=1)
    evidence: list[OrganizationEvidence]


class StructureReviewItem(WriteItem):
    operation: Literal["structure_review"]
    source_event_id: str
    target_event_id: str
    disposition: Literal["contains", "part_of", "related", "independent"]
    reason: str = Field(min_length=1)
    evidence: list[OrganizationEvidence]


class ReviewItem(WriteItem):
    operation: Literal["review"]
    event_ids: list[str]
    reason: str


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


class ConflictItem(WriteItem):
    key: str
    subject_kind: Literal["event", "declaration", "fact"]
    subject_id: str
    claims: list[ConflictClaim]
    reason: str


EventWriteItem = Annotated[
    IdentityItem
    | EventItem
    | ContainmentItem
    | DeclarationReviewItem
    | ComparisonItem
    | RetractItem
    | RelationItem
    | ReviewItem
    | StructureReviewItem,
    Field(discriminator="operation"),
]
ArcWriteItem = Annotated[ArcItem | ArcLinkItem, Field(discriminator="operation")]
OutcomeWriteItem = Annotated[OutcomeItem | OutcomeLinkItem, Field(discriminator="operation")]
