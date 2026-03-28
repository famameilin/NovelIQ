"""
地点相关数据模型

创建时间: 2026-03-28
创建者: TraeAI
任务: implement-location-entity-type
说明: 定义地点相关的数据模型
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel
from sqlalchemy import Integer, String, Text, ForeignKey, Index
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base


class LocationAppearance(BaseModel):
    """
    地点出现记录（Phase1 输出格式）

    创建时间: 2026-03-28
    创建者: TraeAI
    任务: implement-location-entity-type
    """

    raw_name: str
    location_type: Literal["room", "building", "area"] | None = None


class ChunkLocation(Base):
    """
    chunk 地点表

    创建时间: 2026-03-28
    创建者: TraeAI
    任务: implement-location-entity-type
    说明: 存储每个 chunk 中出现的地点
    """

    __tablename__ = "chunk_locations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    chunk_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    location_name: Mapped[str] = mapped_column(String(255), nullable=False)
    location_type: Mapped[str | None] = mapped_column(String(50), nullable=True)
    run_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("analysis_runs.run_id", ondelete="CASCADE"), nullable=False, index=True
    )
    novel_id: Mapped[str] = mapped_column(String(255), nullable=False, index=True)

    __table_args__ = (
        Index("idx_chunk_locations_chunk_id", "chunk_id"),
        Index("idx_chunk_locations_run_id", "run_id"),
        Index("idx_chunk_locations_novel_id", "novel_id"),
    )

    def __repr__(self) -> str:
        return f"<ChunkLocation(id={self.id}, location_name={self.location_name})>"
