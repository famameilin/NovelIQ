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
from src.storage.repositories.annotation import foreshadowing_threads as foreshadowing_thread_repo
from src.storage.models import (
    Chunk,
    ChunkAnnotation,
    ChunkCurve,
    ChunkTopic,
    GraphEntity,
    GraphRelationEvent,
    StageSummary,
)
from src.storage.models.core import DisambigCheckpoint
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
                and_(
                    func.abs(ChunkCurve.net_density) > 0.01,
                    ChunkCurve.run_id == run_id,
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

    def fetch_foreshadowing_threads(self, run_id: str) -> list[foreshadowing_thread_repo.ForeshadowingThreadView]:
        """
        获取 setup thread ledger 视图。

        创建时间: 2026-04-26
        修改者: Codex
        任务: remove-foreshadow-rate-contract
        新建原因: diagnosis 主链改为直接消费 setup ledger，不能继续停留在 chunk 级 foreshadowing_list。
        """

        return foreshadowing_thread_repo.fetch_foreshadowing_threads(self.session, run_id)

    def calculate_foreshadow_expectation(self, run_id: str) -> float | None:
        """
        基于 setup thread ledger 计算伏笔回收预期。

        创建时间: 2026-04-26
        修改者: Codex
        任务: remove-foreshadow-rate-contract
        新建原因: diagnosis payload 现在要把 ledger 的正式 expectation 作为单一真相源传入模型。
        """

        return foreshadowing_thread_repo.calculate_foreshadow_expectation(self.session, run_id)

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
                f"Invalid checkpoint data format for run_id={run_id}: expected dict, got {type(raw_data).__name__}"
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

    def fetch_stage_summaries(self, run_id: str) -> list[dict[str, Any]]:
        """
        获取所有阶段性摘要

        创建时间: 2026-04-08
        创建者: GLM-5
        任务: summary-full-chain-refactor
        说明: 从 stage_summaries 表读取所有阶段性摘要，用于云端诊断

        Args:
            run_id: 运行ID

        Returns:
            包含 start_chunk_id, end_chunk_id, summary 的字典列表
        """
        stmt = (
            select(
                StageSummary.start_chunk_id,
                StageSummary.end_chunk_id,
                StageSummary.summary,
            )
            .where(StageSummary.run_id == run_id)
            .order_by(StageSummary.start_chunk_id)
        )
        result = self.session.execute(stmt)
        return [
            {
                "start_chunk_id": row.start_chunk_id,
                "end_chunk_id": row.end_chunk_id,
                "summary": row.summary,
            }
            for row in result
            if row.summary
        ]
