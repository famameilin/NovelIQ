"""
地点相关数据模型

创建时间: 2026-03-28
创建者: TraeAI
任务: implement-location-entity-type
说明: 定义地点相关的数据模型
"""

from __future__ import annotations

from sqlalchemy import ForeignKey, ForeignKeyConstraint, Index, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base


class ChunkLocation(Base):
    """
    chunk 地点表

    创建时间: 2026-03-28
    创建者: TraeAI
    任务: implement-location-entity-type
    说明: 存储每个 chunk 中出现的地点

    修改时间: 2026-04-22
    修改者: Codex
    任务: fix-analysis-related-foreign-keys
    修改内容: 为 novel_id 与 (chunk_id, run_id) 补充外键约束，避免地点记录脱离小说和 chunk 主表。
    """

    __tablename__ = "chunk_locations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    chunk_id: Mapped[int] = mapped_column(Integer, nullable=False)
    location_name: Mapped[str] = mapped_column(String(255), nullable=False)
    location_type: Mapped[str | None] = mapped_column(String(50), nullable=True)
    run_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("analysis_runs.run_id", ondelete="CASCADE"), nullable=False
    )
    novel_id: Mapped[str] = mapped_column(String(255), nullable=False)

    __table_args__ = (
        ForeignKeyConstraint(
            ["chunk_id", "run_id"],
            ["chunks.chunk_id", "chunks.run_id"],
            ondelete="CASCADE",
            name="chunk_locations_chunk_id_run_id_fkey",
        ),
        ForeignKeyConstraint(
            ["novel_id"],
            ["novels.novel_id"],
            ondelete="RESTRICT",
            name="chunk_locations_novel_id_fkey",
        ),
        Index("idx_chunk_locations_chunk_id", "chunk_id"),
        Index("idx_chunk_locations_run_id", "run_id"),
        Index("idx_chunk_locations_novel_id", "novel_id"),
    )

    def __repr__(self) -> str:
        return f"<ChunkLocation(id={self.id}, location_name={self.location_name})>"
