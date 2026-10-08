"""标注、对话与事件原始记录查询，不判定角色完成或解释领域状态"""

from __future__ import annotations

from sqlalchemy import func, select

from src.storage.models import (
    AnalysisOutput,
    AnnotationWork,
    Chapter,
    DialogueRecord,
    EventEdge,
    EventNode,
    GraphEntity,
    GraphFact,
)
from src.storage.repositories.annotation.rows import ChapterAnnotationRow as ChapterAnnotationRow
from src.storage.repositories.annotation.rows import CharacterFactRow as CharacterFactRow
from src.storage.repositories.annotation.rows import DialogueFactRow as DialogueFactRow
from src.storage.repositories.annotation.rows import ForeshadowingTreeView as ForeshadowingTreeView
from src.storage.repositories.base import BaseRepository


class AnnotationRepository(BaseRepository[AnalysisOutput]):
    def fetch_chapter_sequence_map(self, run_id: str) -> dict[int, int]:
        rows = self.session.execute(select(Chapter.chapter_id, Chapter.sequence).where(Chapter.run_id == run_id)).all()
        return {int(row.chapter_id): int(row.sequence) for row in rows}

    def fetch_chapter_ids(self, run_id: str) -> set[int]:
        return set(self.session.scalars(select(Chapter.chapter_id).where(Chapter.run_id == run_id).distinct()))

    def fetch_saved_outputs(self, run_id: str) -> list[AnalysisOutput]:
        return list(
            self.session.scalars(
                select(AnalysisOutput)
                .join(AnnotationWork, AnnotationWork.work_id == AnalysisOutput.work_id)
                .where(
                    AnalysisOutput.run_id == run_id,
                    AnalysisOutput.kind == "chapter_annotation",
                    AnnotationWork.state == "saved",
                    AnnotationWork.invocation_id == AnalysisOutput.invocation_id,
                )
            )
        )

    def fetch_work_records(self, run_id: str) -> list[AnnotationWork]:
        return list(self.session.scalars(select(AnnotationWork).where(AnnotationWork.run_id == run_id)))

    def fetch_entities_by_id(self, run_id: str) -> dict[str, GraphEntity]:
        return {
            str(row.entity_id): row
            for row in self.session.scalars(select(GraphEntity).where(GraphEntity.run_id == run_id))
        }

    def fetch_dialogue_records(self, run_id: str) -> list[DialogueRecord]:
        return list(
            self.session.scalars(
                select(DialogueRecord)
                .join(
                    Chapter,
                    (Chapter.run_id == DialogueRecord.run_id) & (Chapter.chapter_id == DialogueRecord.chapter_id),
                )
                .where(
                    DialogueRecord.run_id == run_id,
                )
                .order_by(Chapter.sequence, DialogueRecord.chapter_id, DialogueRecord.start)
            )
        )

    def fetch_foreshadowing_roots(self, run_id: str, *, ordered: bool = False) -> list[EventNode]:
        statement = select(EventNode).where(EventNode.run_id == run_id, EventNode.is_foreshadowing_root.is_(True))
        if ordered:
            statement = statement.join(
                Chapter, (Chapter.run_id == EventNode.run_id) & (Chapter.chapter_id == EventNode.chapter_id)
            ).order_by(Chapter.sequence, EventNode.chapter_id, EventNode.event_id)
        return list(self.session.scalars(statement))

    def fetch_foreshadowing_edges(self, run_id: str, *, ordered: bool = False) -> list[EventEdge]:
        statement = select(EventEdge).where(
            EventEdge.run_id == run_id, EventEdge.edge_type == "foreshadowing", EventEdge.is_active.is_(True)
        )
        if ordered:
            statement = statement.join(
                Chapter, (Chapter.run_id == EventEdge.run_id) & (Chapter.chapter_id == EventEdge.target_chapter_id)
            ).order_by(Chapter.sequence, EventEdge.target_chapter_id, EventEdge.edge_id)
        return list(self.session.scalars(statement))

    def fetch_event_records(self, run_id: str, event_ids: set[str]) -> list[EventNode]:
        return list(
            self.session.scalars(select(EventNode).where(EventNode.run_id == run_id, EventNode.event_id.in_(event_ids)))
        )

    def fetch_foreshadowing_edge_counts(self, run_id: str) -> dict[str, int]:
        statement = (
            select(EventEdge.source_event_id, func.count().label("edge_count"))
            .where(EventEdge.run_id == run_id, EventEdge.edge_type == "foreshadowing")
            .group_by(EventEdge.source_event_id)
        )
        return {row.source_event_id: int(row.edge_count) for row in self.session.execute(statement)}

    def fetch_graph_facts(self, run_id: str, *, content_kind: str) -> list[GraphFact]:
        """2026-08-19 用于读取指定类型的章节事实"""
        stmt = (
            select(GraphFact)
            .join(
                Chapter,
                (Chapter.run_id == GraphFact.run_id) & (Chapter.chapter_id == GraphFact.chapter_id),
            )
            .where(
                GraphFact.run_id == run_id,
                GraphFact.source_kind == "annotation",
            )
            .order_by(Chapter.sequence, GraphFact.chapter_id, GraphFact.graph_fact_id)
        )
        rows = self.session.execute(stmt).scalars().all()
        sequence_map = self.fetch_chapter_sequence_map(run_id)
        return sorted(
            (row for row in rows if isinstance(row.content, dict) and row.content.get("kind") == content_kind),
            key=lambda row: (sequence_map.get(row.effective_chapter_id, row.effective_chapter_id), row.graph_fact_id),
        )
