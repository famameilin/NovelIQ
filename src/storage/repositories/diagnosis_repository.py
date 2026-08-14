"""
诊断阶段最新事实源仓储
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from sqlalchemy import and_, func, select
from sqlalchemy.orm import Session

from src.storage.models import Chunk, ChunkCurve, ChunkTopic, StageSummary
from src.storage.repositories.annotation import AnnotationRepository, ForeshadowingThreadView
from src.storage.repositories.base import BaseRepository
from src.storage.repositories.graph import GraphRepository


def _topic_words_from_model_dir(model_dir: Path) -> dict[int, tuple[list[str], str | None]]:
    """2026-08-11 用于从 LDA 模型目录读取主题词与标签，模型缺失或损坏时返回空映射"""
    if not model_dir.exists():
        return {}
    try:
        from src.topic import LDAConfig, LDATrainer

        topic_model = LDATrainer(LDAConfig()).load_model(model_dir)
    except (FileNotFoundError, ImportError, OSError, ValueError):
        return {}
    result: dict[int, tuple[list[str], str | None]] = {}
    labels = getattr(topic_model, "labels", None) or {}
    for topic_id in range(topic_model.num_topics):
        words = [
            word.word
            for word in topic_model.get_topic_words(topic_id, top_n=10)
        ]
        label = labels.get(topic_id)
        result[topic_id] = (words, label if isinstance(label, str) else None)
    return result


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
        """2026-08-07 用于从章节 chunks metrics 读取转折点原文素材"""
        row_limit = limit if limit is not None else 20
        text_by_chunk = self._chunk_text_by_id(run_id)
        rows = [
            (row.chunk_id, text_by_chunk.get(row.chunk_id, ""), row.event_type)
            for row in AnnotationRepository(self.session).fetch_chunk_annotations_full(run_id)
            if row.pivot_moment
        ]
        return rows[:row_limit]

    def fetch_high_tension_chunks(self, run_id: str, limit: int | None = None) -> list[tuple[int, str, float]]:
        """2026-08-14 用于读取高张力 chunk 原文与曲线值（按张力复合指数排序，§19.7 修复）"""
        # 2026-08-14 修复（§19.7）：此前按 abs(net_density)（情绪强度）排序，
        # 高张力诊断实际应表达叙事张力，现改为按 tension_composite 排序。
        # NULL 处理保持原有行为：abs(NULL) 为 NULL，被 > 0.01 过滤条件排除。
        row_limit = limit if limit is not None else 10
        tension_expr = func.abs(ChunkCurve.tension_composite).label("tension")
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
                func.abs(ChunkCurve.tension_composite) > 0.01,
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
        """2026-08-07 用于从章节关系版本逐次变化读取诊断素材"""
        row_limit = limit if limit is not None else 50
        rows: list[tuple[int, str, str, str, str]] = []
        for relation in GraphRepository(self.session).fetch_relation_history(run_id):
            if relation.relation_semantics == "same_character":
                continue
            for change in relation.changes:
                raw_after = change.get("after")
                after = raw_after if isinstance(raw_after, dict) else {}
                rows.append(
                    (
                        int(change["chunk_id"]),
                        relation.from_name,
                        relation.to_name,
                        str(after.get("relation_type") or relation.relation_type),
                        str(change.get("change_kind") or "refine"),
                    )
                )
        return rows[:row_limit]

    def fetch_foreshadowing_chunks(self, run_id: str, limit: int | None = None) -> list[tuple[int, str, str, str]]:
        """2026-08-05 用于从伏笔 thread 与 hit 读取 chunk 级诊断素材"""
        row_limit = limit if limit is not None else 30
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
        """2026-08-07 用于读取章节 chunks metrics 中的转折时刻"""
        return [
            (chunk_id, text)
            for chunk_id, text, _event_type in self.fetch_pivot_blocks(run_id, limit=limit)
        ]

    def fetch_topic_words(self, run_id: str, top_n: int | None = None) -> list[dict[str, Any]]:
        """2026-08-11 用于读取按累计权重排序的主题词（含主题词与标签，模型缺失时仅 id/weight）"""
        row_limit = top_n if top_n is not None else 10
        stmt = (
            select(
                ChunkTopic.topic_id,
                func.sum(ChunkTopic.topic_weight).label("total_weight"),
            )
            .where(ChunkTopic.run_id == run_id)
            .group_by(ChunkTopic.topic_id)
            .order_by(func.sum(ChunkTopic.topic_weight).desc())
        )
        rows = [
            {
                "topic_id": row.topic_id,
                "weight": round(row.total_weight, 4) if row.total_weight else 0.0,
            }
            for row in self.session.execute(stmt).all()[:row_limit]
        ]
        words_by_topic = _topic_words_from_model_dir(Path("models") / "topic" / run_id)
        for row in rows:
            words, label = words_by_topic.get(int(row["topic_id"]), ([], None))
            row["words"] = words
            row["label"] = label
        return rows

    def fetch_known_characters(self, run_id: str) -> list[str]:
        """2026-08-09 用于从消歧后的规范人物视图读取诊断人物名单"""
        from src.knowledge.authority import KnowledgeGraphAuthorityService

        authority = KnowledgeGraphAuthorityService.from_session(self.session)
        try:
            view = authority.build_export_view(run_id)
        except ValueError:
            graph_repo = GraphRepository(self.session)
            return sorted(
                entity.name
                for entity in graph_repo.fetch_latest_entities(run_id, entity_type="character")
            )
        rows: list[str] = []
        for entity in view.canonical_entities:
            if entity.entity_type != "character":
                continue
            if not entity.name or not entity.name.strip() or entity.name == "null":
                continue
            if not entity.aliases:
                rows.append(entity.name)
                continue
            rows.append(f"{entity.name}（别名：{'、'.join(entity.aliases)}）")
        return rows

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
