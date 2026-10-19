"按正式恢复链清退无效贡献，不转换或回填历史结果"

from __future__ import annotations

from sqlalchemy import delete, select

from src.storage.models import (
    Agent,
    Case,
    ChapterAnnotation,
    DialogueRecord,
)
from src.storage.repositories.event_writes import EventWriter
from src.storage.repositories.fact_writes import FactWriter
from src.storage.repositories.queries import agents_annotation_agent as _agent_queries
from src.storage.repositories.queries import final_agents_annotation_agent as _final_agent_queries


def prune_cases(session, run_id, discard) -> None:
    "撤销同一正式生成链中失效 Agent 登记的案例"
    identifiers = set(discard or ())
    if identifiers:
        session.execute(delete(Case).where(Case.run_id == run_id, Case.producer_agent_id.in_(identifiers)))


def discard_chapter_receipts(session, run_id: str, chapter_ids: set[int]) -> None:
    "标注来源失效时清除所属产出上的核对摘要"
    from sqlalchemy import update

    session.execute(
        update(ChapterAnnotation)
        .where(ChapterAnnotation.run_id == run_id, ChapterAnnotation.chapter_id.in_(chapter_ids))
        .values(consolidation_digest=None)
    )


def discard_chapters(session, run_id, chapter_ids) -> dict:

    ordered_chapters = sorted(chapter_ids)
    executions = list(
        session.scalars(
            select(Agent.id).where(
                Agent.run_id == run_id,
                Agent.id.in_(
                    select(ChapterAnnotation.agent_id).where(
                        ChapterAnnotation.run_id == run_id, ChapterAnnotation.chapter_id.in_(ordered_chapters)
                    )
                ),
            )
        )
    )
    discarded_records = select(ChapterAnnotation.record_id).where(
        ChapterAnnotation.run_id == run_id, ChapterAnnotation.chapter_id.in_(ordered_chapters)
    )
    discard_chapter_receipts(session, run_id, chapter_ids)
    execution_ids = set(_final_agent_queries.final_agents_annotation_agent_recover_1(session, ordered_chapters, run_id))
    prune_cases(session, run_id, execution_ids)
    session.flush()
    FactWriter(run_id).discard_storage(session, execution_ids)
    EventWriter(run_id).discard_storage(session, execution_ids)
    session.execute(delete(DialogueRecord).where(DialogueRecord.creation_agent_id.in_(executions)))
    session.execute(delete(ChapterAnnotation).where(ChapterAnnotation.record_id.in_(discarded_records)))
    session.flush()
    records = list(_agent_queries.agents_annotation_agent_recover_1(session, run_id))
    FactWriter(run_id).rebuild_storage(session)
    session.flush()
    return {"records": records, "execution_ids": execution_ids}
