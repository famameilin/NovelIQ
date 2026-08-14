"""
核心表 ORM 模型定义

本模块定义核心业务表：
- AnalysisRun: 分析运行记录表

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

    添加 started_at 字段，记录任务实际开始执行时间，完善运行态时间戳体系

    为 novel_id 补充到 novels 表的外键约束，阻止 task 再次脱离小说主表

    添加 analysis_contract_version 字段（设计文档《章节粒度分析指标重设计》§16）：
    记录 run 的分析合同版本（新 run 默认 paragraph-v1），旧 run 该列为 NULL，
    段落级接口据此返回 409 要求重新分析。
    """

    __tablename__ = "analysis_runs"

    run_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    novel_id: Mapped[str] = mapped_column(
        String(255),
        ForeignKey("novels.novel_id", ondelete="RESTRICT", name="analysis_runs_novel_id_fkey"),
        nullable=False,
    )
    analysis_contract_version: Mapped[str | None] = mapped_column(String(50), nullable=True)
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
