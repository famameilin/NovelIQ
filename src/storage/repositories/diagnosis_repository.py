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

import json
from typing import Any

from sqlalchemy import and_, func, select
from sqlalchemy.orm import Session

from src.config import settings
from src.storage.models import (
    Chunk,
    ChunkAnnotation,
    ChunkTopic,
    EntitySnapshot,
    GraphEntity,
    GraphRelationCurrent,
    GraphRelationEvent,
)
from src.storage.models.analysis import EmotionCurve
from src.storage.models.core import DisambigCheckpoint
from src.storage.repositories.base import BaseRepository
from src.storage.repositories.graph.repository import GraphRepository


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

    def fetch_pivot_blocks(self, run_id: str, limit: int | None = None) -> list[tuple[int, str, str]]:
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
            .join(
                ChunkAnnotation,
                and_(
                    Chunk.chunk_id == ChunkAnnotation.chunk_id,
                    Chunk.run_id == ChunkAnnotation.run_id,
                ),
            )
            .where(
                and_(
                    ChunkAnnotation.pivot_moment == 1,
                    ChunkAnnotation.run_id == run_id,
                    Chunk.run_id == run_id,
                )
            )
            .order_by(Chunk.chunk_id)
            .limit(limit)
        )

        result = self.session.execute(stmt)
        return [(row.chunk_id, row.text, row.event_type) for row in result]

    def fetch_high_tension_chunks(self, run_id: str, limit: int | None = None) -> list[tuple[int, str, float]]:
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
            .join(
                EmotionCurve,
                and_(
                    Chunk.chunk_id == EmotionCurve.chunk_id,
                    Chunk.run_id == EmotionCurve.run_id,
                ),
            )
            .where(
                and_(
                    func.abs(EmotionCurve.net_density) > 0.01,
                    EmotionCurve.run_id == run_id,
                    Chunk.run_id == run_id,
                )
            )
            .order_by(tension_expr.desc())
            .limit(limit)
        )

        result = self.session.execute(stmt)
        return [(row.chunk_id, row.text, row.tension) for row in result]

    def fetch_relation_changes(self, run_id: str, limit: int | None = None) -> list[tuple[int, str, str, str, str]]:
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

        graph_stmt = (
            select(
                GraphRelationEvent.chunk_id,
                GraphEntity.canonical_name,
                GraphRelationEvent.to_entity_id,
                GraphRelationEvent.relation_type,
                GraphRelationEvent.change_type,
            )
            .join(GraphEntity, GraphRelationEvent.from_entity_id == GraphEntity.entity_id)
            .where(GraphRelationEvent.run_id == run_id)
            .order_by(GraphRelationEvent.chunk_id.desc(), GraphRelationEvent.relation_event_id.desc())
            .limit(limit)
        )
        graph_rows = self.session.execute(graph_stmt).fetchall()
        name_map = {
            row.entity_id: row.canonical_name
            for row in self.session.execute(
                select(GraphEntity.entity_id, GraphEntity.canonical_name).where(GraphEntity.run_id == run_id)
            ).fetchall()
        }
        return [
            (
                row.chunk_id,
                row.canonical_name,
                name_map.get(row.to_entity_id, str(row.to_entity_id)),
                row.relation_type,
                row.change_type,
            )
            for row in graph_rows
        ]


    def fetch_foreshadowing_chunks(self, run_id: str, limit: int | None = None) -> list[tuple[int, str, str, str]]:
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
            .join(
                ChunkAnnotation,
                and_(
                    Chunk.chunk_id == ChunkAnnotation.chunk_id,
                    Chunk.run_id == ChunkAnnotation.run_id,
                ),
            )
            .where(
                and_(
                    ChunkAnnotation.has_foreshadowing == 1,
                    ChunkAnnotation.run_id == run_id,
                    Chunk.run_id == run_id,
                )
            )
            .order_by(Chunk.chunk_id)
            .limit(limit)
        )

        result = self.session.execute(stmt)
        return [(row.chunk_id, row.text, row.foreshadowing_type, row.foreshadowing_desc) for row in result]

    def fetch_first_last_chunk_summary(self, run_id: str, max_chars: int | None = None) -> tuple[str, str]:
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

        stmt = select(Chunk.chunk_id, Chunk.text).where(Chunk.run_id == run_id).order_by(Chunk.chunk_id)

        result = self.session.execute(stmt)
        chunks = result.fetchall()

        if not chunks:
            return "", ""

        first_text = chunks[0].text[:max_chars] if chunks[0].text else ""
        last_text = chunks[-1].text[:max_chars] if chunks[-1].text else ""
        return first_text, last_text

    def fetch_pivot_moments(self, run_id: str, limit: int | None = None) -> list[tuple[int, str]]:
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
            .join(
                ChunkAnnotation,
                and_(
                    Chunk.chunk_id == ChunkAnnotation.chunk_id,
                    Chunk.run_id == ChunkAnnotation.run_id,
                ),
            )
            .where(
                and_(
                    ChunkAnnotation.event_type == "高潮",
                    ChunkAnnotation.run_id == run_id,
                    Chunk.run_id == run_id,
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
    ) -> list[dict[str, Any]]:
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
                    EntitySnapshot.run_id == run_id,
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

    def fetch_topic_words(self, run_id: str, top_n: int | None = None) -> list[dict[str, Any]]:
        """
        获取主题词

        创建时间: 2026-03-27
        创建者: TraeAI
        任务: 诊断数据获取逻辑收敛到 DiagnosisRepository
        说明: 从 payload.py 迁移，获取按权重排序的主题词列表

        Args:
            run_id: 运行ID
            top_n: 返回数量限制

        Returns:
            包含 topic_id 和 weight 的字典列表
        """
        if top_n is None:
            top_n = settings.diagnosis.topic_words_top_n

        stmt = (
            select(
                ChunkTopic.topic_id,
                func.sum(ChunkTopic.topic_weight).label("total_weight"),
            )
            .where(ChunkTopic.run_id == run_id)
            .group_by(ChunkTopic.topic_id)
            .order_by(func.sum(ChunkTopic.topic_weight).desc())
        )

        result = self.session.execute(stmt)
        rows = result.fetchall()[:top_n]
        return [
            {
                "topic_id": row.topic_id,
                "weight": round(row.total_weight, 4) if row.total_weight else 0.0,
            }
            for row in rows
        ]

    def fetch_character_disambig_data(self, run_id: str) -> tuple[list[str], dict[str, str]]:
        """
        获取角色消歧数据（known_characters 和 alias_merges）

        创建时间: 2026-03-27
        创建者: TraeAI
        任务: 诊断数据获取逻辑收敛到 DiagnosisRepository
        说明: 从 payload.py 迁移，分离获取 known_characters 和 alias_merges

        修改时间: 2026-03-28
        修改者: TraeAI
        任务: consolidate-codebase-architecture
        修改内容: 禁止静默吞异常，数据格式错误时抛出 ValueError

        Args:
            run_id: 运行ID

        Returns:
            (known_characters, alias_merges):
                known_characters: 规范角色名列表
                alias_merges: 别名到规范名的映射（只包含 alias != canonical）

        Raises:
            ValueError: checkpoint 数据格式无效
        """
        if not run_id:
            return [], {}

        stmt = select(DisambigCheckpoint.state_json).where(DisambigCheckpoint.run_id == run_id)

        result = self.session.execute(stmt).fetchone()

        if not result or not result.state_json:
            return [], {}

        raw_data = json.loads(result.state_json)
        if not isinstance(raw_data, dict):
            raise ValueError(
                f"Invalid checkpoint data format for run_id={run_id}: "
                f"expected dict, got {type(raw_data).__name__}"
            )

        known_canonical_names = raw_data.get("known_canonical_names")
        alias_merges_list = raw_data.get("alias_merges")

        if known_canonical_names is None and alias_merges_list is None:
            raise ValueError(
                f"Missing required fields in checkpoint data for run_id={run_id}: "
                "'known_canonical_names' and 'alias_merges'"
            )

        if known_canonical_names is not None and not isinstance(known_canonical_names, list):
            raise ValueError(
                f"Invalid 'known_canonical_names' format for run_id={run_id}: "
                f"expected list, got {type(known_canonical_names).__name__}"
            )

        if alias_merges_list is not None and not isinstance(alias_merges_list, list):
            raise ValueError(
                f"Invalid 'alias_merges' format for run_id={run_id}: "
                f"expected list, got {type(alias_merges_list).__name__}"
            )

        alias_merges_dict = {
            str(alias): str(canonical)
            for alias, canonical in (alias_merges_list or [])
            if isinstance(alias, str) and isinstance(canonical, str) and alias != canonical
        }
        return [str(name) for name in (known_canonical_names or []) if isinstance(name, str)], alias_merges_dict

    def fetch_graph_summary(self, run_id: str) -> dict[str, Any]:
        graph_repo = GraphRepository(self.session)
        node_count = self.session.execute(
            select(func.count()).select_from(GraphEntity).where(GraphEntity.run_id == run_id)
        ).scalar() or 0
        edge_count = self.session.execute(
            select(func.count()).select_from(GraphRelationCurrent).where(
                GraphRelationCurrent.run_id == run_id,
                GraphRelationCurrent.is_active.is_(True),
            )
        ).scalar() or 0
        core_characters_rows = self.session.execute(
            select(GraphEntity.canonical_name)
            .where(GraphEntity.run_id == run_id)
            .order_by(GraphEntity.last_seen_chunk.desc().nullslast())
            .limit(5)
        ).fetchall()
        recent_events = self.session.execute(
            select(
                GraphRelationEvent.chunk_id,
                GraphRelationEvent.relation_type,
                GraphRelationEvent.change_type,
                GraphRelationEvent.evidence,
            )
            .where(GraphRelationEvent.run_id == run_id)
            .order_by(GraphRelationEvent.chunk_id.desc(), GraphRelationEvent.relation_event_id.desc())
            .limit(5)
        ).fetchall()
        key_relation_rows = self.session.execute(
            select(
                GraphRelationCurrent.current_type,
                GraphRelationCurrent.support_count,
                GraphRelationCurrent.from_entity_id,
                GraphRelationCurrent.to_entity_id,
            )
            .where(
                GraphRelationCurrent.run_id == run_id,
                GraphRelationCurrent.is_active.is_(True),
            )
            .order_by(GraphRelationCurrent.support_count.desc(), GraphRelationCurrent.last_seen_chunk.desc().nullslast())
            .limit(5)
        ).fetchall()
        entity_name_map = {
            row.entity_id: row.canonical_name
            for row in self.session.execute(
                select(GraphEntity.entity_id, GraphEntity.canonical_name).where(GraphEntity.run_id == run_id)
            ).fetchall()
        }
        low_confidence_events = graph_repo.fetch_low_confidence_relation_events(run_id, threshold=0.6, limit=20)
        relation_conflicts = graph_repo.detect_relation_conflicts(run_id, active_only=True)
        density = 0.0
        if node_count > 1:
            density = float(edge_count) / float(node_count * (node_count - 1))
        return {
            "node_count": int(node_count),
            "edge_count": int(edge_count),
            "density": round(density, 4),
            "core_characters": [row[0] for row in core_characters_rows],
            "key_relations": [
                {
                    "from": entity_name_map.get(row[2], str(row[2])),
                    "to": entity_name_map.get(row[3], str(row[3])),
                    "type": row[0],
                    "support_count": int(row[1] or 0),
                }
                for row in key_relation_rows
            ],
            "recent_events": [
                {
                    "chunk_id": row[0],
                    "type": row[1],
                    "change": row[2],
                    "evidence": row[3],
                }
                for row in recent_events
            ],
            "quality": {
                "conflict_count": len(relation_conflicts),
                "low_confidence_count": len(low_confidence_events),
                "conflicts": relation_conflicts[:5],
                "low_confidence_samples": low_confidence_events[:5],
            },
        }

    def fetch_recent_snapshots(
        self,
        run_id: str,
        novel_id: str,
        limit: int = 10,
    ) -> list[dict[str, Any]]:
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
                    EntitySnapshot.run_id == run_id,
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
