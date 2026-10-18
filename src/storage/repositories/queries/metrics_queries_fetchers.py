"从 src/metrics/queries/fetchers.py 分离的具名物理读取"

from __future__ import annotations

from sqlalchemy import func, select

from src.storage.models import Chapter


def metrics_queries_fetchers_fetch_chapter_progress_map_1(_session, run_id):
    chapter_end_char = Chapter.char_offset + func.length(Chapter.text)
    return _session.execute(select(func.max(chapter_end_char)).where(Chapter.run_id == run_id)).scalar_one_or_none()


def metrics_queries_fetchers_fetch_chapter_progress_map_2(_session, run_id):
    return _session.execute(
        select(Chapter.chapter_id, Chapter.char_offset)
        .where(Chapter.run_id == run_id, Chapter.char_offset.is_not(None))
        .order_by(Chapter.sequence, Chapter.chapter_id)
    ).all()


def metrics_queries_fetchers_fetch_chapter_progress_map_3(_session, run_id):
    return _session.execute(select(func.max(Chapter.char_offset)).where(Chapter.run_id == run_id)).scalar_one_or_none()
