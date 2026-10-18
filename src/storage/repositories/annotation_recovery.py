"按正式恢复链清退无效贡献，不转换或回填历史结果"

from __future__ import annotations

from sqlalchemy import delete, select

from src.storage.models import (
    BookCase,
    CaseEntry,
    ChapterAnnotation,
    DialogueRecord,
    EventDeclaration,
    Execution,
    GraphFact,
    NarrativeLink,
    WorkItem,
)
from src.storage.repositories.case_writes import CaseWritesRepository
from src.storage.repositories.event_writes import EventWriter
from src.storage.repositories.fact_writes import FactWriter
from src.storage.repositories.queries import agents_annotation_agent as _agent_queries
from src.storage.repositories.queries import agents_annotation_chapter_consolidation as _receipt_queries
from src.storage.repositories.queries import case_pool_pool as _case_queries
from src.storage.repositories.queries import final_agents_annotation_agent as _final_agent_queries


def prune_cases(session, run_id, discard) -> None:
    repository = CaseWritesRepository(run_id)
    discard_executions = set(discard or ())
    case_ids = repository._case_ids(session)
    if not case_ids:
        return
    cases = sorted(case_ids)
    supports = list(_case_queries.case_pool_pool_load_cases_2(session, cases))
    pruned_supports: set[str] = set()
    if discard is not None:
        observation_ids: set[str] = set()
        cascade_case_ids: set[str] = set()
        if discard_executions:
            observation_ids = set(_case_queries.case_pool_pool_load_cases_6(session, discard_executions))
        if observation_ids:
            for case in _case_queries.case_pool_pool_load_cases_3(session, observation_ids):
                cascade_case_ids.add(case.case_id)
                session.delete(case)
            session.flush()
            for entry_id in sorted(observation_ids):
                session.delete(_case_queries.case_pool_pool_load_cases_7(session, entry_id))
        live_links = (
            set(
                session.scalars(
                    select(NarrativeLink.link_id).where(
                        NarrativeLink.producer_execution_id.in_(repository._run_execution_ids(session)),
                        NarrativeLink.producer_execution_id.not_in(discard_executions),
                    )
                )
            )
            if repository._run_execution_ids(session)
            else set()
        )
        for support in supports:
            if support.case_id in cascade_case_ids:
                pruned_supports.add(support.entry_id)
                continue
            if support.producer_execution_id in discard_executions:
                session.delete(support)
                pruned_supports.add(support.entry_id)
                continue
            for delivery in _case_queries.case_pool_pool_load_cases_4(session, support):
                connection_ids = set(_case_queries.case_pool_pool_load_cases_8(session, delivery))
                if connection_ids and (not connection_ids <= live_links):
                    session.delete(delivery)
        session.flush()
    kept: dict[str, list[CaseEntry]] = {}
    for support in supports:
        if support.entry_id in pruned_supports:
            continue
        kept.setdefault(str(support.case_id), []).append(support)
    for case in _case_queries.case_pool_pool_load_cases_1(session, cases):
        case_supports = kept.get(case.case_id, [])
        if not case_supports and case.pending_event_entry_id is None:
            if discard is not None:
                session.delete(case)
            continue


def discard_chapter_receipts(session, run_id: str, chapter_ids: set[int]) -> None:
    "整章废弃时撤销章末核对凭据（来源集合已失效，重建不得被旧回执阻挡）"
    from src.storage.models import CaseEntry

    if not chapter_ids:
        return
    receipts = list(
        _receipt_queries.agents_annotation_chapter_consolidation_discard_chapter_receipts_1(
            session, chapter_ids, run_id
        )
    )
    if not receipts:
        return
    supported_cases = list(
        _receipt_queries.agents_annotation_chapter_consolidation_discard_chapter_receipts_2(session, receipts)
    )
    session.execute(delete(CaseEntry).where(CaseEntry.program_work_id.in_(receipts)))
    session.execute(delete(GraphFact).where(GraphFact.program_work_id.in_(receipts)))
    session.execute(delete(WorkItem).where(WorkItem.work_id.in_(receipts)))
    if supported_cases:
        session.execute(delete(BookCase).where(BookCase.case_id.in_(supported_cases)))
    session.flush()


def discard_chapters(session, run_id, chapter_ids) -> dict:
    from sqlalchemy import select

    from src.storage.models import BookCase

    ordered_chapters = sorted(chapter_ids)
    executions = select(Execution.execution_id).where(
        Execution.run_id == run_id, Execution.chapter_id.in_(ordered_chapters)
    )
    discarded_records = select(ChapterAnnotation.record_id).where(
        ChapterAnnotation.run_id == run_id, ChapterAnnotation.chapter_id.in_(ordered_chapters)
    )
    discarded_declarations = select(EventDeclaration.declaration_id).where(
        EventDeclaration.record_id.in_(discarded_records)
    )
    discarded_dialogues = select(DialogueRecord.dialogue_id).where(DialogueRecord.creation_execution_id.in_(executions))
    session.execute(
        delete(BookCase).where(
            BookCase.automatic_declaration_id.in_(discarded_declarations)
            | BookCase.declaration_target_id.in_(discarded_declarations)
            | BookCase.dialogue_target_id.in_(discarded_dialogues)
        )
    )
    discard_chapter_receipts(session, run_id, chapter_ids)
    execution_ids = set(_final_agent_queries.final_agents_annotation_agent_recover_1(session, ordered_chapters, run_id))
    # 案例交付先释放对声明连接的 RESTRICT 引用，再删除连接和声明
    prune_cases(session, run_id, execution_ids)
    session.flush()
    FactWriter(run_id).discard_storage(session, execution_ids)
    EventWriter(run_id).discard_storage(session, execution_ids)
    session.execute(delete(DialogueRecord).where(DialogueRecord.creation_execution_id.in_(executions)))
    session.execute(delete(ChapterAnnotation).where(ChapterAnnotation.record_id.in_(discarded_records)))
    session.flush()
    records = list(_agent_queries.agents_annotation_agent_recover_1(session, run_id))
    FactWriter(run_id).rebuild_storage(session)
    session.execute(delete(Execution).where(Execution.run_id == run_id, Execution.chapter_id.in_(ordered_chapters)))
    session.flush()
    return {"records": records, "execution_ids": execution_ids}
