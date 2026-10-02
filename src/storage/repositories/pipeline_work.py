"""数据库租约驱动的 Agent 工作队列"""

from __future__ import annotations

import secrets
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Literal, cast

from sqlalchemy import and_, func, or_, select, text, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from src.agents.annotation.identity import stable_digest
from src.storage.models import (
    AgentInvocation,
    AgentWorkItem,
    AnalysisRun,
    CaseClaim,
    CaseHead,
    EventOutbox,
)

WorkKind = Literal["formal_current", "continuity"]


class StaleWorkLeaseError(RuntimeError):
    """工作已被接管、取消或租约过期，旧尝试不能写入业务状态"""


class ImmutableWorkConflict(RuntimeError):
    """同一逻辑工作在相同 cutoff 内出现另一份输入"""


@dataclass(frozen=True, slots=True)
class WorkReceipt:
    work_id: str
    run_id: str
    work_kind: WorkKind
    payload: dict[str, Any]
    cutoff_hash: str
    attempt_epoch: int
    lease_hash: str
    cancellation_epoch: int
    lease_expires_at: datetime


def _database_now(session: Session) -> datetime:
    """所有租约判断统一使用数据库时钟，避免节点系统时钟漂移"""
    return session.execute(select(func.clock_timestamp())).scalar_one()


def work_audit_outcome(session: Session, receipt: WorkReceipt, outcome: str) -> None:
    session.execute(update(AgentInvocation).where(
        AgentInvocation.work_id == receipt.work_id, AgentInvocation.attempt_epoch == receipt.attempt_epoch,
    ).values(business_outcome=outcome))


def release_work_claims(session: Session, work_id: str) -> None:
    """失败与取消归还 claim，避免恢复后的工作等待上一次有效租约"""
    for claim in session.execute(select(CaseClaim).where(
        CaseClaim.work_id == work_id, CaseClaim.status == "active",
    ).order_by(CaseClaim.case_id)).scalars():
        if claim.status != "active":
            continue
        head = session.get(CaseHead, claim.case_id, with_for_update=True)
        if head is not None and head.claim_epoch == claim.claim_epoch and head.active_lease_hash == claim.lease_hash:
            head.active_lease_hash = None
            head.active_lease_expires_at = None
        claim.status = "released"


def append_outbox(
    session: Session,
    *,
    run_id: str,
    event_type: str,
    payload: dict[str, Any],
    work_id: str | None = None,
    attempt_epoch: int | None = None,
    chapter_id: int | None = None,
    cutoff_hash: str | None = None,
) -> str:
    """与业务状态共用事务，重复写入相同事件时不产生第二条流记录"""
    session.get(AnalysisRun, run_id, with_for_update={"read": True})
    session.execute(text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"),
                    {"key": f"outbox:{run_id}"})
    event_id = stable_digest(run_id, work_id, attempt_epoch, cutoff_hash, event_type, payload)
    statement = insert(EventOutbox).values(
        event_id=event_id,
        run_id=run_id,
        work_id=work_id,
        attempt_epoch=attempt_epoch,
        chapter_id=chapter_id,
        cutoff_hash=cutoff_hash,
        event_type=event_type,
        payload=payload,
    )
    session.execute(statement.on_conflict_do_nothing(index_elements=[EventOutbox.event_id]))
    return event_id


