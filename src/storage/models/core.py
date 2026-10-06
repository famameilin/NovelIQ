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
    """

    __tablename__ = "analysis_runs"
    __table_args__ = (
        Index("idx_analysis_runs_novel", "novel_id"),
        Index("idx_analysis_runs_status", "status"),
        {"comment": "分析运行表：每次分析任务一行，run_id 是所有业务数据的隔离主键，运行态唯一真相源"},
    )

    run_id: Mapped[str] = mapped_column(String(36), primary_key=True, comment="运行主键（uuid）")
    novel_id: Mapped[str] = mapped_column(
        String(255),
        ForeignKey("novels.novel_id", ondelete="RESTRICT", name="analysis_runs_novel_id_fkey"),
        nullable=False,
        comment="所属小说",
    )
    source_path: Mapped[str | None] = mapped_column(Text, nullable=True, comment="原始文件路径快照")
    title: Mapped[str | None] = mapped_column(String(500), nullable=True, comment="书名快照")
    author: Mapped[str | None] = mapped_column(String(255), nullable=True, comment="作者快照")
    status: Mapped[str] = mapped_column(String(50), nullable=False, default="pending", comment="运行状态")
    progress: Mapped[float] = mapped_column(Float, nullable=False, default=0.0, comment="总进度（0~1）")
    stage: Mapped[str | None] = mapped_column(String(255), nullable=True, comment="当前主阶段名")

    # 运行态字段
    sub_stage: Mapped[str | None] = mapped_column(String(255), nullable=True, default=None, comment="当前子阶段名")
    current: Mapped[int] = mapped_column(Integer, nullable=False, default=0, comment="子阶段已完成单位数")
    total: Mapped[int] = mapped_column(Integer, nullable=False, default=100, comment="子阶段总单位数")
    message: Mapped[str | None] = mapped_column(Text, nullable=True, default=None, comment="进度消息")
    error: Mapped[str | None] = mapped_column(Text, nullable=True, default=None, comment="失败时的错误信息")
    task_kind: Mapped[str] = mapped_column(String(50), nullable=False, default="analysis", comment="任务类型")
    request_payload: Mapped[str | None] = mapped_column(Text, nullable=True, default=None, comment="请求参数快照")
    cancel_requested: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, comment="取消请求标志")
    worker_id: Mapped[str | None] = mapped_column(String(255), nullable=True, default=None, comment="执行者标识")
    heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, default=None, comment="心跳时间")
    started_at: Mapped[datetime | None] = mapped_column(
        DateTime, nullable=True, default=None,
        comment="实际开始执行时间",
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, default=None, comment="完成时间")

    created_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, comment="创建时间")
    updated_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, comment="更新时间")

    def __repr__(self) -> str:
        return (
            f"<AnalysisRun(run_id={self.run_id}, novel_id={self.novel_id}, "
            f"status={self.status}, progress={self.progress})>"
        )
