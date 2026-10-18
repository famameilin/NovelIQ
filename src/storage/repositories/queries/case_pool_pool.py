"case pool pool 的具名物理读取"

from __future__ import annotations

from sqlalchemy import or_, select

from src.storage.models import (
    BookCase,
    CaseEntry,
    Chapter,
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


def case_pool_pool_run_execution_ids_1(_session, value_1):
    return _session.scalars(
        select(Execution.execution_id).where(or_(Execution.run_id == value_1, Execution.session_run_id == value_1))
    )


def case_pool_pool_case_ids_1(_session, value_1):
    return _session.scalars(select(BookCase.case_id).where(BookCase.registration_run_id == value_1))


def case_pool_pool_case_ids_2(_session, execution_ids):
    return _session.scalars(
        select(CaseEntry.case_id).where(
            CaseEntry.case_id.is_not(None), CaseEntry.producer_execution_id.in_(execution_ids)
        )
    )


def case_pool_pool_case_ids_3(_session, execution_ids):
    return _session.scalars(
        select(BookCase.case_id)
        .join(CaseEntry, BookCase.pending_event_entry_id == CaseEntry.entry_id)
        .where(CaseEntry.candidate_producer_execution_id.in_(execution_ids))
    )


def case_pool_pool_case_belongs_1(_session, case):
    return _session.scalar(
        select(CaseEntry.candidate_producer_execution_id).where(CaseEntry.entry_id == case.pending_event_entry_id)
    )


def case_pool_pool_pending_observation_1(_session, contribution, reference):
    return _session.scalar(
        select(CaseEntry.entry_id).where(
            CaseEntry.candidate_producer_execution_id == contribution.author,
            CaseEntry.pending_event_reference == reference,
        )
    )


def case_pool_pool_formal_target_columns_1(_session, payload):
    return _session.get(GraphEntity, str(payload["node_id"]))


def case_pool_pool_formal_target_columns_2(_session, payload):
    return _session.get(GraphRelation, str(payload["node_id"]))


def case_pool_pool_formal_target_columns_3(_session, event_id):
    return _session.get(CompleteEvent, event_id)


def case_pool_pool_formal_target_columns_4(_session, event_id):
    return _session.get(EventDeclaration, event_id)


def case_pool_pool_ensure_case_row_1(_session, case):
    return _session.get(BookCase, case["case_id"])


def case_pool_pool_support_entry_1(_session, contribution):
    return _session.get(WorkItem, contribution.author)


def case_pool_pool_support_entry_2(_session, case_id, contribution):
    return _session.scalar(
        select(CaseEntry).where(CaseEntry.case_id == case_id, CaseEntry.producer_execution_id == contribution.author)
    )


def case_pool_pool_support_entry_3(_session, case_id, contribution):
    return _session.scalar(
        select(CaseEntry).where(CaseEntry.case_id == case_id, CaseEntry.program_work_id == contribution.author)
    )


def case_pool_pool_save_support_1(_session, fact):
    return _session.scalar(select(CaseEntry).where(CaseEntry.business_call_id == str(fact["call_id"])))


def case_pool_pool_formal_owner_1(_session, contribution):
    return _session.scalar(
        select(ChapterAnnotation.record_id).where(ChapterAnnotation.execution_id == contribution.author)
    )


def case_pool_pool_formal_owner_2(_session, contribution, value_1):
    report_statement = (
        select(DiagnosisReport.report_id)
        .join(Execution, Execution.execution_id == DiagnosisReport.session_id)
        .where(Execution.session_run_id == value_1)
    )
    return _session.scalar(report_statement.where(DiagnosisReport.session_id == contribution.author))


def case_pool_pool_formal_owner_3(_session, adopted_output_id, value_1):
    report_statement = (
        select(DiagnosisReport.report_id)
        .join(Execution, Execution.execution_id == DiagnosisReport.session_id)
        .where(Execution.session_run_id == value_1)
    )
    return _session.scalar(report_statement.where(DiagnosisReport.report_id == adopted_output_id))


def case_pool_pool_save_work_1(_session, case_id):
    return _session.get(BookCase, case_id, with_for_update=True)


def case_pool_pool_observation_for_1(_session, case):
    return _session.get(CaseEntry, case.pending_event_entry_id)


def case_pool_pool_candidate_key_for_1(_session, case, value_1):
    return _session.scalar(
        select(Chapter.text).where(Chapter.run_id == value_1, Chapter.chapter_id == case.dialogue_candidate_chapter_id)
    )


def case_pool_pool_delivery_dict_1(_session, delivery):
    return _session.scalars(select(CaseEntry.narrative_link_id).where(CaseEntry.parent_entry_id == delivery.entry_id))


def case_pool_pool_row_record_1(_session, case):
    return _session.get(DialogueRecord, case.dialogue_target_id)


def case_pool_pool_load_cases_1(_session, cases):
    return _session.scalars(select(BookCase).where(BookCase.case_id.in_(cases)))


def case_pool_pool_load_cases_2(_session, cases):
    return _session.scalars(
        select(CaseEntry).where(
            CaseEntry.case_id.in_(cases),
            or_(CaseEntry.producer_execution_id.is_not(None), CaseEntry.program_work_id.is_not(None)),
        )
    )


def case_pool_pool_load_cases_3(_session, observation_ids):
    return _session.scalars(select(BookCase).where(BookCase.pending_event_entry_id.in_(sorted(observation_ids))))


def case_pool_pool_load_cases_4(_session, support):
    return _session.scalars(select(CaseEntry).where(CaseEntry.parent_entry_id == support.entry_id))


def case_pool_pool_load_cases_5(_session, support):
    return _session.scalars(select(CaseEntry).where(CaseEntry.parent_entry_id == support.entry_id))


def case_pool_pool_load_cases_6(_session, discard_executions):
    return _session.scalars(
        select(CaseEntry.entry_id).where(CaseEntry.candidate_producer_execution_id.in_(sorted(discard_executions)))
    )


def case_pool_pool_load_cases_7(_session, entry_id):
    return _session.get(CaseEntry, entry_id)


def case_pool_pool_load_cases_8(_session, delivery):
    return _session.scalars(select(CaseEntry.narrative_link_id).where(CaseEntry.parent_entry_id == delivery.entry_id))


def case_pool_pool_load_saved_work_1(_session, annotation_id):
    return _session.get(ChapterAnnotation, annotation_id)


def case_pool_pool_load_saved_work_2(_session, execution_id):
    return _session.scalars(
        select(CaseEntry).where(CaseEntry.producer_execution_id == execution_id, CaseEntry.case_id.is_not(None))
    )


def case_pool_pool_load_saved_work_3(_session, support):
    return _session.get(BookCase, support.case_id)


def case_pool_pool_load_saved_work_4(_session, support):
    return _session.scalars(select(CaseEntry).where(CaseEntry.parent_entry_id == support.entry_id))
