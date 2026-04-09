"""
小说表 ORM 模型定义

创建时间: 2026-04-08
创建者: TraeAI
任务: add-novels-table
说明: 存储小说元数据，解决上传后列表不显示的问题
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base


class Novel(Base):
    """
    小说表

    创建时间: 2026-04-08
    创建者: TraeAI
    任务: add-novels-table
    说明: 存储小说元数据，上传后立即可查
    """

    __tablename__ = "novels"

    novel_id: Mapped[str] = mapped_column(String(8), primary_key=True)
    filename: Mapped[str | None] = mapped_column(String(500), nullable=True)
    file_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    title: Mapped[str | None] = mapped_column(String(500), nullable=True)
    author: Mapped[str | None] = mapped_column(String(255), nullable=True)
    file_size: Mapped[int | None] = mapped_column(Integer, nullable=True)
    upload_time: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    def __repr__(self) -> str:
        return f"<Novel(novel_id={self.novel_id}, title={self.title})>"
