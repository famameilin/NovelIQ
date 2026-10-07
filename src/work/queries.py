"""按成功 work 只读聚合章节结果，不生成第二份章级持久化产物"""

from __future__ import annotations

from collections import defaultdict

from sqlalchemy.orm import Session

from src.storage.models import AnalysisOutput
from src.storage.models.base import naive_utcnow
from src.storage.repositories.annotation.repository import AnnotationRepository
from src.work.policy import completed_chapters

_ROLE_ORDER = {"solo": 0, "structure": 0, "event": 1, "evidence": 2}


def chapter_annotations(session: Session, run_id: str) -> list[AnalysisOutput]:
    records = AnnotationRepository(session).fetch_saved_outputs(run_id)
    works = AnnotationRepository(session).fetch_work_records(run_id)
    complete = completed_chapters(works)
    groups: dict[int, list[AnalysisOutput]] = defaultdict(list)
    for record in records:
        if record.chapter_id is None:
            continue
        groups[record.chapter_id].append(record)
    sequence = AnnotationRepository(session).fetch_chapter_sequence_map(run_id)
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
                for record in sorted(sources, key=lambda value: _ROLE_ORDER.get(value.role or "", 99))
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


def is_annotate_complete(session: Session, run_id: str) -> bool:
    """2026-08-05 用于按真实章节集合严格判断标注阶段完成状态"""
    expected = AnnotationRepository(session).fetch_chapter_ids(run_id)
    if not expected:
        return False
    actual = {record.chapter_id for record in chapter_annotations(session, run_id)}
    return actual == expected


def work_progress_view(session: Session, run_id: str) -> dict[str, object]:
    """只读已登记工作，完整性由唯一角色策略裁决"""
    from src.storage.repositories.book_state import chapter_count, work_records

    work = work_records(session, run_id)
    return {
        "completed_chapters": len(completed_chapters(work)),
        "total_chapters": chapter_count(session, run_id),
        "saved_work_count": len(work),
        "works": [
            {
                "work_id": item.work_id,
                "chapter_id": item.chapter_id,
                "role": item.role,
                "state": item.state,
                "invocation_id": item.invocation_id,
            }
            for item in work
        ],
    }
