"""
Phase2 setup 池与全量台账 ORM 模型定义

本模块提供：
- ForeshadowingThread: setup thread 主表，保存跨 chunk 状态
- ForeshadowingThreadHit: setup thread 命中表，保存每次命中的支撑片段
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, ForeignKeyConstraint, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base


class ForeshadowingThread(Base):
    """
    强伏笔 thread 主表

    保存 setup thread 的生命周期状态，活跃池只是这张表上的过滤视图，不再额外维护 JSON 真相源
    """

    __tablename__ = "foreshadowing_threads"

    setup_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    run_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("analysis_runs.run_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    first_chunk_id: Mapped[int] = mapped_column(Integer, nullable=False)
    last_chunk_id: Mapped[int] = mapped_column(Integer, nullable=False)
    setup_summary: Mapped[str] = mapped_column(Text, nullable=False)
    setup_kind: Mapped[str] = mapped_column(String(50), nullable=False)
    expected_payoff_family: Mapped[str] = mapped_column(String(100), nullable=False)
    payoff_likelihood: Mapped[str] = mapped_column(String(20), nullable=False)
    confidence: Mapped[str] = mapped_column(String(20), nullable=False, default="high")
    strength: Mapped[str] = mapped_column(String(20), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        nullable=False,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
    )

    __table_args__ = (
        Index("idx_foreshadowing_threads_run_active_last_chunk", "run_id", "active", "last_chunk_id"),
        Index("idx_foreshadowing_threads_run_status", "run_id", "status"),
    )

    def __repr__(self) -> str:
        return (
            "<ForeshadowingThread("
            f"setup_id={self.setup_id}, run_id={self.run_id}, last_chunk_id={self.last_chunk_id}"
            ")>"
        )


class ForeshadowingThreadHit(Base):
    """
    强伏笔 thread 命中表

    每次 Phase2 命中都落一条 hit，用于回放 anchor_chunk_ids 和最近理由，不在主表里存 JSON 数组
    """

    __tablename__ = "foreshadowing_thread_hits"

    hit_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    setup_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("foreshadowing_threads.setup_id", ondelete="CASCADE"),
        nullable=False,
    )
    run_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("analysis_runs.run_id", ondelete="CASCADE"),
        nullable=False,
    )
    chunk_id: Mapped[int] = mapped_column(Integer, nullable=False)
    anchor_text: Mapped[str] = mapped_column(Text, nullable=False)
    anchor_reason: Mapped[str] = mapped_column(Text, nullable=False)
    why_unresolved_now: Mapped[str] = mapped_column(Text, nullable=False)
    is_new_setup: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow)

    __table_args__ = (
        ForeignKeyConstraint(
            ["chunk_id", "run_id"],
            ["chunks.chunk_id", "chunks.run_id"],
            ondelete="CASCADE",
        ),
        Index("idx_foreshadowing_thread_hits_setup_id", "setup_id"),
        Index("idx_foreshadowing_thread_hits_run_chunk", "run_id", "chunk_id"),
    )

    def __repr__(self) -> str:
        return f"<ForeshadowingThreadHit(setup_id={self.setup_id}, chunk_id={self.chunk_id}, run_id={self.run_id})>"
