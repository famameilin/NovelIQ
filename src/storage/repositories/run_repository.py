"运行身份与按运行删除的存储操作"

from __future__ import annotations

from typing import Any, cast
from uuid import UUID

from sqlalchemy import delete, or_, select, update
from sqlalchemy.engine import CursorResult

from src.storage.ids import new_id, new_task_id
from src.storage.models import Base, Run
from src.storage.records.sentinels import UNSET
from src.storage.repositories.base import BaseRepository


def _run_purge_predicates(run_id: str) -> dict[str, Any]:
    tables = Base.metadata.tables

    def ids(name, key, condition):
        return select(tables[name].c[key]).where(condition)

    agents = ids("agent", "id", tables["agent"].c.run_id == run_id)
    annotations = ids("agent_annotations", "record_id", tables["agent_annotations"].c.run_id == run_id)
    reports = ids("diagnosis_reports", "report_id", tables["diagnosis_reports"].c.agent_id.in_(agents))
    events = ids("event_records", "event_id", tables["event_records"].c.producer_agent_id.in_(agents))
    participants = ids("event_participants", "participant_id", tables["event_participants"].c.event_id.in_(events))
    facts = ids(
        "graph_facts",
        "graph_fact_id",
        or_(
            tables["graph_facts"].c.direct_producer_agent_id.in_(agents),
            tables["graph_facts"].c.participant_id.in_(participants),
        ),
    )
    loops = ids(
        "agent_loop",
        "id",
        or_(tables["agent_loop"].c.agent_id.in_(agents), tables["agent_loop"].c.standalone_run_id == run_id),
    )
    predicates = {}
    for name, table in tables.items():
        if name == "novels":
            continue
        if name == "runs":
            predicates[name] = table.c.id == run_id
        elif "run_id" in table.c:
            predicates[name] = table.c.run_id == run_id
        elif "producer_agent_id" in table.c:
            predicates[name] = table.c.producer_agent_id.in_(agents)
    predicates.update(
        {
            "agent_loop": or_(
                tables["agent_loop"].c.agent_id.in_(agents), tables["agent_loop"].c.standalone_run_id == run_id
            ),
            "agent_toolcall": tables["agent_toolcall"].c.agentloop_id.in_(loops),
            "diagnosis_reports": tables["diagnosis_reports"].c.agent_id.in_(agents),
            "agent_assessments": or_(
                tables["agent_assessments"].c.record_id.in_(annotations),
                tables["agent_assessments"].c.report_id.in_(reports),
            ),
            "event_participants": tables["event_participants"].c.event_id.in_(events),
            "graph_facts": tables["graph_facts"].c.graph_fact_id.in_(facts),
            "graph_fact_entity_tags": tables["graph_fact_entity_tags"].c.graph_fact_id.in_(facts),
        }
    )
    for name, _key in [
        ("event_records", "event_id"),
        ("event_groups", "group_id"),
        ("event_links", "link_id"),
        ("event_checks", "check_id"),
        ("event_foreshadowing_actions", "action_id"),
    ]:
        predicates[name] = tables[name].c.producer_agent_id.in_(agents)
    events = ids("event_records", "event_id", predicates["event_records"])
    evidence = tables["paragraph_evidence"].c
    predicates["paragraph_evidence"] = or_(
        evidence.graph_fact_id.in_(facts),
        evidence.complete_event_id.in_(events),
        evidence.narrative_group_id.in_(ids("event_groups", "group_id", predicates["event_groups"])),
        evidence.narrative_link_id.in_(ids("event_links", "link_id", predicates["event_links"])),
        evidence.foreshadow_action_id.in_(
            ids("event_foreshadowing_actions", "action_id", predicates["event_foreshadowing_actions"])
        ),
        evidence.check_id.in_(ids("event_checks", "check_id", predicates["event_checks"])),
    )
    predicates["graph_relations"] = tables["graph_relations"].c.from_entity_id.in_(
        ids("graph_entities", "entity_id", tables["graph_entities"].c.run_id == run_id)
    )
    predicates["paragraph_arcs"] = tables["paragraph_arcs"].c.dependent_span_id.in_(
        ids("paragraph_spans", "span_id", tables["paragraph_spans"].c.run_id == run_id)
    )
    return predicates


