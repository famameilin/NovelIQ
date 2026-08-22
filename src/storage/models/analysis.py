"""
分析结果相关表 ORM 模型定义

本模块定义分析结果相关的数据表：
- CloudAnalysis: 云端分析结果表
- GlobalStats: 全局统计表
- GlobalContext: 全局上下文表
- ChapterSummary: 章节摘要表
"""

from __future__ import annotations

from sqlalchemy import Float, ForeignKey, ForeignKeyConstraint, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base


class CloudAnalysis(Base):
    """存储云端分析结果、叙事焦点结构以及分离的题材和风格标签"""

    __tablename__ = "cloud_analysis"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    novel_id: Mapped[str | None] = mapped_column(
        String(255),
        ForeignKey("novels.novel_id", ondelete="RESTRICT", name="cloud_analysis_novel_id_fkey"),
        nullable=True,
    )
    foreshadow_expectation: Mapped[float | None] = mapped_column(Float, nullable=True)
    arc_scores: Mapped[str | None] = mapped_column(Text, nullable=True)
    genre_labels: Mapped[str | None] = mapped_column(Text, nullable=True)
    style_labels: Mapped[str | None] = mapped_column(Text, nullable=True)
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
    focus_structure: Mapped[str | None] = mapped_column(String(20), nullable=True)
    focus_characters: Mapped[str | None] = mapped_column(Text, nullable=True)
    main_characters: Mapped[str | None] = mapped_column(Text, nullable=True)
    core_cast: Mapped[str | None] = mapped_column(Text, nullable=True)
    theme_color: Mapped[str | None] = mapped_column(String(20), nullable=True)
    run_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("analysis_runs.run_id", ondelete="CASCADE"), nullable=True
    )

    __table_args__ = (
        Index("idx_cloud_analysis_novel_id", "novel_id"),
        Index("idx_cloud_analysis_run_id", "run_id"),
    )

    def __repr__(self) -> str:
        return f"<CloudAnalysis(id={self.id}, novel_id={self.novel_id})>"


class GlobalStats(Base):
    """
    全局统计表

    存储全局统计数据

    将主键改为复合主键 (stat_name, run_id)，支持多 run 数据隔离
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

    存储小说的全局上下文信息

    为 novel_id 补充到 novels 表的外键约束，确保全局上下文不会脱离小说主表
    """

    __tablename__ = "global_context"

    novel_id: Mapped[str] = mapped_column(
        String(255),
        ForeignKey("novels.novel_id", ondelete="RESTRICT", name="global_context_novel_id_fkey"),
        primary_key=True,
    )
    novel_title: Mapped[str | None] = mapped_column(String(500), nullable=True)
    core_characters: Mapped[str | None] = mapped_column(Text, nullable=True)
    world_setting: Mapped[str | None] = mapped_column(Text, nullable=True)
    updated_at: Mapped[str | None] = mapped_column(String(50), nullable=True)
    run_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("analysis_runs.run_id", ondelete="CASCADE"), nullable=True
    )

    __table_args__ = (Index("idx_global_context_run_id", "run_id"),)

    def __repr__(self) -> str:
        return f"<GlobalContext(novel_id={self.novel_id})>"


class ChapterSummary(Base):
    """
    分块摘要表

    存储分块的摘要信息

    将主键改为复合主键 (chapter_id, run_id)，使用复合外键引用 chunks 表
    """

    __tablename__ = "chapter_summaries"

    chapter_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    run_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[str | None] = mapped_column(String(50), nullable=True)

    __table_args__ = (
        ForeignKeyConstraint(
            ["chapter_id", "run_id"],
            ["chapters.chapter_id", "chapters.run_id"],
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["run_id"],
            ["analysis_runs.run_id"],
            ondelete="CASCADE",
        ),
        Index("idx_chapter_summaries_run_id", "run_id"),
    )

    def __repr__(self) -> str:
        return f"<ChapterSummary(chapter_id={self.chapter_id}, run_id={self.run_id})>"


class StageSummary(Base):
    """
    阶段性摘要表

    存储增量消歧阶段生成的阶段性摘要

    修正主键为 stage_id 以匹配数据库实际结构

    删除与列级 ForeignKey 重复的同义 ForeignKeyConstraint，
    避免 ORM 元数据重复声明同一条 run_id -> analysis_runs.run_id 外键
    """

    __tablename__ = "stage_summaries"

    stage_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("analysis_runs.run_id", ondelete="CASCADE"), nullable=False
    )
    start_chapter_id: Mapped[int] = mapped_column(Integer, nullable=False)
    end_chapter_id: Mapped[int] = mapped_column(Integer, nullable=False)
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[str | None] = mapped_column(String(50), nullable=True)

    __table_args__ = (
        # 2026-08-13 P2：补齐指向 章节s 的复合 FK，防止孤儿 章节 引用
        ForeignKeyConstraint(
            ["start_chapter_id", "run_id"],
            ["chapters.chapter_id", "chapters.run_id"],
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["end_chapter_id", "run_id"],
            ["chapters.chapter_id", "chapters.run_id"],
            ondelete="CASCADE",
        ),
        Index("idx_stage_summaries_run_id", "run_id"),
    )

    def __repr__(self) -> str:
        return f"<StageSummary(stage_id={self.stage_id}, run_id={self.run_id})>"
