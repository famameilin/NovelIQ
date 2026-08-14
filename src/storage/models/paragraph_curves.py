"""
段落曲线表 ORM 模型定义

paragraph_curves 保存段落级情绪密度与表层张力曲线（设计文档
《章节粒度分析指标重设计》§5.5）：

- 密度由 paragraph_metrics 的分子/分母计算（pos/neg = 权重命中数 / token 数），
  不保存窗口身份；分母为 0 时密度为 NULL（合法观测，不伪造为零，§15.2）
- 平滑值（smoothed_*）由字符坐标稳健局部回归（LOWESS）生成并持久化，
  平滑参数变化时重算本表（§16）
- 曲线横轴使用真实字符位置（position = 段落中点 / 全书字符数，§9.1），
  不使用段落序号
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import (
    DateTime,
    Float,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
)
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base


def _utcnow() -> datetime:
    """created_at 默认值：UTC 带时区当前时间（避免模块导入期求值）"""
    return datetime.now(UTC)


class ParagraphCurve(Base):
    """
    段落曲线表

    每行对应一个真实段落；原始与平滑指标均使用全量段落计算，
    展示降采样（LTTB）只发生在 API 传输层，不回写本表（§9.4）。
    """

    __tablename__ = "paragraph_curves"

    run_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    paragraph_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    curve_version: Mapped[str] = mapped_column(String, nullable=False)

    pos_density: Mapped[float | None] = mapped_column(Float, nullable=True)
    neg_density: Mapped[float | None] = mapped_column(Float, nullable=True)
    net_density: Mapped[float | None] = mapped_column(Float, nullable=True)
    smoothed_net_density: Mapped[float | None] = mapped_column(Float, nullable=True)

    # 表层张力原始值取自 paragraph_metrics（run 内稳健标准化 + sigmoid），
    # 此处只保存平滑后的展示值
    surface_tension: Mapped[float | None] = mapped_column(Float, nullable=True)
    smoothed_surface_tension: Mapped[float | None] = mapped_column(Float, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )

    __table_args__ = (
        ForeignKeyConstraint(
            ["run_id", "paragraph_id"],
            ["paragraphs.run_id", "paragraphs.paragraph_id"],
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["run_id"],
            ["analysis_runs.run_id"],
            ondelete="CASCADE",
        ),
        Index("idx_paragraph_curves_run_paragraph", "run_id", "paragraph_id"),
    )

    def __repr__(self) -> str:
        return f"<ParagraphCurve(run_id={self.run_id}, paragraph_id={self.paragraph_id})>"
