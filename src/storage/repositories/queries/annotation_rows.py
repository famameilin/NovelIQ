"agents annotation agent 的具名物理读取"

from __future__ import annotations

from sqlalchemy import select

from src.storage.models import (
    Chapter,
    ChapterAnnotation,
)


def list_recovery_sources(_session, run_id):
    return _session.execute(
        select(
            ChapterAnnotation.record_id,
            ChapterAnnotation.agent_id,
            ChapterAnnotation.role,
            ChapterAnnotation.chapter_id,
            Chapter.sequence,
        )
        .join(
            Chapter, (Chapter.run_id == ChapterAnnotation.run_id) & (Chapter.chapter_id == ChapterAnnotation.chapter_id)
        )
        .where(ChapterAnnotation.run_id == run_id)
    )
























