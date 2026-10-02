"""固定 cutoff 的案例 claim 与追加式连续性命令"""

from __future__ import annotations

import secrets
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Literal

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from src.agents.annotation.identity import stable_digest, text_digest
from src.storage.models import (
    AnalysisCutoff,
    CaseClaim,
    CaseHead,
    Chapter,
    ContinuityCase,
    CutoffPartition,
    Paragraph,
    ProjectionWorkItem,
    SemanticCommand,
    SourceManifest,
    TextEvidenceRecord,
)
from src.storage.repositories.pipeline_cases import (
    FollowUpCaseInput,
    bind_follow_up_target,
    follow_up_case_id,
    register_case_identity,
)
from src.storage.repositories.pipeline_resolution import validate_resolution
from src.storage.repositories.pipeline_work import (
    PipelineWorkRepository,
    StaleWorkLeaseError,
    WorkReceipt,
    append_outbox,
    work_audit_outcome,
)


@dataclass(frozen=True, slots=True)
class CaseReceipt:
    case_id: str
    claim_epoch: int
    lease_hash: str
    head_epoch: int
    state_hash: str


class CaseClaimLost(StaleWorkLeaseError):
    """案例 claim 冲突只拒绝本案例，不撤回任何正式章节"""


class PipelineContinuityRepository:
    """案例可搜索不等于可订正，必须持有目标 cutoff 下的有效 claim"""

    def __init__(self, session_factory: Callable[[], Session]) -> None:
        self.session_factory = session_factory

    def visible_cases(self, cutoff_hash: str) -> list[dict[str, Any]]:
        with self.session_factory() as session:
            cutoff = session.get(AnalysisCutoff, cutoff_hash)
            if cutoff is None or cutoff.state != "released":
                raise ValueError("continuity 只能读取 released cutoff")
            snapshots = {item["case_id"]: item for item in cutoff.manifest["cases"]}
            rows = session.execute(select(ContinuityCase).where(
                ContinuityCase.run_id == cutoff.run_id, ContinuityCase.case_id.in_(snapshots),
            ).order_by(ContinuityCase.case_id)).scalars()
            evidence_by_case = {row.partition_key.removeprefix("case:"): sorted({evidence_id
                for assertion in row.projection["assertions"] for evidence_id in assertion["evidence_ids"]})
                for row in session.execute(select(CutoffPartition).where(
                    CutoffPartition.cutoff_hash == cutoff_hash, CutoffPartition.partition_key.startswith("case:"),
                )).scalars()}
            return [{
                "case_id": row.case_id, "type": row.issue_kind, "description": row.description,
                "keys": row.search_keys, "target_ref": row.target_ref,
                "chapter_id": row.originating_chapter_id,
                "source_evidence": sorted(set(row.source_evidence) | set(evidence_by_case.get(row.case_id, []))),
                "state": snapshots[row.case_id]["state"], "state_hash": snapshots[row.case_id]["state_hash"],
            } for row in rows]

    def claim(self, receipt: WorkReceipt, case_id: str, *, lease_seconds: int = 120) -> CaseReceipt:
        if lease_seconds < 1 or receipt.work_kind != "continuity":
            raise ValueError("claim 必须属于 continuity 工作且租约为正")
        if receipt.work_kind != "continuity" or case_id != receipt.payload.get("case_id"):
            raise ValueError("案例 claim 不属于本工作指定目标")
        with self.session_factory() as session, session.begin():
            PipelineWorkRepository.lock_owned_work(session, receipt)
            cutoff = session.get(AnalysisCutoff, receipt.cutoff_hash)
            if cutoff is None or cutoff.state != "released" or cutoff.run_id != receipt.run_id:
                raise CaseClaimLost("工作 cutoff 不可见")
            visible = {item["case_id"]: item for item in cutoff.manifest["cases"]}
            if case_id not in visible:
                raise CaseClaimLost("案例不属于工作 cutoff")
            case = session.get(ContinuityCase, case_id)
            if case is None or case.run_id != receipt.run_id:
                raise CaseClaimLost("案例不属于当前 run")
            head = session.get(CaseHead, case_id, with_for_update=True)
            now = session.execute(select(func.clock_timestamp())).scalar_one()
            if head is None or head.state not in {"pending", "deferred", "contested"}:
                raise CaseClaimLost("案例已解决或不存在")
            if visible[case_id]["state_hash"] != head.state_hash:
                raise CaseClaimLost("案例已不再属于本轮固定的状态前提")
            if head.active_lease_expires_at is not None and head.active_lease_expires_at > now:
                owned = session.get(CaseClaim, (case_id, head.claim_epoch))
                if owned is not None and owned.work_id == receipt.work_id and owned.status == "active":
                    return CaseReceipt(case_id, head.claim_epoch, owned.lease_hash, head.head_epoch, head.state_hash)
                raise CaseClaimLost("案例已由其它工作领取")
            previous = session.get(CaseClaim, (case_id, head.claim_epoch))
            if previous is not None and previous.status == "active":
                previous.status = "expired"
            head.claim_epoch += 1
            head.active_lease_hash = secrets.token_hex(32)
            head.active_lease_expires_at = now + timedelta(seconds=lease_seconds)
            session.add(CaseClaim(
                case_id=case_id, claim_epoch=head.claim_epoch, lease_hash=head.active_lease_hash,
                work_id=receipt.work_id, expires_at=head.active_lease_expires_at,
            ))
            append_outbox(session, run_id=receipt.run_id, work_id=receipt.work_id,
                          attempt_epoch=receipt.attempt_epoch, event_type="case_claimed",
                          payload={"case_id": case_id, "claim_epoch": head.claim_epoch},
                          cutoff_hash=receipt.cutoff_hash)
            return CaseReceipt(case_id, head.claim_epoch, head.active_lease_hash, head.head_epoch, head.state_hash)

    def renew(self, receipt: WorkReceipt, claim: CaseReceipt, *, lease_seconds: int = 120) -> datetime:
        """模型长回合同时续案例租约；工作失效、前提变化或租约已过期均不允许复活"""
        if lease_seconds < 1 or claim.case_id != receipt.payload.get("case_id"):
            raise ValueError("案例续租参数与工作目标不匹配")
        with self.session_factory() as session, session.begin():
            PipelineWorkRepository.lock_owned_work(session, receipt)
            head = session.get(CaseHead, claim.case_id, with_for_update=True)
            claim_row = session.get(CaseClaim, (claim.case_id, claim.claim_epoch), with_for_update=True)
            now = session.execute(select(func.clock_timestamp())).scalar_one()
            if (head is None or claim_row is None or claim_row.status != "active"
                    or claim_row.work_id != receipt.work_id or head.claim_epoch != claim.claim_epoch
                    or head.active_lease_hash != claim.lease_hash or claim_row.lease_hash != claim.lease_hash
                    or head.active_lease_expires_at is None or head.active_lease_expires_at <= now
                    or head.head_epoch != claim.head_epoch or head.state_hash != claim.state_hash):
                raise CaseClaimLost("案例续租被 claim 或前提栅栏拒绝")
            expires_at = now + timedelta(seconds=lease_seconds)
            head.active_lease_expires_at = expires_at
            claim_row.expires_at = expires_at
            return expires_at

    def commit(
        self, receipt: WorkReceipt, claim: CaseReceipt | None, *,
        state: Literal["resolved", "deferred", "contested"] = "deferred",
        resolution: dict[str, Any] | None = None,
        reason: str = "",
        evidence: list[dict[str, Any]] | None = None,
        follow_up_cases: list[FollowUpCaseInput] | None = None,
    ) -> str | None:
        """原文能力、work、claim 和 CAS 在同一事务复核后再追加命令"""
        if receipt.work_kind != "continuity" or (claim is not None and claim.case_id != receipt.payload.get("case_id")):
            raise ValueError("连续性提交不属于本工作指定目标")
        with self.session_factory() as session, session.begin():
            PipelineWorkRepository.lock_owned_work(session, receipt)
            if claim is None:
                PipelineWorkRepository.mark_submitted(session, receipt)
                work_audit_outcome(session, receipt, "claim_lost")
                append_outbox(session, run_id=receipt.run_id, work_id=receipt.work_id,
                              attempt_epoch=receipt.attempt_epoch, cutoff_hash=receipt.cutoff_hash,
                              event_type="case_claim_lost", payload={"case_id": receipt.payload["case_id"]})
                return None
            case = session.get(ContinuityCase, claim.case_id)
            head = session.get(CaseHead, claim.case_id, with_for_update=True)
            claim_row = session.get(CaseClaim, (claim.case_id, claim.claim_epoch), with_for_update=True)
            now: datetime = session.execute(select(func.clock_timestamp())).scalar_one()
            if (case is None or case.run_id != receipt.run_id or head is None or claim_row is None
                or claim_row.work_id != receipt.work_id or claim_row.status != "active"
                or head.claim_epoch != claim.claim_epoch or head.active_lease_hash != claim.lease_hash
                or head.active_lease_expires_at is None or head.active_lease_expires_at <= now
                or head.head_epoch != claim.head_epoch or head.state_hash != claim.state_hash):
                raise CaseClaimLost("案例 claim 或前提已变化")
            if state not in {"resolved", "deferred", "contested"}:
                raise ValueError("无效的连续性状态")
            if state == "resolved" and not resolution:
                raise ValueError("resolved 必须包含明确主张")
            domain_command = None
            normalized = resolution or {}
            if resolution:
                normalized, domain_command = validate_resolution(
                    session, case, resolution, cutoff_hash=receipt.cutoff_hash,
                )
            evidence_ids = self._register_evidence(session, receipt, case, evidence or [])
            if state == "resolved" and not evidence:
                raise ValueError("连续性结论必须引用本轮实际读取的原文")
            payload = {"case_id": case.case_id, "target_ref": case.target_ref,
                       "state": state, "resolution": normalized, "reason": reason,
                       "domain_command": list(domain_command) if domain_command is not None else None}
            payload_hash = stable_digest(payload)
            command_id = stable_digest(receipt.work_id, case.case_id, payload_hash)
            partition = f"case:{case.case_id}"
            chapter = session.get(Chapter, (case.originating_chapter_id, receipt.run_id))
            if chapter is None:
                raise ValueError("案例来源章节不存在")
            session.execute(insert(SemanticCommand).values(
                command_id=command_id, run_id=receipt.run_id,
                command_path=f"case/{case.case_id}/{receipt.work_id}/{payload_hash}",
                command_kind="case_resolution", partition_key=partition,
                origin_annotation_id=case.originating_annotation_id,
                origin_chapter_id=case.originating_chapter_id,
                origin_chapter_sequence=chapter.sequence,
                effective_document_position={"chapter_id": case.originating_chapter_id},
                payload=payload, payload_hash=payload_hash, evidence_ids=evidence_ids,
                independence_keys=sorted({f"paragraph:{item['paragraph_id']}" for item in evidence or []}),
                precondition_epoch=claim.head_epoch, precondition_hash=claim.state_hash,
                author_work_id=receipt.work_id,
            ).on_conflict_do_nothing(index_elements=[SemanticCommand.command_id]))
            session.flush()
            session.execute(insert(ProjectionWorkItem).values(
                projection_id=stable_digest(command_id, partition), run_id=receipt.run_id,
                command_id=command_id, partition_key=partition,
            ).on_conflict_do_nothing(index_elements=[ProjectionWorkItem.command_id, ProjectionWorkItem.partition_key]))
            for seed in follow_up_cases or []:
                seed = FollowUpCaseInput.model_validate(seed)
                target, origin = bind_follow_up_target(
                    session, run_id=receipt.run_id, cutoff_hash=receipt.cutoff_hash, target=seed.target_ref,
                )
                seed_evidence = self._register_evidence(session, receipt, case, seed.evidence, include_source=False)
                seed_id = follow_up_case_id(receipt.run_id, seed)
                register_case_identity(
                    session, run_id=receipt.run_id, case_id=seed_id, issue_kind=seed.type,
                    description=seed.description, keys=seed.keys, target_ref=target, evidence_ids=seed_evidence,
                    annotation_id=origin["annotation_id"], chapter_id=origin["chapter_id"],
                )
                seed_payload = {"case_id": seed_id, "target_ref": target, "parent_case_id": case.case_id,
                                "input_cutoff_hash": receipt.cutoff_hash}
                seed_command = stable_digest(receipt.work_id, "follow-up", seed_payload, seed_evidence)
                seed_partition = f"case:{seed_id}"
                session.execute(insert(SemanticCommand).values(
                    command_id=seed_command, run_id=receipt.run_id, command_kind="case_seed",
                    command_path=f"follow-up/{seed_command}", partition_key=seed_partition,
                    origin_annotation_id=origin["annotation_id"], origin_chapter_id=origin["chapter_id"],
                    origin_chapter_sequence=origin["chapter_sequence"],
                    effective_document_position=origin["position"], payload=seed_payload,
                    payload_hash=stable_digest(seed_payload), evidence_ids=seed_evidence,
                    independence_keys=sorted({f"paragraph:{item['paragraph_id']}" for item in seed.evidence}),
                    author_work_id=receipt.work_id,
                ).on_conflict_do_nothing(index_elements=[SemanticCommand.command_id]))
                session.flush()
                session.execute(insert(ProjectionWorkItem).values(
                    projection_id=stable_digest(seed_command, seed_partition), run_id=receipt.run_id,
                    command_id=seed_command, partition_key=seed_partition,
                ).on_conflict_do_nothing(index_elements=[
                    ProjectionWorkItem.command_id, ProjectionWorkItem.partition_key,
                ]))
            prior_resolutions = session.execute(select(SemanticCommand.payload).where(
                SemanticCommand.run_id == receipt.run_id, SemanticCommand.partition_key == partition,
                SemanticCommand.command_kind == "case_resolution",
            )).scalars()
            values = {stable_digest(item["resolution"]) for item in prior_resolutions
                      if item["state"] == "resolved"}
            head.state = "contested" if len(values) > 1 else state
            head.head_epoch += 1
            head.state_hash = stable_digest(head.state, sorted(values), evidence_ids)
            head.active_lease_hash = None
            head.active_lease_expires_at = None
            head.updated_at = now
            claim_row.status = "consumed"
            claim_row.consumed_at = now
            PipelineWorkRepository.mark_submitted(session, receipt)
            append_outbox(session, run_id=receipt.run_id, work_id=receipt.work_id,
                          attempt_epoch=receipt.attempt_epoch, event_type="case_resolution_submitted",
                          payload={"case_id": case.case_id, "state": state, "command_id": command_id},
                          cutoff_hash=receipt.cutoff_hash)
            return command_id

    @staticmethod
    def _register_evidence(
        session: Session, receipt: WorkReceipt, case: ContinuityCase, evidence: list[dict[str, Any]],
        *, include_source: bool = True,
    ) -> list[str]:
        evidence_ids = set(case.source_evidence) if include_source else set()
        source_hash = receipt.payload["source_manifest_hash"]
        source = session.get(SourceManifest, source_hash)
        if source is None or source.run_id != receipt.run_id:
            raise ValueError("连续性工作没有匹配的原文快照")
        for item in evidence:
            paragraph = session.get(Paragraph, (receipt.run_id, int(item["paragraph_id"])))
            if (paragraph is None
                or source.paragraph_hashes.get(str(paragraph.paragraph_id)) != text_digest(paragraph.text)
                or item["text_hash"] != text_digest(paragraph.text)):
                raise ValueError("连续性原文来源已变化")
            start, end = int(item["char_start"]), int(item["char_end"])
            if not 0 <= start < end <= len(paragraph.text):
                raise ValueError("连续性证据区间越界")
            evidence_id = stable_digest(receipt.run_id, paragraph.paragraph_id, start, end, source_hash)
            session.execute(insert(TextEvidenceRecord).values(
                evidence_id=evidence_id, run_id=receipt.run_id, chapter_id=paragraph.chapter_id,
                paragraph_id=paragraph.paragraph_id, char_start=start, char_end=end,
                text_hash=text_digest(paragraph.text[start:end]), source_manifest_hash=source_hash,
            ).on_conflict_do_nothing(index_elements=[TextEvidenceRecord.evidence_id]))
            evidence_ids.add(evidence_id)
        return sorted(evidence_ids)
