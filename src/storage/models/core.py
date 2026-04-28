"""
核心表 ORM 模型定义

本模块定义核心业务表：
- AnalysisRun: 分析运行记录表
- DisambigCheckpoint: 消歧检查点表

新增 DisambigCheckpoint 模型用于保存消歧检查点

为 AnalysisRun 添加运行态字段
          （error, message, completed_at, cancel_requested, worker_id, heartbeat_at, sub_stage, current, total）
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base

if TYPE_CHECKING:
    pass


class AnalysisRun(Base):
    """
    分析运行记录表

    记录每次分析任务的运行信息，作为所有数据的隔离主键

    添加完整运行态字段，使 DB 成为任务唯一真相源

    添加 started_at 字段，记录任务实际开始执行时间，完善运行态时间戳体系。

    为 novel_id 补充到 novels 表的外键约束，阻止 task 再次脱离小说主表。
    """

    __tablename__ = "analysis_runs"

    run_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    novel_id: Mapped[str] = mapped_column(
        String(255),
        ForeignKey("novels.novel_id", ondelete="RESTRICT", name="analysis_runs_novel_id_fkey"),
        nullable=False,
    )
    source_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    title: Mapped[str | None] = mapped_column(String(500), nullable=True)
    author: Mapped[str | None] = mapped_column(String(255), nullable=True)
    status: Mapped[str] = mapped_column(String(50), nullable=False, default="pending")
    progress: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    stage: Mapped[str | None] = mapped_column(String(255), nullable=True)

    # 运行态字段
    sub_stage: Mapped[str | None] = mapped_column(String(255), nullable=True, default=None)
    current: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    total: Mapped[int] = mapped_column(Integer, nullable=False, default=100)
    message: Mapped[str | None] = mapped_column(Text, nullable=True, default=None)
    error: Mapped[str | None] = mapped_column(Text, nullable=True, default=None)
    task_kind: Mapped[str] = mapped_column(String(50), nullable=False, default="analysis")
    request_payload: Mapped[str | None] = mapped_column(Text, nullable=True, default=None)
    cancel_requested: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    worker_id: Mapped[str | None] = mapped_column(String(255), nullable=True, default=None)
    heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, default=None)
    started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, default=None)
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

    为 run_id 补充到 analysis_runs 的外键约束，确保检查点生命周期与任务一致。
    """

    __tablename__ = "disambig_checkpoint"

    run_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("analysis_runs.run_id", ondelete="CASCADE", name="disambig_checkpoint_run_id_fkey"),
        primary_key=True,
    )
    state_json: Mapped[str] = mapped_column(Text, nullable=False)
    updated_at: Mapped[float] = mapped_column(Float, nullable=False)

    def __repr__(self) -> str:
        return f"<DisambigCheckpoint(run_id={self.run_id}, updated_at={self.updated_at})>"
