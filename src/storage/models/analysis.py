"""
创建时间: 2026-03-15
创建者: TraeAI
任务: postgresql-migration
说明: 分析结果相关表 ORM 模型定义

本模块定义分析结果相关的数据表：
- CloudAnalysis: 云端分析结果表
- EmotionCurve: 情绪曲线表
- RhythmCurve: 节奏曲线表
- GlobalStats: 全局统计表
- GlobalContext: 全局上下文表
- ChunkSummary: 分块摘要表

修改时间: 2026-03-16
修改者: TraeAI
修改内容: 将 EmotionCurve, RhythmCurve, ChunkSummary 的主键改为复合主键 (chunk_id, run_id)，使用复合外键引用 chunks 表
"""

from __future__ import annotations

from typing import Optional

from sqlalchemy import Float, ForeignKeyConstraint, Index, Integer, String, Text, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base


class CloudAnalysis(Base):
    """
    云端分析结果表

    创建时间: 2026-03-15
    创建者: TraeAI
    任务: postgresql-migration
    说明: 存储云端模型的分析结果
    """

    __tablename__ = "cloud_analysis"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    novel_id: Mapped[Optional[str]] = mapped_column(String(255), nullable=True, index=True)
    foreshadow_rate: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    arc_scores: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    narrative_type: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    topic_labels: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    diagnosis: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    value_logic_type: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    value_logic_reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    power_stance_score: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    power_stance_reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    common_people_dignity: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    dignity_reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    cultural_depth_score: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    cultural_depth_reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    emotion_curve_type: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    run_id: Mapped[Optional[str]] = mapped_column(
        String(36), ForeignKey("analysis_runs.run_id", ondelete="CASCADE"), nullable=True, index=True
    )

    __table_args__ = (
        Index("idx_cloud_analysis_novel_id", "novel_id"),
        Index("idx_cloud_analysis_run_id", "run_id"),
    )

    def __repr__(self) -> str:
        return f"<CloudAnalysis(id={self.id}, novel_id={self.novel_id})>"


class EmotionCurve(Base):
    """
    情绪曲线表

    创建时间: 2026-03-15
    创建者: TraeAI
    任务: postgresql-migration
    说明: 存储分块的情绪密度数据

    修改时间: 2026-03-16
    修改者: TraeAI
    修改内容: 将主键改为复合主键 (chunk_id, run_id)，使用复合外键引用 chunks 表
    """

    __tablename__ = "emotion_curve"

    chunk_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    run_id: Mapped[str] = mapped_column(String(36), primary_key=True, index=True)
    pos_density: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    neg_density: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    net_density: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    smoothed_density: Mapped[Optional[float]] = mapped_column(Float, nullable=True)

    __table_args__ = (
        ForeignKeyConstraint(
            ["chunk_id", "run_id"],
            ["chunks.chunk_id", "chunks.run_id"],
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["run_id"],
            ["analysis_runs.run_id"],
            ondelete="CASCADE",
        ),
        Index("idx_emotion_curve_run_id", "run_id"),
    )

    def __repr__(self) -> str:
        return f"<EmotionCurve(chunk_id={self.chunk_id}, run_id={self.run_id})>"


class RhythmCurve(Base):
    """
    节奏曲线表

    创建时间: 2026-03-15
    创建者: TraeAI
    任务: postgresql-migration
    说明: 存储分块的张力/节奏数据

    修改时间: 2026-03-16
    修改者: TraeAI
    修改内容: 将主键改为复合主键 (chunk_id, run_id)，使用复合外键引用 chunks 表
    """

    __tablename__ = "rhythm_curve"

    chunk_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    run_id: Mapped[str] = mapped_column(String(36), primary_key=True, index=True)
    tension_proxy: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    tension_composite: Mapped[Optional[float]] = mapped_column(Float, nullable=True)

    __table_args__ = (
        ForeignKeyConstraint(
            ["chunk_id", "run_id"],
            ["chunks.chunk_id", "chunks.run_id"],
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["run_id"],
            ["analysis_runs.run_id"],
            ondelete="CASCADE",
        ),
        Index("idx_rhythm_curve_run_id", "run_id"),
    )

    def __repr__(self) -> str:
        return f"<RhythmCurve(chunk_id={self.chunk_id}, run_id={self.run_id})>"


class GlobalStats(Base):
    """
    全局统计表

    创建时间: 2026-03-15
    创建者: TraeAI
    任务: postgresql-migration
    说明: 存储全局统计数据

    修改时间: 2026-03-16
    修改者: TraeAI
    任务: fix-global-stats-pk
    修改内容: 将主键改为复合主键 (stat_name, run_id)，支持多 run 数据隔离
    """

    __tablename__ = "global_stats"

    stat_name: Mapped[str] = mapped_column(String(255), primary_key=True)
    stat_value: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    run_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("analysis_runs.run_id", ondelete="CASCADE"), primary_key=True
    )

    def __repr__(self) -> str:
        return f"<GlobalStats(stat_name={self.stat_name}, run_id={self.run_id})"


class GlobalContext(Base):
    """
    全局上下文表

    创建时间: 2026-03-15
    创建者: TraeAI
    任务: postgresql-migration
    说明: 存储小说的全局上下文信息
    """

    __tablename__ = "global_context"

    novel_id: Mapped[str] = mapped_column(String(255), primary_key=True)
    novel_title: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    core_characters: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    world_setting: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    updated_at: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    run_id: Mapped[Optional[str]] = mapped_column(
        String(36), ForeignKey("analysis_runs.run_id", ondelete="CASCADE"), nullable=True, index=True
    )

    __table_args__ = (Index("idx_global_context_run_id", "run_id"),)

    def __repr__(self) -> str:
        return f"<GlobalContext(novel_id={self.novel_id})>"


class ChunkSummary(Base):
    """
    分块摘要表

    创建时间: 2026-03-15
    创建者: TraeAI
    任务: postgresql-migration
    说明: 存储分块的摘要信息

    修改时间: 2026-03-16
    修改者: TraeAI
    修改内容: 将主键改为复合主键 (chunk_id, run_id)，使用复合外键引用 chunks 表
    """

    __tablename__ = "chunk_summaries"

    chunk_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    run_id: Mapped[str] = mapped_column(String(36), primary_key=True, index=True)
    summary: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)

    __table_args__ = (
        ForeignKeyConstraint(
            ["chunk_id", "run_id"],
            ["chunks.chunk_id", "chunks.run_id"],
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["run_id"],
            ["analysis_runs.run_id"],
            ondelete="CASCADE",
        ),
        Index("idx_chunk_summaries_run_id", "run_id"),
    )

    def __repr__(self) -> str:
        return f"<ChunkSummary(chunk_id={self.chunk_id}, run_id={self.run_id})>"