class PipelineWorkRepository:
    """每次队列操作独立短事务，模型请求期间不持有数据库 Session"""

    def __init__(self, session_factory: Callable[[], Session]) -> None:
        self.session_factory = session_factory

    def enqueue(
        self,
        *,
        run_id: str,
        work_kind: WorkKind,
        logical_key: str,
        payload: dict[str, Any],
        cutoff_hash: str,
        priority: int = 0,
    ) -> str:
        payload_hash = stable_digest(payload)
        work_id = stable_digest(run_id, work_kind, logical_key, payload_hash, cutoff_hash)
        with self.session_factory() as session, session.begin():
            run = session.get(AnalysisRun, run_id, with_for_update=True)
            if run is None:
                raise ValueError(f"分析 run 不存在: {run_id}")
            if run.cancel_requested:
                raise StaleWorkLeaseError(f"分析 run 已取消: {run_id}")
            existing = session.execute(
                select(AgentWorkItem).where(
                    AgentWorkItem.run_id == run_id,
                    AgentWorkItem.work_kind == work_kind,
                    AgentWorkItem.logical_key == logical_key,
                    AgentWorkItem.cutoff_hash == cutoff_hash,
                )
            ).scalar_one_or_none()
            if existing is not None:
                existing_input = {key: value for key, value in existing.payload.items() if key != "model_id"}
                if stable_digest(existing_input) != payload_hash:
                    raise ImmutableWorkConflict(f"工作输入冲突: run_id={run_id} logical_key={logical_key}")
                return existing.work_id
            session.add(
                AgentWorkItem(
                    work_id=work_id,
                    run_id=run_id,
                    work_kind=work_kind,
                    logical_key=logical_key,
                    payload=payload,
                    payload_hash=payload_hash,
                    cutoff_hash=cutoff_hash,
                    priority=priority,
                    cancellation_epoch=run.cancellation_epoch,
                )
            )
            append_outbox(
                session,
                run_id=run_id,
                work_id=work_id,
                event_type="work_queued",
                payload={"work_kind": work_kind, "logical_key": logical_key},
                cutoff_hash=cutoff_hash,
            )
        return work_id

    def claim(
        self,
        *,
        owner: str,
        lease_seconds: int = 120,
        run_id: str | None = None,
        work_kind: WorkKind | None = None,
        max_attempts: int | None = None,
        in_flight: Mapping[str, int] | None = None,
    ) -> WorkReceipt | None:
        """使用 SKIP LOCKED 领取一个可执行项，过期租约由下一节点接管"""
        if lease_seconds <= 0:
            raise ValueError("lease_seconds 必须大于零")
        with self.session_factory() as session, session.begin():
            now = _database_now(session)
            if run_id is not None:
                run = session.get(AnalysisRun, run_id, with_for_update={"read": True})
                if run is None or run.cancel_requested:
                    return None
            filters = []
            if run_id is not None:
                filters.append(AgentWorkItem.run_id == run_id)
            if work_kind is not None:
                filters.append(AgentWorkItem.work_kind == work_kind)
            row = session.execute(
                select(AgentWorkItem)
                .join(AnalysisRun, AnalysisRun.run_id == AgentWorkItem.run_id)
                .where(
                    AgentWorkItem.available_at <= now,
                    AgentWorkItem.cancellation_epoch == AnalysisRun.cancellation_epoch,
                    AnalysisRun.cancel_requested.is_(False),
                    *filters,
                    or_(
                        AgentWorkItem.state == "queued",
                        and_(
                            AgentWorkItem.state == "running",
                            AgentWorkItem.lease_expires_at <= now,
                        ),
                    ),
                )
                .order_by(
                    AgentWorkItem.priority.desc(),
                    AgentWorkItem.available_at,
                    AgentWorkItem.created_at,
                    AgentWorkItem.work_id,
                )
                .limit(1)
                .with_for_update(of=AgentWorkItem, skip_locked=True)
            ).scalar_one_or_none()
            if row is None:
                return None
            if run_id is None:
                run = session.get(AnalysisRun, row.run_id, with_for_update={"read": True})
                if run is None or run.cancel_requested or run.cancellation_epoch != row.cancellation_epoch:
                    return None
            if max_attempts is not None and row.attempt_count >= max_attempts:
                row.state = "dead_letter"
                release_work_claims(session, row.work_id)
                append_outbox(session, run_id=row.run_id, work_id=row.work_id,
                              event_type="work_dead_letter", payload={"reason": "过期接管耗尽尝试预算"})
                return None
            from src.config import settings
            from src.config.model_assignment import select_annotation_model

            # 2026-10-02 模型池分发：只在有空位的模型中选举；全部满位不领取，任务留在队列
            selected = select_annotation_model(
                stable_digest(row.work_id, row.attempt_epoch), settings.models.model_pool,
                previous_model_id=row.payload.get("model_id"), in_flight=in_flight,
            )
            if selected is None:
                return None
            row.state = "running"
            row.attempt_count += 1
            row.attempt_epoch += 1
            # 模型选择属于执行尝试，不参与不可变的原文工作身份
            row.payload = {**row.payload, "model_id": selected}
            row.lease_owner = owner
            row.lease_hash = secrets.token_hex(32)
            row.lease_expires_at = now + timedelta(seconds=lease_seconds)
            row.heartbeat_at = now
            row.updated_at = now
            receipt = WorkReceipt(
                work_id=row.work_id,
                run_id=row.run_id,
                work_kind=cast(WorkKind, row.work_kind),
                payload=dict(row.payload),
                cutoff_hash=row.cutoff_hash,
                attempt_epoch=row.attempt_epoch,
                lease_hash=row.lease_hash,
                cancellation_epoch=row.cancellation_epoch,
                lease_expires_at=row.lease_expires_at,
            )
            append_outbox(
                session,
                run_id=row.run_id,
                work_id=row.work_id,
                attempt_epoch=row.attempt_epoch,
                event_type="work_started",
                payload={"work_kind": row.work_kind, "model_id": selected},
                cutoff_hash=row.cutoff_hash,
            )
            return receipt

    @staticmethod
    def lock_owned_work(session: Session, receipt: WorkReceipt) -> AgentWorkItem:
        """写入前在业务事务里复核租约、epoch 与取消 epoch"""
        run = session.get(AnalysisRun, receipt.run_id, with_for_update={"read": True})
        row = session.get(AgentWorkItem, receipt.work_id, with_for_update=True)
        now = _database_now(session)
        if (
            row is None
            or run is None
            or row.state != "running"
            or row.attempt_epoch != receipt.attempt_epoch
            or row.lease_hash != receipt.lease_hash
            or row.lease_expires_at is None
            or row.lease_expires_at <= now
            or row.cancellation_epoch != receipt.cancellation_epoch
            or run.cancellation_epoch != receipt.cancellation_epoch
            or run.cancel_requested
        ):
            raise StaleWorkLeaseError(f"工作租约失效: work_id={receipt.work_id}")
        return row

    def heartbeat(self, receipt: WorkReceipt, *, lease_seconds: int = 120) -> datetime:
        with self.session_factory() as session, session.begin():
            row = self.lock_owned_work(session, receipt)
            now = _database_now(session)
            row.heartbeat_at = now
            row.lease_expires_at = now + timedelta(seconds=lease_seconds)
            row.updated_at = now
            for claim in session.execute(select(CaseClaim).where(
                CaseClaim.work_id == receipt.work_id, CaseClaim.status == "active",
            )).scalars():
                head = session.get(CaseHead, claim.case_id, with_for_update=True)
                if (head is not None and head.claim_epoch == claim.claim_epoch
                    and head.active_lease_hash == claim.lease_hash
                    and head.active_lease_expires_at is not None and head.active_lease_expires_at > now):
                    claim.expires_at = row.lease_expires_at
                    head.active_lease_expires_at = row.lease_expires_at
            return row.lease_expires_at

    @staticmethod
    def mark_submitted(session: Session, receipt: WorkReceipt) -> None:
        """由正式或连续性提交事务调用，业务结果与 work 状态原子提交"""
        row = PipelineWorkRepository.lock_owned_work(session, receipt)
        row.state = "submitted"
        row.lease_owner = None
        row.lease_hash = None
        row.lease_expires_at = None
        row.updated_at = _database_now(session)
        work_audit_outcome(session, receipt, "submitted")
        release_work_claims(session, receipt.work_id)
        append_outbox(
            session,
            run_id=row.run_id,
            work_id=row.work_id,
            attempt_epoch=row.attempt_epoch,
            event_type="work_submitted",
            payload={"work_kind": row.work_kind},
            cutoff_hash=row.cutoff_hash,
        )

    def fail(
        self,
        receipt: WorkReceipt,
        *,
        reason: str,
        transient: bool,
        max_attempts: int = 3,
        retry_delay_seconds: int = 5,
    ) -> str:
        """仅瞬态失败在有界预算内重新入队"""
        with self.session_factory() as session, session.begin():
            row = self.lock_owned_work(session, receipt)
            now = _database_now(session)
            retry = transient and row.attempt_count < max_attempts
            row.state = "queued" if retry else "dead_letter"
            row.available_at = now + timedelta(seconds=retry_delay_seconds if retry else 0)
            row.lease_owner = None
            row.lease_hash = None
            row.lease_expires_at = None
            row.updated_at = now
            release_work_claims(session, receipt.work_id)
            work_audit_outcome(session, receipt, "retry_queued" if retry else "dead_letter")
            append_outbox(
                session,
                run_id=row.run_id,
                work_id=row.work_id,
                attempt_epoch=row.attempt_epoch,
                event_type="work_retry" if retry else "work_dead_letter",
                payload={"reason": reason},
                cutoff_hash=row.cutoff_hash,
            )
            return row.state

    def cancel_run(self, run_id: str) -> int:
        """增加取消 epoch 并取消未领取工作，运行中的旧尝试由写入栅栏拒绝"""
        with self.session_factory() as session, session.begin():
            run = session.get(AnalysisRun, run_id, with_for_update=True)
            if run is None:
                raise ValueError(f"分析 run 不存在: {run_id}")
            if run.cancel_requested:
                return run.cancellation_epoch
            run.cancellation_epoch += 1
            run.cancel_requested = True
            for row in session.execute(
                select(AgentWorkItem).where(
                    AgentWorkItem.run_id == run_id, AgentWorkItem.state.in_(("queued", "running"))
                )
            ).scalars():
                row.state = "cancelled"
                release_work_claims(session, row.work_id)
            session.execute(update(AgentInvocation).where(
                AgentInvocation.run_id == run_id, AgentInvocation.business_outcome.in_(("running", "model_succeeded")),
            ).values(business_outcome="cancelled"))
            append_outbox(
                session,
                run_id=run_id,
                event_type="run_cancelled",
                payload={"cancellation_epoch": run.cancellation_epoch},
            )
            return run.cancellation_epoch

    def state_counts(self, run_id: str, *, work_kind: WorkKind | None = None) -> dict[str, int]:
        """协调器只读数据库状态，重启后可继续等待或报告 dead letter"""
        with self.session_factory() as session:
            statement = (
                select(AgentWorkItem.state, func.count().label("item_count"))
                .where(AgentWorkItem.run_id == run_id)
                .group_by(AgentWorkItem.state)
            )
            if work_kind is not None:
                statement = statement.where(AgentWorkItem.work_kind == work_kind)
            return {str(row.state): int(row.item_count) for row in session.execute(statement)}

    def resume_failed_work(self, run_id: str) -> int:
        """显式再次启动分析时只重置未提交项，已经成立的正式结果不重跑"""
        with self.session_factory() as session, session.begin():
            run = session.get(AnalysisRun, run_id, with_for_update=True)
            if run is None or run.cancel_requested:
                raise StaleWorkLeaseError("恢复工作前必须先恢复 run 的取消状态")
            rows = list(session.execute(select(AgentWorkItem).where(
                AgentWorkItem.run_id == run_id,
                or_(AgentWorkItem.state.in_(("dead_letter", "cancelled")),
                    and_(AgentWorkItem.state == "running", AgentWorkItem.cancellation_epoch != run.cancellation_epoch)),
            )).scalars())
            for row in rows:
                row.state = "queued"
                row.attempt_count = 0
                row.cancellation_epoch = run.cancellation_epoch
                row.available_at = _database_now(session)
                row.lease_owner = None
                row.lease_hash = None
                row.lease_expires_at = None
                release_work_claims(session, row.work_id)
            if rows:
                append_outbox(session, run_id=run_id, event_type="work_resumed", payload={"count": len(rows)})
            return len(rows)
