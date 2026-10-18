"""事件森林原始记录读取，不组装事件树、排序或解释伏笔状态

- 章节原文与章节目录同键（chapters.text）
- 已保存产物 = chapter_annotations 行（存在即成功事实，行自带运行/章/角色归属）
- 章级声明 = event_declarations，经来源记录取得运行归属
- 因果/伏笔边 = narrative_links 的语义形状（relation_type 表达类型）
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.event_trees.storage_map import run_execution_ids
from src.storage.models import (
    Chapter,
    ChapterAnnotation,
    EventDeclaration,
    NarrativeLink,
)


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
        """本 run 已正式保存的章节标注：行存在即保存事实，章号从产物行取得"""
        stmt = (
            select(
                ChapterAnnotation.record_id.label("output_id"),
                ChapterAnnotation.record_id,
                ChapterAnnotation.execution_id,
                ChapterAnnotation.chapter_id,
            )
            .where(ChapterAnnotation.run_id == run_id)
            .order_by(ChapterAnnotation.chapter_id)
        )
        return list(self.session.execute(stmt).all())

    def fetch_nodes(self, run_id: str, max_chapter_order: int):
        """本 run 在阅读截点内的章级声明，按章序与声明身份稳定排序"""
        stmt = (
            select(
                EventDeclaration.declaration_id.label("event_id"),
                EventDeclaration.declaration_id,
                EventDeclaration.record_id,
                EventDeclaration.local_key,
                EventDeclaration.title,
                EventDeclaration.problem,
                EventDeclaration.summary,
                EventDeclaration.event_type,
                EventDeclaration.status,
                EventDeclaration.progress,
                EventDeclaration.is_foreshadowing_root,
                EventDeclaration.payoff_likelihood,
                ChapterAnnotation.chapter_id.label("chapter_id"),
                Chapter.sequence.label("chapter_order"),
            )
            .join(ChapterAnnotation, ChapterAnnotation.record_id == EventDeclaration.record_id)
            .join(
                Chapter,
                (Chapter.run_id == ChapterAnnotation.run_id) & (Chapter.chapter_id == ChapterAnnotation.chapter_id),
            )
            .where(
                ChapterAnnotation.run_id == run_id,
                Chapter.sequence <= max_chapter_order,
            )
            .order_by(Chapter.sequence, EventDeclaration.declaration_id)
        )
        return list(self.session.execute(stmt).all())

    def fetch_outputs(self, annotation_ids: set[str]):
        if not annotation_ids:
            return []
        return list(
            self.session.execute(
                select(ChapterAnnotation)
                .where(ChapterAnnotation.record_id.in_(annotation_ids))
                .order_by(ChapterAnnotation.record_id)
            ).scalars()
        )

    def _event_chapters(self, run_id: str, event_ids: set[str]) -> dict[str, set[int]]:
        """完整事件的来源章：由其自身证据的段落所属章节投影，不按当前章替代"""
        from src.storage.models import Paragraph, SourceEvidence

        result: dict[str, set[int]] = {event_id: set() for event_id in event_ids}
        if not event_ids:
            return result
        stmt = (
            select(SourceEvidence.complete_event_id, Paragraph.chapter_id)
            .join(Paragraph, (Paragraph.run_id == run_id) & (Paragraph.paragraph_id == SourceEvidence.paragraph_id))
            .where(SourceEvidence.complete_event_id.in_(list(event_ids)))
        )
        for event_id, chapter_id in self.session.execute(stmt).all():
            result[str(event_id)].add(int(chapter_id))
        return result

    def _semantic_links(self, run_id: str, *, relation_type: str):
        """本 run 的正式语义链路：两端都必须是完整事件，按链路身份稳定排序"""
        return list(
            self.session.execute(
                select(NarrativeLink)
                .where(
                    NarrativeLink.producer_execution_id.in_(run_execution_ids(run_id)),
                    NarrativeLink.relation_type == relation_type,
                    NarrativeLink.semantic_source_event_id.is_not(None),
                    NarrativeLink.semantic_target_event_id.is_not(None),
                )
                .order_by(NarrativeLink.link_id)
            ).scalars()
        )

    def fetch_causal_edges(self, run_id: str, chapter_ids: set[int], *, include_inactive: bool = False):
        links = self._semantic_links(run_id, relation_type="causal")
        if not include_inactive:
            links = [row for row in links if row.is_active is not False]
        event_ids = {row.semantic_source_event_id for row in links} | {
            row.semantic_target_event_id for row in links
        }
        chapters = self._event_chapters(run_id, {item for item in event_ids if item is not None})
        return [
            row
            for row in links
            if chapters.get(str(row.semantic_source_event_id), set()) <= chapter_ids
            and chapters.get(str(row.semantic_target_event_id), set()) <= chapter_ids
        ]

    def fetch_foreshadow_roots(self, run_id: str, chapter_ids: set[int]):
        rows = list(
            self.session.scalars(
                select(EventDeclaration)
                .join(ChapterAnnotation, ChapterAnnotation.record_id == EventDeclaration.record_id)
                .join(
                    Chapter,
                    (Chapter.run_id == ChapterAnnotation.run_id)
                    & (Chapter.chapter_id == ChapterAnnotation.chapter_id),
                )
                .where(
                    ChapterAnnotation.run_id == run_id,
                    EventDeclaration.is_foreshadowing_root.is_(True),
                )
                .order_by(Chapter.sequence, EventDeclaration.declaration_id)
            )
        )
        if not chapter_ids:
            return rows
        return [row for row in rows if self._declaration_chapter(row.record_id) in chapter_ids]

    def _declaration_chapter(self, record_id: str) -> int | None:
        return self.session.scalar(
            select(ChapterAnnotation.chapter_id).where(ChapterAnnotation.record_id == record_id).limit(1)
        )

    def fetch_foreshadow_edges(self, run_id: str):
        """伏笔语义链路：来源/目标都必须是完整事件，声明身份不回填冒充"""
        return self._semantic_links(run_id, relation_type="foreshadowing")
