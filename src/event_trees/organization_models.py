"""事件组织的冻结模型、值域与内容摘要"""

from __future__ import annotations

import hashlib
import json
import unicodedata
from typing import Annotated, Any, Literal

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, model_validator

from src.text_processing.evidence import SourceReference
from src.utils.event_line_names import validate_event_line_names


def _validate_narrative_description(value: str) -> str:
    if sum(not unicodedata.category(char).startswith("P") for char in value) > 20:
        raise ValueError("目标或说明最多20字，不计算标点，请精简后重写并重新提交")
    return value


def _validate_narrative_title(value: str) -> str:
    if sum(not unicodedata.category(char).startswith("P") for char in value) > 6:
        raise ValueError("标题最多6字，不计算标点，请精简后重写并重新提交")
    return value


NarrativeTitle = Annotated[
    str,
    Field(min_length=1, description="单一精练标题，最多6字；不计算Unicode标点，其余字符逐字计数；超限须重写"),
    AfterValidator(_validate_narrative_title),
]


NarrativeDescription = Annotated[
    str,
    Field(min_length=1, description="一句目标或结果说明，最多20字；不计算Unicode标点，其余字符逐字计数；超限须重写"),
    AfterValidator(_validate_narrative_description),
]


def snapshot_digest(payload: Any) -> str:
    """稳定摘要只绑定业务内容，不包含审计或容量租约"""
    return hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def record_payloads(records: Any) -> list[dict[str, Any]]:
    """无序候选集合以内容排序，跨工作恢复顺序不改变核对结果"""
    return sorted((item.model_dump(mode="json") for item in records), key=snapshot_digest)


class OrganizationEvidence(BaseModel):
    """工具只接受真实段号与逐字引文，坐标和哈希由服务端绑定"""

    model_config = ConfigDict(extra="forbid", frozen=True)
    paragraph_id: int = Field(ge=0)
    quote: str | None = Field(default=None, min_length=1)
    occurrence: int = Field(default=1, ge=1)
    event_id: str | None = Field(default=None, min_length=1)


class BoundOrganizationEvidence(SourceReference):
    """正式证据保留可选的完整事件引用与已绑定原文位置"""

    event_id: str | None = None


class OrganizationRecord(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    evidence: list[BoundOrganizationEvidence] = Field(min_length=1, max_length=100)
    producer_agent_id: str = ""


class EventOutcomeDraft(OrganizationRecord):
    outcome_id: str
    title: NarrativeTitle
    description: NarrativeDescription
    first_text_position: int = Field(ge=0)

    @model_validator(mode="after")
    def validate_text_evidence(self) -> EventOutcomeDraft:
        if any(ref.event_id is not None for ref in self.evidence):
            raise ValueError("全书结果只接受自身原文证据，不接受事件贡献来源")
        return self


class CompleteEventDraft(OrganizationRecord):
    """诊断待保存的完整事件；直接过程与子事件作为同一笔原子输入"""

    event_id: str
    local_key: str = Field(min_length=1, max_length=255)
    title: str = Field(min_length=1)
    problem: str = Field(min_length=1)
    summary: str = Field(min_length=1)
    event_type: str = Field(min_length=1)
    status: Literal["ongoing", "resolved"]
    progress: str | None = None
    reason: str | None = None
    annotation_record_id: str | None = None
    from_chapter_id: int
    to_chapter_id: int
    is_foreshadowing_root: bool = False
    payoff_likelihood: Literal["high", "medium", "low"] | None = None
    first_text_position: int = Field(ge=0)
    participants: list[dict[str, Any]] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_payoff(self) -> CompleteEventDraft:
        if self.is_foreshadowing_root != (self.payoff_likelihood is not None):
            raise ValueError("伏笔根与 payoff_likelihood 必须成对：伏笔根必须给回收预期，非伏笔根不能给")
        return self


class EventQueueDraft(OrganizationRecord):
    "模型明确提交的完整有序事件树；允许空树"

    tree_id: str
    tree_key: str | None = Field(default=None, max_length=255)
    title: str = Field(min_length=1)
    description: str = Field(min_length=1)
    event_ids: list[str] = Field(default_factory=list)
    reason: str = ""
    evidence: list[BoundOrganizationEvidence] = Field(default_factory=list, max_length=100)

    @model_validator(mode="after")
    def validate_members(self) -> EventQueueDraft:
        if len(set(self.event_ids)) != len(self.event_ids):
            raise ValueError("树成员不得重复")
        if self.event_ids and not self.evidence:
            raise ValueError("非空事件树必须给出原文证据")
        return self


class QueueReferenceDraft(OrganizationRecord):
    parent_tree_id: str
    child_tree_id: str
    reason: str = Field(min_length=1)
    evidence: list[BoundOrganizationEvidence] = Field(default_factory=list)


class RelationDraft(OrganizationRecord):
    relation_id: str
    source_kind: Literal["event"]
    source_id: str
    target_kind: Literal["event"]
    target_id: str
    relation_type: str = Field(min_length=1)
    reason: str = Field(min_length=1)
    source_operation_id: str | None
    is_active: bool | None = True


class NarrativeOrganization(BaseModel):
    """完整事件的全书组织；章节概要、类型和包含结构保持不可变"""

    model_config = ConfigDict(extra="forbid", frozen=True)
    source_agent_id: str | None = None
    event_line_ids: list[str] = Field(default_factory=list)
    event_line_names: dict[str, str] = Field(default_factory=dict)
    events: list[CompleteEventDraft] = Field(default_factory=list)
    relations: list[RelationDraft] = Field(default_factory=list)
    outcomes: list[EventOutcomeDraft] = Field(default_factory=list)
    queues: list[EventQueueDraft] = Field(default_factory=list)
    queue_references: list[QueueReferenceDraft] = Field(default_factory=list)
    content_snapshot: str | None = None
    structure_snapshot: str | None = None

    @model_validator(mode="after")
    def validate_structure(self) -> NarrativeOrganization:
        outcomes = {item.outcome_id for item in self.outcomes}
        if self.event_line_names:
            validate_event_line_names(self.event_line_names, self.event_line_ids)
        for records, keys in (
            (self.events, {item.event_id for item in self.events}),
            (self.relations, {item.relation_id for item in self.relations}),
            (self.outcomes, list(outcomes)),
            (self.queues, {item.tree_id for item in self.queues}),
            (self.queue_references, {(item.parent_tree_id, item.child_tree_id) for item in self.queue_references}),
        ):
            if len(records) != len(keys):
                raise ValueError("全书组织身份或关联端点重复")
        return self
