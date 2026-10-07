"""按成功 work 只读聚合章节结果，不生成第二份章级持久化产物"""

from __future__ import annotations

from collections import defaultdict

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.storage.models import AnalysisOutput, AnnotationWork, Chapter
from src.storage.models.base import naive_utcnow
from src.storage.repositories.annotation.work_state import completed_chapters

_ROLE_ORDER = {"solo": 0, "structure": 0, "event": 1, "evidence": 2}


def chapter_annotations(session: Session, run_id: str) -> list[AnalysisOutput]:
    records = (
        session.execute(
            select(AnalysisOutput)
            .join(AnnotationWork, AnnotationWork.work_id == AnalysisOutput.work_id)
            .where(
                AnalysisOutput.run_id == run_id,
                AnalysisOutput.kind == "chapter_annotation",
                AnnotationWork.state == "saved",
                AnnotationWork.invocation_id == AnalysisOutput.invocation_id,
            )
        )
        .scalars()
        .all()
    )
    works = session.execute(select(AnnotationWork).where(AnnotationWork.run_id == run_id)).scalars().all()
    complete = completed_chapters(works)
    groups: dict[int, list[AnalysisOutput]] = defaultdict(list)
    for record in records:
        if record.chapter_id is None:
            continue
        groups[record.chapter_id].append(record)
    sequence = {
        row.chapter_id: row.sequence
        for row in session.execute(select(Chapter.chapter_id, Chapter.sequence).where(Chapter.run_id == run_id)).all()
    }
    results: list[AnalysisOutput] = []
    for chapter_id, sources in sorted(groups.items(), key=lambda item: sequence[item[0]]):
        expected = {work.role for work in works if work.chapter_id == chapter_id}
        if chapter_id not in complete or {record.role for record in sources} != expected:
            continue
        metric = next(record for record in sources if record.role in {"solo", "evidence"})
        payload = {"metrics": metric.payload["metrics"]}
        for name in ("events", "dialogues", "character_observations", "paragraph_labels", "coverage_warnings"):
            payload[name] = [
                value
                for record in sorted(
                    sources, key=lambda value: _ROLE_ORDER.get(value.role or "", 99)
                )
                for value in record.payload.get(name, [])
            ]
        results.append(
            AnalysisOutput(
                output_id=metric.output_id,
                run_id=run_id,
                kind="chapter_annotation",
                chapter_id=chapter_id,
                payload=payload,
                created_at=naive_utcnow(),
            )
        )
    return results
