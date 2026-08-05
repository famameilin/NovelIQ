"""
已退出主链的身份消歧检查点 ORM 模型
"""

from __future__ import annotations

from sqlalchemy import Float, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from src.storage.models.base import Base


class DisambigCheckpoint(Base):
    """归档的身份消歧检查点表"""

    __tablename__ = "disambig_checkpoint"

    run_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("analysis_runs.run_id", ondelete="CASCADE", name="disambig_checkpoint_run_id_fkey"),
        primary_key=True,
    )
    state_json: Mapped[str] = mapped_column(Text, nullable=False)
    updated_at: Mapped[float] = mapped_column(Float, nullable=False)

    def __repr__(self) -> str:
        """2026-08-05 用于保留归档模型的调试显示"""
        return f"<DisambigCheckpoint(run_id={self.run_id}, updated_at={self.updated_at})>"
