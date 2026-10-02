"""连续性派生案例的稳定目标与追加式证据"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from src.agents.annotation.identity import stable_digest
from src.agents.annotation.schema import RELATION_DEFINITIONS
from src.storage.models import AnalysisCutoff, CaseHead, ContinuityCase, CutoffPartition
from src.storage.repositories.pipeline_work import ImmutableWorkConflict


class CaseTargetInput(BaseModel):
    """目标必须是固定 cutoff 中可见的确切领域对象，不接受任意记录键"""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    domain: Literal["entity", "dialogue", "event", "relation"]
    entity_id: str | None = None
    candidate_key: str | None = None
    event_id: str | None = None
    from_entity_id: str | None = None
    to_entity_id: str | None = None
    relation_type: str | None = None

    @model_validator(mode="after")
    def validate_fields(self) -> CaseTargetInput:
        required = {
            "entity": {"entity_id"}, "dialogue": {"candidate_key"}, "event": {"event_id"},
            "relation": {"from_entity_id", "to_entity_id", "relation_type"},
        }[self.domain]
        present = {field for field in type(self).model_fields if field != "domain" and getattr(self, field) is not None}
        if present != required or any(not getattr(self, field) for field in required):
            raise ValueError("案例目标的字段必须与 domain 完全匹配")
        if self.domain == "relation" and self.from_entity_id == self.to_entity_id:
            raise ValueError("案例关系端点不能相同")
        return self


class FollowUpCaseInput(BaseModel):
    """新疑点必须绑定领域目标和本轮实际读取的原文，描述不参与稳定身份"""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    type: str = Field(min_length=1, max_length=60)
    description: str = Field(min_length=1, max_length=100)
    keys: list[str] = Field(min_length=1, max_length=20)
    target_ref: CaseTargetInput
    evidence: list[dict[str, Any]] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_keys(self) -> FollowUpCaseInput:
        self.keys = sorted({key.strip() for key in self.keys})
        if any(not key for key in self.keys):
            raise ValueError("派生案例检索键不能为空")
        return self


def cutoff_assertions(session: Session, cutoff_hash: str, run_id: str) -> list[dict[str, Any]]:
    """对象权限来自 released 快照，不能由当前可变 head 或猜测 UUID 获得"""
    cutoff = session.get(AnalysisCutoff, cutoff_hash)
    if cutoff is None or cutoff.run_id != run_id or cutoff.state != "released":
        raise ValueError("案例目标需要本 run 的 released cutoff")
    return [assertion for partition in session.execute(select(CutoffPartition).where(
        CutoffPartition.cutoff_hash == cutoff_hash,
    )).scalars() for assertion in partition.projection["assertions"]]


def bind_follow_up_target(
    session: Session, *, run_id: str, cutoff_hash: str, target: CaseTargetInput,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """服务端按正式对象确定来源章节，模型不能伪造 originating_annotation_id"""
    assertions = cutoff_assertions(session, cutoff_hash, run_id)
    entities: dict[str, dict[str, Any]] = {}
    for assertion in assertions:
        if assertion["kind"] == "entity_mention":
            entity_id = assertion["payload"]["entity_id"]
            entities.setdefault(entity_id, assertion)
    origin = None
    if target.domain == "entity":
        origin = entities.get(str(target.entity_id))
    elif target.domain == "relation":
        if target.from_entity_id not in entities or target.to_entity_id not in entities:
            raise ValueError("案例关系端点不属于固定 cutoff")
        if target.relation_type not in RELATION_DEFINITIONS:
            raise ValueError("案例关系类型不属于项目词表")
        origin = entities[str(target.from_entity_id)]
    else:
        kind, field, identifier = ("event", "node_id", target.event_id) if target.domain == "event" else (
            "dialogue", "candidate_key", target.candidate_key,
        )
        origin = next((assertion for assertion in assertions
                       if assertion["kind"] == kind and assertion["payload"].get(field) == identifier), None)
    if origin is None:
        raise ValueError("派生案例目标不属于固定 cutoff 的正式对象")
    return target.model_dump(exclude_none=True), origin


def follow_up_case_id(run_id: str, seed: FollowUpCaseInput) -> str:
    return stable_digest(run_id, seed.type, seed.target_ref.model_dump(exclude_none=True), fold_text=True)


def register_case_identity(
    session: Session, *, run_id: str, case_id: str, issue_kind: str, description: str,
    keys: list[str], target_ref: dict[str, Any], evidence_ids: list[str],
    annotation_id: str | None, chapter_id: int,
) -> None:
    """身份和初始 Evidence 不更新；重复发现通过调用方追加证据命令"""
    session.execute(insert(ContinuityCase).values(
        case_id=case_id, run_id=run_id, case_key=case_id, issue_kind=issue_kind,
        description=description, search_keys=keys, target_ref=target_ref, source_evidence=evidence_ids,
        originating_annotation_id=annotation_id, originating_chapter_id=chapter_id,
    ).on_conflict_do_nothing(index_elements=[ContinuityCase.case_id]))
    prior = session.get(ContinuityCase, case_id)
    if prior is None or prior.run_id != run_id or prior.target_ref != target_ref or prior.issue_kind != issue_kind:
        raise ImmutableWorkConflict(f"CaseSeed 目标冲突: case_id={case_id}")
    session.execute(insert(CaseHead).values(
        case_id=case_id, state="pending", state_hash=stable_digest("pending", case_id),
    ).on_conflict_do_nothing(index_elements=[CaseHead.case_id]))
