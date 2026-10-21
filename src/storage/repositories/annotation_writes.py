"标注正式产物整体保存，事务边界由 Storage 固定"

from sqlalchemy import select, text

from src.storage.models import AnalysisAssessment, ChapterAnnotation, DialogueRecord
from src.storage.records.annotation_save import AnnotationSave
from src.storage.repositories.case_writes import CaseWritesRepository
from src.storage.repositories.event_writes import EventWriter
from src.storage.repositories.fact_writes import FactWriter


def save_annotation(session, request: AnnotationSave):
    record = request.record
    session.execute(
        text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"),
        {"key": f"fact_graph:{record['run_id']}"},
    )
    fact_writer = FactWriter(request.facts.run_id)
    existing = session.scalar(
        select(ChapterAnnotation).where(
            ChapterAnnotation.run_id == record["run_id"],
            ChapterAnnotation.chapter_id == record["chapter_id"],
            ChapterAnnotation.role == record["role"],
        )
    )
    if existing is not None:
        if existing.agent_id != record["agent_id"] or existing.record_id != record["record_id"]:
            raise ValueError("章与角色已有另一份不可变标注结果")
        from src.storage.repositories.event_contributions import check_annotation_event_contribution

        if not check_annotation_event_contribution(session, request.events):
            raise ValueError("已保存标注与冻结事件贡献不一致")
        return {
            "annotation_id": existing.record_id,
            "warnings": [],
            "committed_cases": CaseWritesRepository(record["run_id"]).register_event_roots(session),
        }
    fact_writer.ensure_entity_rows(session, request.facts)
    session.add(ChapterAnnotation(**record))
    session.flush()
    EventWriter(record["run_id"]).save_work(session, request.events, record["record_id"])
    fact_writer.save_work(session, request.facts, record["record_id"])
    session.add_all(DialogueRecord(**row) for row in request.dialogues)
    session.add_all(AnalysisAssessment(**row) for row in request.labels)
    session.flush()
    warnings = CaseWritesRepository(record["run_id"]).save_work(session, request.cases)
    session.flush()
    from src.storage.repositories.event_contributions import check_annotation_event_contribution

    if not check_annotation_event_contribution(session, request.events):
        raise ValueError("标注保存结果与冻结事件贡献不一致")
    committed_cases = CaseWritesRepository(record["run_id"]).register_event_roots(session)
    return {"annotation_id": record["record_id"], "warnings": warnings, "committed_cases": committed_cases}
