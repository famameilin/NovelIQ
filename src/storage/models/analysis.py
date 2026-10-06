"""
分析结果相关表 ORM 模型定义

本模块定义分析结果相关的数据表：
- GlobalStats: 全局统计表

2026-10-06 表合并：CloudAnalysis 云端分析宽表已并入 analysis_outputs（kind='cloud_analysis'）。
"""

from __future__ import annotations

from sqlalchemy import Float, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base


class GlobalStats(Base):
    """
    全局统计表

    存储全局统计数据

    将主键改为复合主键 (stat_name, run_id)，支持多 run 数据隔离
    """

    __tablename__ = "global_stats"
    __table_args__ = {"comment": "全局统计表：run 级标量统计指标（名称 → 值）"}

    stat_name: Mapped[str] = mapped_column(String(255), primary_key=True, comment="统计项名称")
    stat_value: Mapped[float | None] = mapped_column(Float, nullable=True, comment="统计值")
    run_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("analysis_runs.run_id", ondelete="CASCADE"),
        primary_key=True,
        comment="所属分析运行",
    )

    def __repr__(self) -> str:
        return f"<GlobalStats(stat_name={self.stat_name}, run_id={self.run_id})"
