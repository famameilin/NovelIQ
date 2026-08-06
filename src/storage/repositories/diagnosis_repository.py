"""
诊断阶段最新事实源仓储
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import and_, func, select
from sqlalchemy.orm import Session

from src.config import settings
from src.storage.models import Chunk, ChunkCurve, ChunkTopic, StageSummary
from src.storage.repositories.annotation import AnnotationRepository, ForeshadowingThreadView
from src.storage.repositories.base import BaseRepository
from src.storage.repositories.graph import GraphRepository


class DiagnosisRepository(BaseRepository["DiagnosisRepository"]):
    """2026-08-05 用于向诊断 Agent 提供章节标注与数据库图事实"""

    def __init__(self, session: Session):
        """2026-08-05 用于初始化诊断事实查询仓储"""
        super().__init__(session)

    def _chunk_text_by_id(self, run_id: str) -> dict[int, str]:
        """2026-08-05 用于构建诊断素材的 chunk 原文映射"""
        stmt = select(Chunk.chunk_id, Chunk.text).where(Chunk.run_id == run_id)
        return {int(row.chunk_id): str(row.text) for row in self.session.execute(stmt).all()}

    def fetch_pivot_blocks(self, run_id: str, limit: int | None = None) -> list[tuple[int, str, str]]:
        """2026-08-05 用于从章节 segments 读取转折点原文素材"""
        row_limit = limit if limit is not None else settings.diagnosis.pivot_blocks_limit
        text_by_chunk = self._chunk_text_by_id(run_id)
        rows = [
            (row.chunk_id, text_by_chunk.get(row.chunk_id, ""), row.event_type)
            for row in AnnotationRepository(self.session).fetch_chunk_annotations_full(run_id)
            if row.pivot_moment
        ]
        return rows[:row_limit]

    def fetch_high_tension_chunks(self, run_id: str, limit: int | None = None) -> list[tuple[int, str, float]]:
        """2026-08-05 用于读取高张力 chunk 原文与曲线值"""
        row_limit = limit if limit is not None else settings.diagnosis.high_tension_limit
        tension_expr = func.abs(ChunkCurve.net_density).label("tension")
        stmt = (
            select(Chunk.chunk_id, Chunk.text, tension_expr)
            .select_from(Chunk)
            .join(
                ChunkCurve,
                and_(
                    Chunk.chunk_id == ChunkCurve.chunk_id,
                    Chunk.run_id == ChunkCurve.run_id,
                ),
            )
            .where(
                func.abs(ChunkCurve.net_density) > 0.01,
                ChunkCurve.run_id == run_id,
                Chunk.run_id == run_id,
            )
            .order_by(tension_expr.desc())
            .limit(row_limit)
        )
        return [
            (int(row.chunk_id), str(row.text), float(row.tension))
            for row in self.session.execute(stmt)
        ]

    def fetch_relation_changes(self, run_id: str, limit: int | None = None) -> list[tuple[int, str, str, str, str]]:
        """2026-08-05 用于从关系 GraphFact 历史读取诊断素材"""
        row_limit = limit if limit is not None else settings.diagnosis.relation_changes_limit
        return [
            (
                event.chunk_id,
                event.from_name,
                event.to_name,
                event.relation_type,
                event.change_type,
            )
            for event in GraphRepository(self.session).fetch_representative_relation_events(
                run_id,
                limit=row_limit,
            )
        ]

    def fetch_foreshadowing_chunks(self, run_id: str, limit: int | None = None) -> list[tuple[int, str, str, str]]:
        """2026-08-05 用于从伏笔 thread 与 hit 读取 chunk 级诊断素材"""
        row_limit = limit if limit is not None else settings.diagnosis.foreshadowing_limit
        text_by_chunk = self._chunk_text_by_id(run_id)
        rows: list[tuple[int, str, str, str]] = []
        for thread in AnnotationRepository(self.session).fetch_foreshadowing_threads(run_id):
            for chunk_id in thread.anchor_chunk_ids:
                rows.append(
                    (
                        chunk_id,
                        text_by_chunk.get(chunk_id, ""),
                        thread.setup_kind,
                        thread.setup_summary,
                    )
                )
        return sorted(rows, key=lambda row: row[0])[:row_limit]

    def fetch_foreshadowing_threads(self, run_id: str) -> list[ForeshadowingThreadView]:
        """2026-08-05 用于读取伏笔线程最新汇总视图"""
        return AnnotationRepository(self.session).fetch_foreshadowing_threads(run_id)

    def calculate_foreshadow_expectation(self, run_id: str) -> float | None:
        """2026-08-05 用于读取伏笔线程生命周期聚合预期"""
        return AnnotationRepository(self.session).calculate_foreshadow_expectation(run_id)

    def fetch_pivot_moments(self, run_id: str, limit: int | None = None) -> list[tuple[int, str]]:
        """2026-08-05 用于读取章节 segments 中的转折时刻"""
        return [
            (chunk_id, text)
            for chunk_id, text, _event_type in self.fetch_pivot_blocks(run_id, limit=limit)
        ]

    def fetch_topic_words(self, run_id: str, top_n: int | None = None) -> list[dict[str, Any]]:
        """2026-08-05 用于读取按累计权重排序的主题词"""
        row_limit = top_n if top_n is not None else settings.diagnosis.topic_words_top_n
        stmt = (
            select(
                ChunkTopic.topic_id,
                func.sum(ChunkTopic.topic_weight).label("total_weight"),
            )
            .where(ChunkTopic.run_id == run_id)
            .group_by(ChunkTopic.topic_id)
            .order_by(func.sum(ChunkTopic.topic_weight).desc())
        )
        return [
            {
                "topic_id": row.topic_id,
                "weight": round(row.total_weight, 4) if row.total_weight else 0.0,
            }
            for row in self.session.execute(stmt).all()[:row_limit]
        ]

    def fetch_known_characters(self, run_id: str) -> list[str]:
        """2026-08-06 用于从数据库图实体节点读取诊断人物名单"""
        graph_repo = GraphRepository(self.session)
        return sorted(
            entity.canonical_name
            for entity in graph_repo.fetch_representative_entities(run_id, entity_type="character")
        )

    def fetch_stage_summaries(self, run_id: str) -> list[dict[str, Any]]:
        """2026-08-05 用于读取仍由诊断消费的阶段摘要记录"""
        stmt = (
            select(
                StageSummary.start_chunk_id,
                StageSummary.end_chunk_id,
                StageSummary.summary,
            )
            .where(StageSummary.run_id == run_id)
            .order_by(StageSummary.start_chunk_id)
        )
        return [
            {
                "start_chunk_id": row.start_chunk_id,
                "end_chunk_id": row.end_chunk_id,
                "summary": row.summary,
            }
            for row in self.session.execute(stmt)
            if row.summary
        ]
