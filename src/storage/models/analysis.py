"""
创建时间: 2026-03-15
创建者: TraeAI
任务: postgresql-migration
说明: 分析结果相关表 ORM 模型定义

本模块定义分析结果相关的数据表：
- CloudAnalysis: 云端分析结果表
- ChunkCurve: 分块曲线表（情绪 + 节奏）
- GlobalStats: 全局统计表
- GlobalContext: 全局上下文表
- ChunkSummary: 分块摘要表

修改时间: 2026-03-16
修改者: TraeAI
修改内容: 将 EmotionCurve, RhythmCurve, ChunkSummary 的主键改为复合主键 (chunk_id, run_id)，使用复合外键引用 chunks 表
"""

from __future__ import annotations

from sqlalchemy import Float, ForeignKey, ForeignKeyConstraint, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base


class CloudAnalysis(Base):
    """
    云端分析结果表

    创建时间: 2026-03-15
    创建者: TraeAI
    任务: postgresql-migration
    说明: 存储云端模型的分析结果

    修改时间: 2026-03-27
    修改者: TraeAI
    修改内容: 新增 protagonist, main_characters, core_cast 三个字段用于存储角色信息
    """

    __tablename__ = "cloud_analysis"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    novel_id: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    foreshadow_rate: Mapped[float | None] = mapped_column(Float, nullable=True)
    arc_scores: Mapped[str | None] = mapped_column(Text, nullable=True)
    narrative_type: Mapped[str | None] = mapped_column(String(100), nullable=True)
    topic_labels: Mapped[str | None] = mapped_column(Text, nullable=True)
    diagnosis: Mapped[str | None] = mapped_column(Text, nullable=True)
    value_logic_type: Mapped[str | None] = mapped_column(String(50), nullable=True)
    value_logic_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    power_stance_score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    power_stance_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    common_people_dignity: Mapped[int | None] = mapped_column(Integer, nullable=True)
    dignity_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    cultural_depth_score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    cultural_depth_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    narrative_arc_type: Mapped[str | None] = mapped_column(String(50), nullable=True)
    protagonist: Mapped[str | None] = mapped_column(Text, nullable=True)
    main_characters: Mapped[str | None] = mapped_column(Text, nullable=True)
    core_cast: Mapped[str | None] = mapped_column(Text, nullable=True)
    run_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("analysis_runs.run_id", ondelete="CASCADE"), nullable=True, index=True
    )

    __table_args__ = (
        Index("idx_cloud_analysis_novel_id", "novel_id"),
        Index("idx_cloud_analysis_run_id", "run_id"),
    )

    def __repr__(self) -> str:
        return f"<CloudAnalysis(id={self.id}, novel_id={self.novel_id})>"


class ChunkCurve(Base):
    """
    分块曲线表（合并情绪曲线 + 节奏曲线）

    创建时间: 2026-03-30
    创建者: CodeBuddy
    任务: db-schema-cleanup
    说明: 将 emotion_curve 和 rhythm_curve 合并为 chunk_curves，统一管理所有分块级曲线数据
    """

    __tablename__ = "chunk_curves"

    chunk_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    run_id: Mapped[str] = mapped_column(String(36), primary_key=True, index=True)
    pos_density: Mapped[float | None] = mapped_column(Float, nullable=True)
    neg_density: Mapped[float | None] = mapped_column(Float, nullable=True)
    net_density: Mapped[float | None] = mapped_column(Float, nullable=True)
    smoothed_density: Mapped[float | None] = mapped_column(Float, nullable=True)
    tension_proxy: Mapped[float | None] = mapped_column(Float, nullable=True)
    tension_composite: Mapped[float | None] = mapped_column(Float, nullable=True)

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
        Index("idx_chunk_curves_run_id", "run_id"),
    )

    def __repr__(self) -> str:
        return f"<ChunkCurve(chunk_id={self.chunk_id}, run_id={self.run_id})>"


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
    stat_value: Mapped[float | None] = mapped_column(Float, nullable=True)
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
    novel_title: Mapped[str | None] = mapped_column(String(500), nullable=True)
    core_characters: Mapped[str | None] = mapped_column(Text, nullable=True)
    world_setting: Mapped[str | None] = mapped_column(Text, nullable=True)
    updated_at: Mapped[str | None] = mapped_column(String(50), nullable=True)
    run_id: Mapped[str | None] = mapped_column(
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
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[str | None] = mapped_column(String(50), nullable=True)

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
