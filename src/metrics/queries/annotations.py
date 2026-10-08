"""本领域的独立只读投影，不返回 HTTP 模型"""

from __future__ import annotations

from sqlalchemy.orm import Session

from src.event_trees.read.foreshadowing import foreshadowing_by_chapter as read_foreshadowing
from src.storage.repositories.annotation.repository import AnnotationRepository
from src.storage.repositories.annotation.rows import (
    ChapterAnnotationRow,
)
from src.work.queries import chapter_annotations


def fetch_chapter_annotations_full(session: Session, run_id: str) -> list[ChapterAnnotationRow]:
    """2026-08-07 用于从最新系统绑定 payload 展开完整章节标注

    写入前的领域校验归标注 agent，这里按 payload 取指标字段，不重跑整章合同。
    """
    foreshadowing_by_chapter = read_foreshadowing(session, run_id)
    rows: list[ChapterAnnotationRow] = []
    for record in chapter_annotations(session, run_id):
        if record.chapter_id is None:
            continue
        metrics = record.payload["metrics"]
        rows.append(
            ChapterAnnotationRow(
                chapter_id=record.chapter_id,
                emotional_valence=metrics["emotional_valence"],
                event_type=metrics["narrative_function"],
                pivot_moment=metrics["pivot_moment"],
                cliffhanger=metrics["cliffhanger"],
                coverage_warnings=list(record.payload.get("coverage_warnings") or []),
                **foreshadowing_by_chapter.get(record.chapter_id, {}),
            )
        )
    sequence_map = AnnotationRepository(session).fetch_chapter_sequence_map(run_id)
    return sorted(rows, key=lambda row: (sequence_map.get(row.chapter_id, row.chapter_id), row.chapter_id))
