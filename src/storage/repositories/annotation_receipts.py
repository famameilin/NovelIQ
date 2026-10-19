"标注保存回执与章末凭据，均在 Storage 内部完成事务"

from sqlalchemy import select, text

from src.storage.models import Agent, Case, ChapterAnnotation
from src.storage.repositories.case_writes import CaseWritesRepository


def inspect_saved(session, invocation_id):
    record_id = session.scalar(select(ChapterAnnotation.record_id).where(ChapterAnnotation.agent_id == invocation_id))
    return {
        "execution": session.get(Agent, invocation_id),
        "record_id": record_id,
        "warnings": [],
    }


def save_consolidation(session, request):
    "章末核对结果与案例随正式标注来源一起保存"
    run_id, chapter_id = request["run_id"], request["chapter_id"]
    session.execute(text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"), {"key": f"fact_graph:{run_id}"})
    records = list(
        session.scalars(
            select(ChapterAnnotation).where(
                ChapterAnnotation.run_id == run_id, ChapterAnnotation.chapter_id == chapter_id
            )
        )
    )
    sources = sorted(
        ({"agent_id": str(row.agent_id), "output_id": str(row.record_id)} for row in records),
        key=lambda item: item["output_id"],
    )
    if sources != sorted(request["sources"], key=lambda item: item["output_id"]):
        raise ValueError("章末核对期间正式标注来源发生变化")
    if any(row.consolidation_digest not in (None, request["program_key"]) for row in records):
        raise ValueError("章末核对来源摘要不一致，不能覆盖")
    warnings = CaseWritesRepository(run_id).save_work(session, request["cases"])
    if warnings:
        raise ValueError(f"章末案例未成功保存: {warnings}")
    for row in records:
        row.consolidation_digest = request["program_key"]
    session.flush()
    identifiers = sorted(request["cases"].snapshot()["registrations"])
    states = {row.id: row.status for row in session.scalars(select(Case).where(Case.id.in_(identifiers)))}
    return {
        "status": "saved",
        "chapter_id": chapter_id,
        "fact_id": request["digest"],
        "author": request["author"],
        "case_ids": identifiers,
        "case_states": states,
        "issues": len(identifiers),
    }
