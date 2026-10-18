"标注保存回执与章末凭据，均在 Storage 内部完成事务"

from sqlalchemy import select, text

from src.storage.models import BookCase, CaseEntry, ChapterAnnotation, Execution, GraphFact, WorkItem
from src.storage.repositories.case_writes import CaseWritesRepository


def inspect_saved(session, invocation_id):
    record_id = session.scalar(
        select(ChapterAnnotation.record_id).where(ChapterAnnotation.execution_id == invocation_id)
    )
    return {
        "execution": session.get(Execution, invocation_id),
        "record_id": record_id,
        "warnings": annotation_warnings(session, record_id) if record_id else [],
    }


def annotation_warnings(session, record_id):
    "独立核验已提交产物的真实案例告警，重投不能丢失局部失败信息"
    rows = session.scalars(
        select(CaseEntry).where(CaseEntry.warning_record_id == record_id).order_by(CaseEntry.warning_ordinal)
    )
    return [
        {"code": "case_save_failed", "caseid": row.attempted_case_reference, "message": row.warning_message}
        for row in rows
    ]


def save_consolidation(session, request):
    run_id, chapter_id = request["run_id"], request["chapter_id"]
    session.execute(text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"), {"key": f"fact_graph:{run_id}"})
    records = session.scalars(
        select(ChapterAnnotation)
        .where(ChapterAnnotation.run_id == run_id, ChapterAnnotation.chapter_id == chapter_id)
        .order_by(ChapterAnnotation.role, ChapterAnnotation.record_id)
    ).all()
    sources = sorted(
        ({"execution_id": str(row.execution_id), "output_id": str(row.record_id)} for row in records),
        key=lambda item: item["output_id"],
    )
    expected = sorted(request["sources"], key=lambda item: item["output_id"])
    if sources != expected or any(row.chapter_consolidation_version != request["rule_version"] for row in records):
        raise ValueError("章末核对期间正式标注来源发生变化，不能保存过期结论")
    previous = session.scalar(
        select(WorkItem).where(
            WorkItem.program_run_id == run_id,
            WorkItem.program_chapter_id == chapter_id,
            WorkItem.program_code == request["program_code"],
        )
    )
    if previous is not None:
        if previous.program_invocation_key != request["program_key"]:
            raise ValueError("章末凭据与有效来源集合不同，不能覆盖")
        expected_cases = request["cases"].snapshot()["registrations"]
        descriptions = set(
            session.scalars(
                select(BookCase.description)
                .join(CaseEntry, CaseEntry.case_id == BookCase.case_id)
                .where(CaseEntry.program_work_id == previous.work_id)
            )
        )
        if not request.get("recheck") or descriptions == {item["description"] for item in expected_cases.values()}:
            return {
                "status": "existing",
                "chapter_id": chapter_id,
                "fact_id": request["digest"],
                "author": previous.work_id,
            }
        from src.storage.repositories.annotation_recovery import discard_chapter_receipts

        discard_chapter_receipts(session, run_id, {chapter_id})
    session.add(
        WorkItem(
            work_id=request["author"],
            program_run_id=run_id,
            program_chapter_id=chapter_id,
            program_code=request["program_code"],
            program_invocation_key=request["program_key"],
        )
    )
    session.flush()
    session.add(GraphFact(program_work_id=request["author"]))
    session.flush()
    warnings = CaseWritesRepository(run_id).save_work(session, request["cases"])
    if warnings:
        raise ValueError(f"章末案例未成功保存: {warnings}")
    identifiers = sorted(request["cases"].snapshot()["registrations"])
    states = {
        row.case_id: str(row.review_state or "pending")
        for row in session.scalars(select(BookCase).where(BookCase.case_id.in_(identifiers)))
    }
    return {
        "status": "saved",
        "chapter_id": chapter_id,
        "fact_id": request["digest"],
        "author": request["author"],
        "case_ids": identifiers,
        "case_states": states,
        "issues": len(identifiers),
    }
