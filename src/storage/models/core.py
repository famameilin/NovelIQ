"""
创建时间: 2026-03-15
创建者: TraeAI
任务: postgresql-migration
说明: 核心表 ORM 模型定义

本模块定义核心业务表：
- AnalysisRun: 分析运行记录表
- DisambigCheckpoint: 消歧检查点表

修改时间: 2026-03-16
修改者: TraeAI
任务: fix-disambiguation-three-phase
修改内容: 新增 DisambigCheckpoint 模型用于保存消歧检查点
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, Float, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base

if TYPE_CHECKING:
    pass


class AnalysisRun(Base):
    """
    分析运行记录表

    创建时间: 2026-03-15
    创建者: TraeAI
    任务: postgresql-migration
    说明: 记录每次分析任务的运行信息，作为所有数据的隔离主键
    """

    __tablename__ = "analysis_runs"

    run_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    novel_id: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    source_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    title: Mapped[str | None] = mapped_column(String(500), nullable=True)
    status: Mapped[str] = mapped_column(String(50), nullable=False, default="pending", index=True)
    created_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    updated_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    __table_args__ = (
        Index("idx_analysis_runs_novel", "novel_id"),
        Index("idx_analysis_runs_status", "status"),
    )

    def __repr__(self) -> str:
        return f"<AnalysisRun(run_id={self.run_id}, novel_id={self.novel_id}, status={self.status})>"


class DisambigCheckpoint(Base):
    """
    消歧检查点表

    创建时间: 2026-03-16
    创建者: TraeAI
    任务: fix-disambiguation-three-phase
    说明: 保存增量消歧过程中的 alias_map 检查点，支持断点续传

    修改时间: 2026-03-19
    修改者: TraeAI
    任务: fix-entity-relations-not-saved
    修改内容: 添加 entity_relations 字段用于保存关系数据
    """

    __tablename__ = "disambig_checkpoint"

    run_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    alias_map: Mapped[str] = mapped_column(Text, nullable=False)
    updated_at: Mapped[float] = mapped_column(Float, nullable=False)
    entity_relations: Mapped[str | None] = mapped_column(Text, nullable=True)
    disambig_states: Mapped[str | None] = mapped_column(Text, nullable=True)

    def __repr__(self) -> str:
        return f"<DisambigCheckpoint(run_id={self.run_id}, updated_at={self.updated_at})>"
