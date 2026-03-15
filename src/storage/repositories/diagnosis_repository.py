"""
创建时间: 2026-03-14
创建者: TraeAI
任务: 实现 DiagnosisRepository 类
说明: 诊断数据 Repository 实现，管理诊断分析相关的数据查询和存储

修改时间: 2026-03-15
修改者: TraeAI
任务: postgresql-migration
修改内容: 从 sqlite3.Connection 迁移到 SQLAlchemy Session，使用 ORM 查询替代原生 SQL
"""

from __future__ import annotations

from typing import Any, Dict, List, Tuple

from sqlalchemy import and_, func, or_, select
from sqlalchemy.orm import Session

from src.config import settings
from src.storage.models import Chunk, ChunkAnnotation, ChunkRelation, EntitySnapshot
from src.storage.models.analysis import EmotionCurve
from src.storage.repositories.base import BaseRepository


class DiagnosisRepository(BaseRepository["DiagnosisRepository"]):
    """
    诊断数据 Repository

    管理诊断分析相关的数据查询和存储，包括转折点、高张力分块、
    关系变更、伏笔分块、实体快照等数据操作。

    修改时间: 2026-03-15
    修改者: TraeAI
    任务: postgresql-migration
    修改内容: 从 sqlite3.Connection 迁移到 SQLAlchemy Session
    """

    def __init__(self, session: Session):
        """
        初始化 DiagnosisRepository

        Args:
            session: SQLAlchemy Session 实例
        """
        super().__init__(session)

    def fetch_pivot_blocks(self, run_id: str, limit: int | None = None) -> List[Tuple[int, str, str]]:
        """
        获取转折点分块

        Args:
            run_id: 运行ID
            limit: 返回数量限制

        Returns:
            (chunk_id, text, event_type) 元组列表
        """
        if limit is None:
            limit = settings.diagnosis.pivot_blocks_limit

        stmt = (
            select(Chunk.chunk_id, Chunk.text, ChunkAnnotation.event_type)
            .select_from(Chunk)
            .join(ChunkAnnotation, Chunk.chunk_id == ChunkAnnotation.chunk_id)
            .where(
                and_(
                    ChunkAnnotation.pivot_moment == 1,
                    or_(ChunkAnnotation.run_id == run_id, ChunkAnnotation.run_id.is_(None)),
                )
            )
            .order_by(Chunk.chunk_id)
            .limit(limit)
        )

        result = self.session.execute(stmt)
        return [(row.chunk_id, row.text, row.event_type) for row in result]

    def fetch_high_tension_chunks(self, run_id: str, limit: int | None = None) -> List[Tuple[int, str, float]]:
        """
        获取高张力分块

        Args:
            run_id: 运行ID
            limit: 返回数量限制

        Returns:
            (chunk_id, text, tension) 元组列表
        """
        if limit is None:
            limit = settings.diagnosis.high_tension_limit

        tension_expr = func.abs(EmotionCurve.net_density).label("tension")

        stmt = (
            select(Chunk.chunk_id, Chunk.text, tension_expr)
            .select_from(Chunk)
            .join(EmotionCurve, Chunk.chunk_id == EmotionCurve.chunk_id)
            .where(
                and_(
                    func.abs(EmotionCurve.net_density) > 0.01,
                    or_(EmotionCurve.run_id == run_id, EmotionCurve.run_id.is_(None)),
                )
            )
            .order_by(tension_expr.desc())
            .limit(limit)
        )

        result = self.session.execute(stmt)
        return [(row.chunk_id, row.text, row.tension) for row in result]

    def fetch_relation_changes(self, run_id: str, limit: int | None = None) -> List[Tuple[int, str, str, str, str]]:
        """
        获取关系变更记录

        Args:
            run_id: 运行ID
            limit: 返回数量限制

        Returns:
            (chunk_id, from_char, to_char, type, change) 元组列表
        """
        if limit is None:
            limit = settings.diagnosis.relation_changes_limit

        stmt = (
            select(
                ChunkRelation.chunk_id,
                ChunkRelation.from_char,
                ChunkRelation.to_char,
                ChunkRelation.type,
                ChunkRelation.change,
            )
            .where(or_(ChunkRelation.run_id == run_id, ChunkRelation.run_id.is_(None)))
            .order_by(ChunkRelation.chunk_id)
            .limit(limit)
        )

        result = self.session.execute(stmt)
        return [(row.chunk_id, row.from_char, row.to_char, row.type, row.change) for row in result]

    def fetch_foreshadowing_chunks(self, run_id: str, limit: int | None = None) -> List[Tuple[int, str, str, str]]:
        """
        获取伏笔分块

        Args:
            run_id: 运行ID
            limit: 返回数量限制

        Returns:
            (chunk_id, text, foreshadowing_type, foreshadowing_desc) 元组列表
        """
        if limit is None:
            limit = settings.diagnosis.foreshadowing_limit

        stmt = (
            select(
                Chunk.chunk_id,
                Chunk.text,
                ChunkAnnotation.foreshadowing_type,
                ChunkAnnotation.foreshadowing_desc,
            )
            .select_from(Chunk)
            .join(ChunkAnnotation, Chunk.chunk_id == ChunkAnnotation.chunk_id)
            .where(
                and_(
                    ChunkAnnotation.has_foreshadowing == 1,
                    or_(ChunkAnnotation.run_id == run_id, ChunkAnnotation.run_id.is_(None)),
                )
            )
            .order_by(Chunk.chunk_id)
            .limit(limit)
        )

        result = self.session.execute(stmt)
        return [(row.chunk_id, row.text, row.foreshadowing_type, row.foreshadowing_desc) for row in result]

    def fetch_first_last_chunk_summary(self, run_id: str, max_chars: int | None = None) -> Tuple[str, str]:
        """
        获取首尾分块摘要

        Args:
            run_id: 运行ID
            max_chars: 最大字符数

        Returns:
            (首分块摘要, 尾分块摘要) 元组
        """
        if max_chars is None:
            max_chars = settings.diagnosis.first_last_max_chars

        stmt = (
            select(Chunk.chunk_id, Chunk.text)
            .where(or_(Chunk.run_id == run_id, Chunk.run_id.is_(None)))
            .order_by(Chunk.chunk_id)
        )

        result = self.session.execute(stmt)
        chunks = result.fetchall()

        if not chunks:
            return "", ""

        first_text = chunks[0].text[:max_chars] if chunks[0].text else ""
        last_text = chunks[-1].text[:max_chars] if chunks[-1].text else ""
        return first_text, last_text

    def fetch_pivot_moments(self, run_id: str, limit: int | None = None) -> List[Tuple[int, str]]:
        """
        获取高潮时刻

        Args:
            run_id: 运行ID
            limit: 返回数量限制

        Returns:
            (chunk_id, text) 元组列表
        """
        if limit is None:
            limit = settings.diagnosis.pivot_moments_limit

        stmt = (
            select(Chunk.chunk_id, Chunk.text)
            .select_from(Chunk)
            .join(ChunkAnnotation, Chunk.chunk_id == ChunkAnnotation.chunk_id)
            .where(
                and_(
                    ChunkAnnotation.event_type == "高潮",
                    or_(ChunkAnnotation.run_id == run_id, ChunkAnnotation.run_id.is_(None)),
                )
            )
            .order_by(Chunk.chunk_id)
            .limit(limit)
        )

        result = self.session.execute(stmt)
        return [(row.chunk_id, row.text) for row in result]

    def insert_entity_snapshot(
        self,
        run_id: str,
        novel_id: str,
        entity_id: int,
        chunk_id: int,
        state_json: str,
    ) -> int | None:
        """
        插入实体快照

        使用 merge 操作实现 INSERT OR REPLACE 语义：
        如果存在相同 (novel_id, entity_id, chunk_id) 的记录则更新，否则插入。

        Args:
            run_id: 运行ID
            novel_id: 小说ID
            entity_id: 实体ID
            chunk_id: 分块ID
            state_json: 状态JSON

        Returns:
            插入记录的 ID
        """
        snapshot = EntitySnapshot(
            novel_id=novel_id,
            entity_id=entity_id,
            chunk_id=chunk_id,
            state_json=state_json,
            run_id=run_id,
        )
        merged = self.session.merge(snapshot)
        self.session.flush()
        return merged.snap_id

    def fetch_snapshots_by_chunk(
        self,
        run_id: str,
        novel_id: str,
        start_chunk: int,
        end_chunk: int,
    ) -> List[Dict[str, Any]]:
        """
        按分块范围获取快照

        Args:
            run_id: 运行ID
            novel_id: 小说ID
            start_chunk: 起始分块ID
            end_chunk: 结束分块ID

        Returns:
            快照字典列表
        """
        stmt = (
            select(
                EntitySnapshot.snap_id,
                EntitySnapshot.novel_id,
                EntitySnapshot.entity_id,
                EntitySnapshot.chunk_id,
                EntitySnapshot.state_json,
                EntitySnapshot.run_id,
            )
            .where(
                and_(
                    EntitySnapshot.novel_id == novel_id,
                    EntitySnapshot.chunk_id >= start_chunk,
                    EntitySnapshot.chunk_id <= end_chunk,
                    or_(EntitySnapshot.run_id == run_id, EntitySnapshot.run_id.is_(None)),
                )
            )
            .order_by(EntitySnapshot.chunk_id.desc())
        )

        result = self.session.execute(stmt)
        return [
            {
                "snap_id": row.snap_id,
                "novel_id": row.novel_id,
                "entity_id": row.entity_id,
                "chunk_id": row.chunk_id,
                "state_json": row.state_json,
                "run_id": row.run_id,
            }
            for row in result
        ]

    def fetch_recent_snapshots(
        self,
        run_id: str,
        novel_id: str,
        limit: int = 10,
    ) -> List[Dict[str, Any]]:
        """
        获取最近的快照

        Args:
            run_id: 运行ID
            novel_id: 小说ID
            limit: 返回数量限制

        Returns:
            快照字典列表
        """
        stmt = (
            select(
                EntitySnapshot.snap_id,
                EntitySnapshot.novel_id,
                EntitySnapshot.entity_id,
                EntitySnapshot.chunk_id,
                EntitySnapshot.state_json,
                EntitySnapshot.run_id,
            )
            .where(
                and_(
                    EntitySnapshot.novel_id == novel_id,
                    or_(EntitySnapshot.run_id == run_id, EntitySnapshot.run_id.is_(None)),
                )
            )
            .order_by(EntitySnapshot.chunk_id.desc())
            .limit(limit)
        )

        result = self.session.execute(stmt)
        return [
            {
                "snap_id": row.snap_id,
                "novel_id": row.novel_id,
                "entity_id": row.entity_id,
                "chunk_id": row.chunk_id,
                "state_json": row.state_json,
                "run_id": row.run_id,
            }
            for row in result
        ]
