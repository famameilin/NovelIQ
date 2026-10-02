"""分区确定性重算、屏障 ACK 与不可变可见快照

2026-10-02 拆分（Trae）：语义命令派生静态逻辑移至
pipeline_projection_commands.py（模块函数），本文件保留
PipelineProjectionRepository 状态机方法，调用处改为模块函数。
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from secrets import choice, token_hex
from typing import Any

from sqlalchemy import func, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from src.agents.annotation.identity import stable_digest
from src.storage.models import (
    AgentInvocation,
    AgentWorkItem,
    AnalysisCutoff,
    AnalysisRun,
    CaseHead,
    ChapterAnnotationRecord,
    CommandOutcome,
    ContinuityCase,
    CutoffPartition,
    PartitionHead,
    ProjectionWorkItem,
    SemanticCommand,
)
from src.storage.repositories.pipeline_projection_commands import (
    blocked_parent_ids,
    dependency_manifest,
    derive_chapter_links,
    derive_domain_commands,
    register_conflict_cases,
)
from src.storage.repositories.pipeline_reducers import reduce_partition
from src.storage.repositories.pipeline_source import verify_source_manifest
from src.storage.repositories.pipeline_work import ImmutableWorkConflict, append_outbox


class CutoffNotReady(RuntimeError):
    """未投影、有效 claim 或死信均不得伪装为已释放"""


class ProjectionCASConflict(RuntimeError):
    """局部竞争只重读重算，不能把并发赢家覆盖或记作业务死信"""


class PipelineProjectionRepository:
    """所有操作独立短事务，分区头与 ACK 在同一事务更新"""

    def __init__(self, session_factory: Callable[[], Session]) -> None:
        self.session_factory = session_factory
        self._projection_inputs: dict[str, dict[str, Any]] = {}

    @staticmethod
    def _lock_cutoff(session: Session, cutoff_hash: str) -> AnalysisCutoff | None:
        """所有写路径统一先锁 run 再锁 cutoff，避免释放与恢复之间形成反向等待"""
        run_id = session.execute(select(AnalysisCutoff.run_id).where(
            AnalysisCutoff.cutoff_hash == cutoff_hash,
        )).scalar_one_or_none()
        if run_id is None:
            return None
        session.get(AnalysisRun, run_id, with_for_update=True)
        return session.get(AnalysisCutoff, cutoff_hash, with_for_update=True)

    def seal(self, run_id: str, *, round_kind: str, round_number: int) -> str:
        with self.session_factory() as session, session.begin():
            run = session.get(AnalysisRun, run_id, with_for_update=True)
            if run is None or run.cancel_requested:
                raise CutoffNotReady("分析不存在或已取消")
            work = list(session.execute(select(AgentWorkItem).where(AgentWorkItem.run_id == run_id)).scalars())
            if not work or any(row.state != "submitted" for row in work):
                raise CutoffNotReady("Agent 工作尚未全部提交")
            self._check_claims(session, run_id)
            source_hash = verify_source_manifest(session, run_id)
            formal = list(session.execute(select(ChapterAnnotationRecord).where(
                ChapterAnnotationRecord.run_id == run_id
            ).order_by(ChapterAnnotationRecord.chapter_id)).scalars())
            commands = list(session.execute(select(SemanticCommand).where(
                SemanticCommand.run_id == run_id
            ).order_by(SemanticCommand.command_id)).scalars())
            derive_domain_commands(session, commands)
            derive_chapter_links(session, commands)
            session.flush()
            commands = list(session.execute(select(SemanticCommand).where(
                SemanticCommand.run_id == run_id,
            ).order_by(SemanticCommand.command_id)).scalars())
            register_conflict_cases(session, run_id, commands)
            session.flush()
            cases = list(session.execute(select(ContinuityCase.case_id, CaseHead.state, CaseHead.state_hash)
                                        .join(CaseHead).where(ContinuityCase.run_id == run_id)
                                        .order_by(ContinuityCase.case_id)).all())
            manifest: dict[str, Any] = {
                "formal": [[row.annotation_id, row.payload_hash] for row in formal],
                "commands": [[row.command_id, row.payload_hash] for row in commands],
                "cases": [{"case_id": row.case_id, "state": row.state, "state_hash": row.state_hash} for row in cases],
                "dependencies": dependency_manifest(commands),
                "source_manifest_hash": source_hash,
                "blocked_parent_ids": blocked_parent_ids(commands),
            }
            hashes = [stable_digest(manifest[key]) for key in ("formal", "commands", "cases")]
            cutoff_hash = stable_digest(run_id, round_kind, round_number, hashes)
            existing = session.execute(select(AnalysisCutoff).where(
                AnalysisCutoff.run_id == run_id, AnalysisCutoff.round_kind == round_kind,
                AnalysisCutoff.round_number == round_number,
            )).scalar_one_or_none()
            if existing is not None:
                if existing.cutoff_hash != cutoff_hash:
                    raise ImmutableWorkConflict("相同轮次的 manifest 已变化")
                return existing.cutoff_hash
            incomplete = session.execute(select(AnalysisCutoff.cutoff_hash).where(
                AnalysisCutoff.run_id == run_id, AnalysisCutoff.state != "released",
            ).limit(1)).scalar_one_or_none()
            if incomplete is not None:
                raise CutoffNotReady("上一截止快照尚未释放，必须先恢复原轮次")
            session.add(AnalysisCutoff(
                cutoff_hash=cutoff_hash, run_id=run_id, round_kind=round_kind, round_number=round_number,
                formal_manifest_hash=hashes[0], command_manifest_hash=hashes[1], case_manifest_hash=hashes[2],
                cancellation_epoch=run.cancellation_epoch, state="projecting", manifest=manifest,
            ))
            session.flush()
            partitions = sorted({command.partition_key for command in commands})
            if partitions:
                session.execute(insert(PartitionHead).values([{
                    "run_id": run_id, "partition_key": partition, "head_epoch": 0,
                    "state_hash": stable_digest([]), "projection_hash": stable_digest({}), "projection": {},
                } for partition in partitions]).on_conflict_do_nothing(index_elements=[
                    PartitionHead.run_id, PartitionHead.partition_key,
                ]))
            for item in session.execute(select(ProjectionWorkItem).where(
                ProjectionWorkItem.run_id == run_id
            )).scalars():
                item.cutoff_hash = cutoff_hash
                item.state = "queued"
                item.completed_at = None
                item.last_error = None
            append_outbox(session, run_id=run_id, event_type="cutoff_sealed",
                          payload={"round_kind": round_kind, "round_number": round_number}, cutoff_hash=cutoff_hash)
            return cutoff_hash

    @staticmethod
    def _check_claims(session: Session, run_id: str) -> None:
        active = session.execute(select(CaseHead.case_id).join(ContinuityCase).where(
            ContinuityCase.run_id == run_id,
            CaseHead.active_lease_expires_at > func.clock_timestamp(),
        ).limit(1)).scalar_one_or_none()
        if active is not None:
            raise CutoffNotReady(f"案例仍有有效 claim: {active}")

    def project_next(self, cutoff_hash: str) -> bool:
        """失败留下可恢复死信；事务回滚后没有半个 ACK 或分区头"""
        for _ in range(8):
            try:
                return self._project_attempt(cutoff_hash)
            except ProjectionCASConflict as exc:
                with self.session_factory() as session, session.begin():
                    cutoff = session.get(AnalysisCutoff, cutoff_hash)
                    if cutoff is None or cutoff.state != "projecting":
                        return False
                    append_outbox(session, run_id=cutoff.run_id, event_type="projection_cas_conflict",
                                  payload={"partition_key": str(exc), "retry_id": token_hex(16)},
                                  cutoff_hash=cutoff_hash)
        return False

    def _project_attempt(self, cutoff_hash: str) -> bool:
        attempted: list[str] = []
        try:
            return self._project_next(cutoff_hash, attempted)
        except ProjectionCASConflict:
            raise
        except Exception as exc:
            if not attempted:
                raise
            with self.session_factory() as session, session.begin():
                cutoff = self._lock_cutoff(session, cutoff_hash)
                if cutoff is not None and cutoff.state == "projecting":
                    cutoff.state = "failed"
                    for item in session.execute(select(ProjectionWorkItem).where(
                        ProjectionWorkItem.cutoff_hash == cutoff_hash, ProjectionWorkItem.state == "queued",
                        ProjectionWorkItem.partition_key == attempted[0],
                    )).scalars():
                        item.state = "dead_letter"
                        item.last_error = str(exc)
                    append_outbox(session, run_id=cutoff.run_id, event_type="projection_dead_letter",
                                  payload={"error": str(exc), "partition_key": attempted[0]}, cutoff_hash=cutoff_hash)
            raise

    def resume_projection(self, cutoff_hash: str) -> None:
        """显式恢复不重跑已提交 Agent，只重新执行未 ACK 投影"""
        with self.session_factory() as session, session.begin():
            cutoff = self._lock_cutoff(session, cutoff_hash)
            if cutoff is None or cutoff.state == "released":
                return
            run = session.get(AnalysisRun, cutoff.run_id, with_for_update=True)
            if run is None or run.cancel_requested:
                raise CutoffNotReady("恢复投影前必须恢复分析")
            if run.cancellation_epoch != cutoff.cancellation_epoch:
                cutoff.cancellation_epoch = run.cancellation_epoch
            cutoff.state = "projecting"
            for item in session.execute(select(ProjectionWorkItem).where(
                ProjectionWorkItem.cutoff_hash == cutoff_hash, ProjectionWorkItem.state == "dead_letter",
            )).scalars():
                item.state = "queued"
                item.last_error = None

    def _project_next(self, cutoff_hash: str, attempted: list[str]) -> bool:
        """无分区锁读取固定命令，head_epoch 与双哈希 CAS 后同事务 ACK"""
        with self.session_factory() as session, session.begin():
            cutoff = session.execute(select(
                AnalysisCutoff.run_id, AnalysisCutoff.state, AnalysisCutoff.cancellation_epoch,
            ).where(AnalysisCutoff.cutoff_hash == cutoff_hash)).one_or_none()
            if cutoff is None or cutoff.state != "projecting":
                return False
            run = session.get(AnalysisRun, cutoff.run_id, with_for_update={"read": True})
            if run is None or run.cancel_requested or run.cancellation_epoch != cutoff.cancellation_epoch:
                raise CutoffNotReady("投影已被取消栅栏拒绝")
            candidates = session.execute(select(ProjectionWorkItem.partition_key).where(
                ProjectionWorkItem.cutoff_hash == cutoff_hash,
                ProjectionWorkItem.state == "queued",
                ProjectionWorkItem.available_at <= func.clock_timestamp(),
            ).distinct().order_by(ProjectionWorkItem.partition_key).limit(32)).scalars()
            available = list(candidates)
            partition = choice(available) if available else None
            if partition is None:
                return False
            items = list(session.execute(select(ProjectionWorkItem).where(
                ProjectionWorkItem.cutoff_hash == cutoff_hash, ProjectionWorkItem.partition_key == partition,
                ProjectionWorkItem.state == "queued",
            )).scalars())
            if not items:
                return False
            attempted.append(partition)
            if cutoff_hash not in self._projection_inputs:
                manifest = session.execute(select(AnalysisCutoff.manifest).where(
                    AnalysisCutoff.cutoff_hash == cutoff_hash,
                )).scalar_one()
                self._projection_inputs[cutoff_hash] = {
                    "blocked_parent_ids": manifest.get("blocked_parent_ids", []),
                    "dependencies": manifest.get("dependencies"),
                }
            inputs = self._projection_inputs[cutoff_hash]
            head = session.get(PartitionHead, (cutoff.run_id, partition))
            assert head is not None
            commands = list(session.execute(select(SemanticCommand).join(
                ProjectionWorkItem, ProjectionWorkItem.command_id == SemanticCommand.command_id,
            ).where(
                SemanticCommand.run_id == cutoff.run_id,
                SemanticCommand.partition_key == partition,
                ProjectionWorkItem.cutoff_hash == cutoff_hash,
            )).scalars())
            blocked = set(inputs["blocked_parent_ids"])
            active_commands = [row for row in commands if row.parent_command_id not in blocked]
            projection, outcomes = reduce_partition(active_commands, dependencies=inputs["dependencies"])
            for row in commands:
                if row.parent_command_id in blocked:
                    outcomes[row.command_id] = "conflict"
            projection["blocked_commands"] = sorted(row.command_id for row in commands
                                                     if row.parent_command_id in blocked)
            state_hash = stable_digest(sorted((row.command_id, row.payload_hash) for row in commands))
            projection_hash = stable_digest(projection)
            head_epoch = self._compare_and_swap_head(
                session, head, state_hash=state_hash, projection_hash=projection_hash, projection=projection,
            )
            session.execute(insert(CutoffPartition).values(
                cutoff_hash=cutoff_hash, partition_key=partition,
                projection=projection, projection_hash=projection_hash,
            ).on_conflict_do_nothing(index_elements=[CutoffPartition.cutoff_hash, CutoffPartition.partition_key]))
            snapshot = session.get(CutoffPartition, (cutoff_hash, partition))
            if snapshot is None or snapshot.projection_hash != projection_hash:
                raise ImmutableWorkConflict("cutoff 分区快照发生变化")
            for command in commands:
                session.execute(insert(CommandOutcome).values(
                    command_id=command.command_id, state=outcomes[command.command_id], partition_key=partition,
                    head_epoch=head_epoch, state_hash=state_hash,
                    reason_code="mutually_exclusive_claims" if projection["contested"] else None,
                    resolved_at=datetime.now(UTC),
                ).on_conflict_do_update(index_elements=[CommandOutcome.command_id], set_={
                    "state": outcomes[command.command_id], "head_epoch": head_epoch,
                    "state_hash": state_hash, "resolved_at": datetime.now(UTC),
                }))
            for item in items:
                item.state = "ack"
                item.attempt_epoch += 1
                item.completed_at = datetime.now(UTC)
            append_outbox(session, run_id=cutoff.run_id, event_type="partition_projected",
                          payload={"partition_key": partition, "projection_hash": projection_hash},
                          cutoff_hash=cutoff_hash)
            return True

    @staticmethod
    def _compare_and_swap_head(
        session: Session, head: PartitionHead, *, state_hash: str, projection_hash: str, projection: dict[str, Any],
    ) -> int:
        next_epoch = head.head_epoch + int(head.state_hash != state_hash or head.projection_hash != projection_hash)
        next_value = session.execute(update(PartitionHead).where(
            PartitionHead.run_id == head.run_id, PartitionHead.partition_key == head.partition_key,
            PartitionHead.head_epoch == head.head_epoch, PartitionHead.state_hash == head.state_hash,
            PartitionHead.projection_hash == head.projection_hash,
        ).values(head_epoch=next_epoch, state_hash=state_hash, projection_hash=projection_hash,
                 projection=projection, updated_at=datetime.now(UTC)).returning(PartitionHead.head_epoch)
            .execution_options(synchronize_session=False)).scalar_one_or_none()
        if next_value is None:
            raise ProjectionCASConflict(head.partition_key)
        return next_value

    def release(self, cutoff_hash: str, *, materialize: Callable[[Session, AnalysisCutoff], None]) -> None:
        """释放物化失败独立留痕，可恢复投影而不重新调用模型"""
        attempted: list[bool] = []
        try:
            self._release(cutoff_hash, materialize=materialize, attempted=attempted)
        except Exception as exc:
            if attempted:
                with self.session_factory() as session, session.begin():
                    cutoff = self._lock_cutoff(session, cutoff_hash)
                    if cutoff is not None and cutoff.state == "projecting":
                        cutoff.state = "failed"
                        append_outbox(session, run_id=cutoff.run_id, event_type="cutoff_materialization_failed",
                                      payload={"error": str(exc)}, cutoff_hash=cutoff_hash)
            raise

    def projection_progress(self, cutoff_hash: str) -> tuple[str, dict[str, int]]:
        """CAS 重试让出工作时仍可能有 queued 分区，协调器按持久状态等待"""
        with self.session_factory() as session:
            state = session.execute(select(AnalysisCutoff.state).where(
                AnalysisCutoff.cutoff_hash == cutoff_hash,
            )).scalar_one_or_none()
            if state is None:
                raise CutoffNotReady("cutoff 不存在")
            counts = session.execute(select(ProjectionWorkItem.state, func.count().label("item_count")).where(
                ProjectionWorkItem.cutoff_hash == cutoff_hash,
            ).group_by(ProjectionWorkItem.state))
            return state, {row.state: row.item_count for row in counts}

    def _release(
        self, cutoff_hash: str, *, materialize: Callable[[Session, AnalysisCutoff], None], attempted: list[bool],
    ) -> None:
        """读模型物化与 released 同事务提交，消费者不会见到半套图"""
        with self.session_factory() as session, session.begin():
            cutoff = self._lock_cutoff(session, cutoff_hash)
            if cutoff is None:
                raise CutoffNotReady("cutoff 不存在")
            if cutoff.state == "released":
                return
            if cutoff.state != "projecting":
                raise CutoffNotReady("失败的 cutoff 必须先显式恢复投影")
            run = session.get(AnalysisRun, cutoff.run_id, with_for_update=True)
            if run is None or run.cancel_requested or run.cancellation_epoch != cutoff.cancellation_epoch:
                raise CutoffNotReady("cutoff 已被取消栅栏拒绝")
            self._check_claims(session, cutoff.run_id)
            if verify_source_manifest(session, cutoff.run_id) != cutoff.manifest["source_manifest_hash"]:
                raise CutoffNotReady("原文 manifest 发生变化")
            states = list(session.execute(select(ProjectionWorkItem.state).where(
                ProjectionWorkItem.cutoff_hash == cutoff_hash
            )).scalars())
            if any(state != "ack" for state in states):
                raise CutoffNotReady("存在未 ACK 或 dead letter 的投影")
            commands = list(session.execute(select(SemanticCommand.command_id, SemanticCommand.payload_hash)
                                           .where(SemanticCommand.run_id == cutoff.run_id)
                                           .order_by(SemanticCommand.command_id)).all())
            if stable_digest([[row.command_id, row.payload_hash] for row in commands]) != cutoff.command_manifest_hash:
                raise CutoffNotReady("固定 manifest 后出现了新命令")
            formal = session.execute(select(ChapterAnnotationRecord).where(
                ChapterAnnotationRecord.run_id == cutoff.run_id,
            ).order_by(ChapterAnnotationRecord.chapter_id)).scalars()
            if stable_digest([[row.annotation_id, row.payload_hash] for row in formal]) != cutoff.formal_manifest_hash:
                raise CutoffNotReady("固定 manifest 后正式结果发生变化")
            cases = session.execute(select(ContinuityCase.case_id, CaseHead.state, CaseHead.state_hash)
                                    .join(CaseHead).where(ContinuityCase.run_id == cutoff.run_id)
                                    .order_by(ContinuityCase.case_id))
            if stable_digest([{"case_id": row.case_id, "state": row.state, "state_hash": row.state_hash}
                              for row in cases]) != cutoff.case_manifest_hash:
                raise CutoffNotReady("固定 manifest 后案例状态发生变化")
            attempted.append(True)
            materialize(session, cutoff)
            cutoff.state = "released"
            cutoff.released_at = datetime.now(UTC)
            session.execute(update(AgentInvocation).where(
                AgentInvocation.run_id == cutoff.run_id, AgentInvocation.business_outcome == "submitted",
            ).values(business_outcome="projected"))
            append_outbox(session, run_id=cutoff.run_id, event_type="cutoff_released",
                          payload={"round_kind": cutoff.round_kind, "round_number": cutoff.round_number},
                          cutoff_hash=cutoff_hash)

    def latest_released(self, run_id: str) -> dict[str, Any] | None:
        with self.session_factory() as session:
            row = session.execute(select(AnalysisCutoff).where(
                AnalysisCutoff.run_id == run_id, AnalysisCutoff.state == "released",
            ).order_by(AnalysisCutoff.released_at.desc(), AnalysisCutoff.cutoff_hash).limit(1)).scalar_one_or_none()
            if row is None:
                return None
            return {"cutoff_hash": row.cutoff_hash, "round_kind": row.round_kind,
                    "round_number": row.round_number, "manifest": row.manifest}
