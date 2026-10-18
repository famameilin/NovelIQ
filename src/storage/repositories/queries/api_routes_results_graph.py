"从 src/api/routes/results_graph.py 分离的具名物理读取"

from __future__ import annotations

from sqlalchemy import select

from src.storage.models import Chapter, Paragraph


def api_routes_results_graph_get_event_source_chapter_1(_session, chapter_id, run_id):
    return _session.scalar(select(Chapter).where(Chapter.run_id == run_id, Chapter.chapter_id == chapter_id))


def api_routes_results_graph_get_event_source_chapter_2(_session, chapter_id, run_id):
    return _session.execute(
        select(Paragraph)
        .where(Paragraph.run_id == run_id, Paragraph.chapter_id == chapter_id)
        .order_by(Paragraph.paragraph_index)
    ).scalars()
