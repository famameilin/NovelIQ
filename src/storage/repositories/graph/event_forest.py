"""事件森林原始记录读取，不组装事件树、排序或解释伏笔状态"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.storage.models import AnalysisOutput, AnnotationWork, Chapter, EventEdge, EventNode


class EventForestRecords:
    def __init__(self, session: Session) -> None:
        self.session = session

    def fetch_chapters(self, run_id: str):
        return list(
            self.session.execute(
                select(Chapter)
                .where(Chapter.run_id == run_id, Chapter.text.isnot(None))
                .order_by(Chapter.sequence, Chapter.chapter_id)
            ).scalars()
        )

    def fetch_saved_outputs(self, run_id: str):
        return list(
            self.session.execute(
                select(AnalysisOutput)
                .join(AnnotationWork, AnnotationWork.work_id == AnalysisOutput.work_id)
                .where(
                    AnalysisOutput.run_id == run_id,
                    AnalysisOutput.kind == "chapter_annotation",
                    AnnotationWork.state == "saved",
                    AnnotationWork.invocation_id == AnalysisOutput.invocation_id,
                )
            ).scalars()
        )

    def fetch_nodes(self, run_id: str, max_chapter_order: int):
        return list(
            self.session.execute(
                select(EventNode)
                .where(EventNode.run_id == run_id, EventNode.chapter_order <= max_chapter_order)
                .order_by(EventNode.chapter_order, EventNode.event_id)
            ).scalars()
        )

    def fetch_outputs(self, annotation_ids: set[str]):
        return list(
            self.session.execute(
                select(AnalysisOutput).where(
                    AnalysisOutput.kind == "chapter_annotation",
                    AnalysisOutput.output_id.in_(annotation_ids),
                )
            ).scalars()
        )

    def fetch_causal_edges(self, run_id: str, chapter_ids: set[int], *, include_inactive: bool = False):
        filters: list[Any] = [
            EventEdge.run_id == run_id,
            EventEdge.edge_type == "causal",
            EventEdge.source_chapter_id.in_(chapter_ids),
            EventEdge.target_chapter_id.in_(chapter_ids),
        ]
        if not include_inactive:
            filters.append(EventEdge.is_active.is_(True))
        return list(self.session.execute(select(EventEdge).where(*filters).order_by(EventEdge.edge_id)).scalars())

    def fetch_foreshadow_roots(self, run_id: str, chapter_ids: set[int]):
        return list(
            self.session.execute(
                select(EventNode)
                .join(
                    Chapter,
                    (Chapter.run_id == EventNode.run_id) & (Chapter.chapter_id == EventNode.chapter_id),
                )
                .where(
                    EventNode.run_id == run_id,
                    EventNode.is_foreshadowing_root.is_(True),
                    EventNode.chapter_id.in_(chapter_ids),
                )
                .order_by(Chapter.sequence, EventNode.chapter_id, EventNode.event_id)
            ).scalars()
        )

    def fetch_foreshadow_edges(self, run_id: str):
        return list(
            self.session.execute(
                select(EventEdge).where(
                    EventEdge.run_id == run_id,
                    EventEdge.edge_type == "foreshadowing",
                )
            )
            .scalars()
            .all()
        )