_RUN_PURGE_ORDER = tuple(table.name for table in reversed(Base.metadata.sorted_tables) if table.name != "novels")


class RunRepository(BaseRepository[dict[str, Any]]):
    "任务身份与状态，不保存运行明细"

    @staticmethod
    def _record(row: Run) -> dict[str, Any]:
        return {
            "run_id": row.id,
            "novel_id": row.novelid,
            "task_id": row.taskid,
            "status": row.status,
            "lda_completed": row.lda_completed,
            "w2v_completed": row.w2v_completed,
        }

    def create_run(self, novel_id: str, run_id: str | None = None, task_id: str | None = None) -> str:
        run_id = run_id or new_id()
        if UUID(run_id).version != 7:
            raise ValueError("运行主键必须为 UUIDv7")
        task_id = task_id or new_task_id()
        if len(task_id) != 8:
            raise ValueError("任务短 ID 必须为 8 位")
        self.session.add(Run(id=run_id, novelid=novel_id, taskid=task_id, status="pending"))
        self.session.flush()
        return run_id

    def get_run(self, run_id: str) -> dict[str, Any] | None:
        row = self.session.get(Run, run_id)
        return self._record(row) if row is not None else None

    def get_run_by_task_id(self, task_id: str) -> dict[str, Any] | None:
        row = self.session.scalar(select(Run).where(Run.taskid == task_id))
        return self._record(row) if row is not None else None

    def get_runs_by_novel(self, novel_id: str) -> list[dict[str, Any]]:
        return [
            self._record(row)
            for row in self.session.scalars(select(Run).where(Run.novelid == novel_id).order_by(Run.id.desc()))
        ]

    def get_by_status(self, status: str) -> list[dict[str, Any]]:
        return [
            self._record(row) for row in self.session.scalars(select(Run).where(Run.status == status).order_by(Run.id))
        ]

    def get_pending_tasks(self) -> list[dict[str, Any]]:
        return self.get_by_status("pending")

    def claim_pending_run(self, run_id: str) -> bool:
        result = self.session.execute(
            update(Run).where(Run.id == run_id, Run.status == "pending").values(status="running")
        )
        self.session.flush()
        return bool(cast(CursorResult[Any], result).rowcount)

    def cancel_pending_run(self, run_id: str) -> bool:
        "仅取消尚未被领取的任务"
        result = self.session.execute(
            update(Run).where(Run.id == run_id, Run.status == "pending").values(status="cancelled")
        )
        self.session.flush()
        return bool(cast(CursorResult[Any], result).rowcount)

    def update_run_task_fields(self, run_id: str, *, status: str | object = UNSET) -> None:
        if status is not UNSET:
            self.session.execute(update(Run).where(Run.id == run_id).values(status=status))
            self.session.flush()

    def delete_run(self, run_id: str) -> bool:
        if self.session.get(Run, run_id) is None:
            return False
        predicates = _run_purge_predicates(run_id)
        for table in reversed(Base.metadata.sorted_tables):
            if table.name in predicates:
                self.session.execute(delete(table).where(predicates[table.name]))
        self.session.flush()
        return True

    def mark_running_as_failed(self) -> int:
        result = self.session.execute(update(Run).where(Run.status == "running").values(status="failed"))
        return int(cast(CursorResult[Any], result).rowcount or 0)

    def mark_cancelling_as_cancelled(self) -> int:
        result = self.session.execute(update(Run).where(Run.status == "cancelling").values(status="cancelled"))
        return int(cast(CursorResult[Any], result).rowcount or 0)
