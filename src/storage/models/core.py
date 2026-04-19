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

修改时间: 2026-04-19
修改者: TraeAI
任务: task-system-db-driven-refactor
修改内容: 为 AnalysisRun 添加运行态字段（error, message, completed_at, cancel_requested, worker_id, heartbeat_at, sub_stage, current, total）
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, DateTime, Float, Index, Integer, String, Text
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

修改时间: 2026-04-19
修改者: TraeAI
任务: task-system-db-driven-refactor
修改内容: 添加完整运行态字段，使 DB 成为任务唯一真相源

修改时间: 2026-04-19
修改者: Codex (GPT-5)
任务: fix-task-system-review-findings
修改内容: 补充 message 持久化字段，保证 DB-only 状态查询可恢复进度文案
    """

    __tablename__ = "analysis_runs"

    run_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    novel_id: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    source_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    title: Mapped[str | None] = mapped_column(String(500), nullable=True)
    author: Mapped[str | None] = mapped_column(String(255), nullable=True)
    status: Mapped[str] = mapped_column(String(50), nullable=False, default="pending", index=True)
    progress: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    stage: Mapped[str | None] = mapped_column(String(255), nullable=True)

    # 运行态字段（task-system-db-driven-refactor 新增）
    sub_stage: Mapped[str | None] = mapped_column(String(255), nullable=True, default=None)
    current: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    total: Mapped[int] = mapped_column(Integer, nullable=False, default=100)
    message: Mapped[str | None] = mapped_column(Text, nullable=True, default=None)
    error: Mapped[str | None] = mapped_column(Text, nullable=True, default=None)
    cancel_requested: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    worker_id: Mapped[str | None] = mapped_column(String(255), nullable=True, default=None)
    heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, default=None)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, default=None)

    created_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    updated_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    __table_args__ = (
        Index("idx_analysis_runs_novel", "novel_id"),
        Index("idx_analysis_runs_status", "status"),
    )

    def __repr__(self) -> str:
        return (
            f"<AnalysisRun(run_id={self.run_id}, novel_id={self.novel_id}, "
            f"status={self.status}, progress={self.progress})>"
        )


class DisambigCheckpoint(Base):
    """
    消歧检查点表

    仅存储 DisambiguationState 的 JSON 快照，用于断点续传。
    图投影进度通过 ChunkRelation.projection_status 查询，不在此表中记录。
    """

    __tablename__ = "disambig_checkpoint"

    run_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    state_json: Mapped[str] = mapped_column(Text, nullable=False)
    updated_at: Mapped[float] = mapped_column(Float, nullable=False)

    def __repr__(self) -> str:
        return f"<DisambigCheckpoint(run_id={self.run_id}, updated_at={self.updated_at})>"
