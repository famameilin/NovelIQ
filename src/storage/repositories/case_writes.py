"案例记录映射及局部保存点，仅由 Storage 完整操作调用"

from __future__ import annotations

import json
from copy import deepcopy
from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from src.storage.ids import new_id
from src.storage.models import (
    BookCase,
    CaseEntry,
    ChapterAnnotation,
    CompleteEvent,
    DiagnosisReport,
    DialogueRecord,
    EventDeclaration,
    Execution,
    GraphEntity,
    GraphRelation,
    WorkItem,
)
from src.storage.records.cases import CaseSave

_CASE_CONFLICT_SQLSTATES = {"23503", "23505", "23514"}


def _receipt_bytes(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True).encode("utf-8")


class CaseWritesRepository:
    "真实外键检查、幂等写入和保存点均由 Storage 内部持有"

    def __init__(self, run_id: str):
        self.run_id = run_id

    def _run_execution_ids(self, session: Session) -> set[str]:
        "本运行的真实执行：执行行直接携带运行归属（调用形状或整轮会话形状）"
        return set(
            session.scalars(
                select(Execution.execution_id).where(
                    or_(Execution.run_id == self.run_id, Execution.session_run_id == self.run_id)
                )
            )
        )

    def _case_ids(self, session: Session) -> set[str]:
        "本 run 案例集合：无目标登记按真实运行；正式目标/候选观察按真实生产者身份"
        case_ids = set(session.scalars(select(BookCase.case_id).where(BookCase.registration_run_id == self.run_id)))
        execution_ids = self._run_execution_ids(session)
        if execution_ids:
            case_ids |= set(
                session.scalars(
                    select(CaseEntry.case_id).where(
                        CaseEntry.case_id.is_not(None), CaseEntry.producer_execution_id.in_(execution_ids)
                    )
                )
            )
            case_ids |= set(
                session.scalars(
                    select(BookCase.case_id)
                    .join(CaseEntry, BookCase.pending_event_entry_id == CaseEntry.entry_id)
                    .where(CaseEntry.candidate_producer_execution_id.in_(execution_ids))
                )
            )
        case_ids |= set(
            session.scalars(
                select(CaseEntry.case_id).where(
                    CaseEntry.case_id.is_not(None), CaseEntry.program_work_id.in_(self._run_program_work_ids())
                )
            )
        )
        return case_ids

    def _run_program_work_ids(self):
        "本 run 的程序形状 work：章末核对按运行归属、诊断失败保留按整轮会话归属"
        return select(WorkItem.work_id).where(
            or_(
                WorkItem.program_run_id == self.run_id,
                WorkItem.diagnosis_session_id.in_(
                    select(Execution.execution_id).where(Execution.session_run_id == self.run_id)
                ),
            )
        )

    def _case_belongs(self, session: Session, case: BookCase) -> bool:
        "案例归属校验：登记运行或真实生产者执行必须属于本 run"
        if case.registration_run_id is not None:
            return case.registration_run_id == self.run_id
        execution_ids = self._run_execution_ids(session)
        if case.pending_event_entry_id is not None:
            producer = session.scalar(
                select(CaseEntry.candidate_producer_execution_id).where(
                    CaseEntry.entry_id == case.pending_event_entry_id
                )
            )
            return producer in execution_ids
        return (
            session.scalar(
                select(CaseEntry.entry_id).where(
                    CaseEntry.case_id == case.case_id,
                    or_(
                        CaseEntry.producer_execution_id.in_(execution_ids),
                        CaseEntry.program_work_id.in_(self._run_program_work_ids()),
                    ),
                )
            )
            is not None
        )

    def _pending_observation(self, session: Session, contribution: CaseSave, payload: dict[str, Any]) -> str:
        "诊断失败候选观察：同一 (真实执行, 候选标识) 只存一次，多个案例共同引用"
        reference = str(payload.get("event_id") or payload.get("node_id") or "")
        if not reference:
            raise ValueError("未发布事件候选缺少候选标识")
        chapter_id = payload.get("chapter_id")
        if chapter_id is None:
            raise ValueError("未发布事件候选缺少来源章")
        existing = session.scalar(
            select(CaseEntry.entry_id).where(
                CaseEntry.candidate_producer_execution_id == contribution.author,
                CaseEntry.pending_event_reference == reference,
            )
        )
        if existing is not None:
            return str(existing)
        title = str(payload.get("name") or payload.get("title") or reference)[:255]
        entry = CaseEntry(
            entry_id=new_id(),
            candidate_producer_execution_id=contribution.author,
            pending_event_reference=reference,
            pending_event_title=title,
            pending_event_chapter_id=int(chapter_id),
        )
        session.add(entry)
        session.flush()
        return entry.entry_id

    def _formal_target_columns(self, session: Session, case: dict[str, Any], contribution: CaseSave) -> dict[str, Any]:
        "payload 定位键 → book_cases 正式目标/候选列；不能落库的目标明确报错"
        payload = case.get("payload") or {}
        case_type = case["case_type"]
        values: dict[str, Any] = {}
        if case_type == "character" and payload.get("node_id"):
            entity = session.get(GraphEntity, str(payload["node_id"]))
            if entity is None:
                raise ValueError(f"人物案例目标实体不存在: {payload['node_id']}")
            values["entity_target_id"] = entity.entity_id
        elif case_type == "relation" and payload.get("node_id"):
            relation = session.get(GraphRelation, str(payload["node_id"]))
            if relation is None:
                raise ValueError(f"关系案例目标不存在: {payload['node_id']}")
            values["relation_target_id"] = relation.relation_id
        elif case_type == "dialogue":
            candidate_key = payload.get("candidate_key")
            chapter_id = payload.get("chapter_id")
            if candidate_key and chapter_id is not None:
                record = session.scalar(
                    select(DialogueRecord).where(
                        DialogueRecord.candidate_key == str(candidate_key),
                        DialogueRecord.creation_execution_id.in_(self._run_execution_ids(session)),
                    )
                )
                if record is not None:
                    values["dialogue_target_id"] = record.dialogue_id
                else:
                    start, end = (payload.get("start"), payload.get("end"))
                    if not isinstance(start, int) or not isinstance(end, int):
                        raise ValueError("对话候选缺少正式记录与真实章节区间 start/end")
                    values["dialogue_candidate_chapter_id"] = int(chapter_id)
                    values["dialogue_candidate_start"] = start
                    values["dialogue_candidate_end"] = end
        elif case_type == "event":
            event_id = str(payload.get("event_id") or payload.get("node_id") or "")
            if event_id:
                if session.get(CompleteEvent, event_id) is not None:
                    values["complete_event_target_id"] = event_id
                elif session.get(EventDeclaration, event_id) is not None:
                    if bool(case.get("automatic")):
                        values["automatic_declaration_id"] = event_id
                    else:
                        values["declaration_target_id"] = event_id
                else:
                    values["pending_event_entry_id"] = self._pending_observation(session, contribution, payload)
        return values

    def _ensure_case_row(self, session: Session, case: dict[str, Any], contribution: CaseSave) -> BookCase:
        "幂等登记案例行；已存在时只校验归属，不改写既有业务字段"
        existing = session.get(BookCase, case["case_id"])
        if existing is not None:
            if not self._case_belongs(session, existing):
                raise ValueError(f"case_id={case['case_id']} 不属于当前 run")
            return existing
        payload = case.get("payload") or {}
        values: dict[str, Any] = {
            "case_id": case["case_id"],
            "case_type": case["case_type"],
            "description": case["description"],
            "registration_run_id": self.run_id,
        }
        reason = payload.get("reason")
        if isinstance(reason, str) and reason:
            values["registration_reason"] = reason
        paragraph_id = payload.get("paragraph_id")
        if isinstance(paragraph_id, int):
            values["registration_paragraph_id"] = paragraph_id
        values.update(self._formal_target_columns(session, case, contribution))
        if any(
            values.get(name) is not None
            for name in (
                "automatic_declaration_id",
                "entity_target_id",
                "relation_target_id",
                "dialogue_target_id",
                "declaration_target_id",
                "complete_event_target_id",
                "pending_event_entry_id",
            )
        ):
            values["registration_run_id"] = None
        row = BookCase(**values)
        session.add(row)
        session.flush()
        return row

    def _support_entry(self, session: Session, case_id: str, contribution: CaseSave, adopted: bool) -> CaseEntry:
        "Agent 支持/贡献：每 (case, producer execution) 一行，不伪造第二份支持"
        work = session.get(WorkItem, contribution.author)
        if work is not None:
            existing = session.scalar(
                select(CaseEntry).where(CaseEntry.case_id == case_id, CaseEntry.program_work_id == contribution.author)
            )
            if existing is not None:
                return existing
            entry = CaseEntry(entry_id=new_id(), case_id=case_id, program_work_id=contribution.author)
            session.add(entry)
            session.flush()
            return entry
        existing = session.scalar(
            select(CaseEntry).where(
                CaseEntry.case_id == case_id, CaseEntry.producer_execution_id == contribution.author
            )
        )
        if existing is not None:
            existing.adopted = bool(existing.adopted) or adopted
            return existing
        entry = CaseEntry(
            entry_id=new_id(), case_id=case_id, producer_execution_id=contribution.author, adopted=adopted
        )
        session.add(entry)
        session.flush()
        return entry

    def _save_support(
        self, session: Session, case: BookCase, contribution: CaseSave, facts: list[dict[str, Any]]
    ) -> None:
        "支持→交付→连接：只引用直接父条目，业务 call_id 全局唯一"
        adopted = any(bool(fact.get("is_write")) for fact in facts)
        support = self._support_entry(session, case.case_id, contribution, adopted)
        for fact in facts:
            delivery = session.scalar(select(CaseEntry).where(CaseEntry.business_call_id == str(fact["call_id"])))
            if delivery is None:
                delivery = CaseEntry(
                    entry_id=new_id(),
                    parent_entry_id=support.entry_id,
                    business_call_id=str(fact["call_id"]),
                    accepted_order=int(fact["accepted_order"]),
                    tool_name=str(fact["tool_name"]),
                    receipt_bytes=_receipt_bytes(fact.get("receipt")),
                )
                session.add(delivery)
                session.flush()
            elif delivery.parent_entry_id != support.entry_id:
                raise ValueError(f"业务调用 ID 已属于其他交付: {fact['call_id']}")
            for link_id in fact.get("connections") or []:
                exists = session.scalar(
                    select(CaseEntry.entry_id).where(
                        CaseEntry.parent_entry_id == delivery.entry_id, CaseEntry.narrative_link_id == str(link_id)
                    )
                )
                if exists is None:
                    session.add(
                        CaseEntry(entry_id=new_id(), parent_entry_id=delivery.entry_id, narrative_link_id=str(link_id))
                    )

    def _formal_owner(
        self, session: Session, contribution: CaseSave, adopted_output_id: str | None
    ) -> tuple[str | None, str | None]:
        "正式产物 owner：标注尝试记录或诊断发布报告（告警行归属不伪造）"
        record_id = session.scalar(
            select(ChapterAnnotation.record_id).where(ChapterAnnotation.execution_id == contribution.author)
        )
        if record_id is not None:
            return (str(record_id), None)
        report_statement = (
            select(DiagnosisReport.report_id)
            .join(Execution, Execution.execution_id == DiagnosisReport.session_id)
            .where(Execution.session_run_id == self.run_id)
        )
        if adopted_output_id:
            report_id = session.scalar(report_statement.where(DiagnosisReport.report_id == adopted_output_id))
            if report_id is not None:
                return (None, str(report_id))
        report_id = session.scalar(report_statement.where(DiagnosisReport.session_id == contribution.author))
        if report_id is not None:
            return (None, str(report_id))
        return (None, None)

    def _save_warnings(
        self,
        session: Session,
        record_id: str | None,
        report_id: str | None,
        warnings: list[dict[str, Any]],
        author: str,
    ) -> None:
        "真实保存告警逐条落 case_entries 的告警形状；无正式 owner 时只返回给调用方"
        for ordinal, item in enumerate(warnings):
            reference = str(item.get("caseid") or item.get("code") or "unknown")[:255]
            message = str(item.get("message") or item)
            if record_id is not None:
                session.add(
                    CaseEntry(
                        entry_id=new_id(),
                        warning_record_id=record_id,
                        warning_ordinal=ordinal,
                        attempted_case_reference=reference,
                        warning_message=message,
                    )
                )
            elif report_id is not None:
                session.add(
                    CaseEntry(
                        entry_id=new_id(),
                        warning_report_id=report_id,
                        producer_execution_id=author,
                        warning_ordinal=ordinal,
                        attempted_case_reference=reference,
                        warning_message=message,
                    )
                )
        session.flush()

    def save_work(
        self, session: Session, contribution: CaseSave, *, adopted_output_id: str | None = None
    ) -> list[dict[str, Any]]:
        "登记案例是主体业务；可选交付单独 savepoint，失败不撤销正式产物"
        from sqlalchemy.exc import DBAPIError

        frozen = contribution.snapshot()
        warnings: list[dict[str, Any]] = []
        failed_ids: set[str] = set()
        created_ids = set(frozen["created_case_ids"])
        record_id, report_id = self._formal_owner(session, contribution, adopted_output_id)

        def failed(case_id: str, exc: Exception) -> None:
            if case_id in failed_ids:
                return
            failed_ids.add(case_id)
            warnings.append({"code": "case_save_failed", "caseid": case_id, "message": str(exc)})

        for case_id in sorted(frozen["created_case_ids"]):
            case = frozen["registrations"][case_id]
            try:
                with session.begin_nested():
                    self._ensure_case_row(session, case, contribution)
            except (OSError, TimeoutError):
                raise
            except DBAPIError as exc:
                if exc.connection_invalidated or str(getattr(exc.orig, "sqlstate", "")) not in _CASE_CONFLICT_SQLSTATES:
                    raise
                failed(case_id, exc)
            except ValueError as exc:
                failed(case_id, exc)
        for case_id in sorted(frozen["registrations"]):
            facts = deepcopy([item for item in frozen["deliveries"] if item["case_id"] == case_id])
            try:
                with session.begin_nested():
                    state = session.get(BookCase, case_id, with_for_update=True)
                    if state is None or (case_id not in created_ids and (not self._case_belongs(session, state))):
                        raise ValueError(f"case_id={case_id} 不属于当前 run")
                    self._save_support(session, state, contribution, facts)
            except (OSError, TimeoutError):
                raise
            except DBAPIError as exc:
                if exc.connection_invalidated or str(getattr(exc.orig, "sqlstate", "")) not in _CASE_CONFLICT_SQLSTATES:
                    raise
                failed(case_id, exc)
            except ValueError as exc:
                failed(case_id, exc)
        if warnings:
            self._save_warnings(session, record_id, report_id, warnings, contribution.author)
        return warnings
