"""
小说表 ORM 模型定义

存储小说元数据，解决上传后列表不显示的问题
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base


class Novel(Base):
    """
    小说表

    存储小说元数据，上传后立即可查
    """

    __tablename__ = "novels"
    __table_args__ = {"comment": "小说元数据表：上传文件登记，novel_id 是全部分析数据的隔离主键根"}

    novel_id: Mapped[str] = mapped_column(String(8), primary_key=True, comment="小说主键（8 位短 ID）")
    filename: Mapped[str | None] = mapped_column(String(500), nullable=True, comment="上传原始文件名")
    file_path: Mapped[str | None] = mapped_column(Text, nullable=True, comment="原始文件存储路径")
    title: Mapped[str | None] = mapped_column(String(500), nullable=True, comment="书名")
    author: Mapped[str | None] = mapped_column(String(255), nullable=True, comment="作者")
    file_size: Mapped[int | None] = mapped_column(Integer, nullable=True, comment="文件字节数")
    upload_time: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, comment="上传时间")

    def __repr__(self) -> str:
        return f"<Novel(novel_id={self.novel_id}, title={self.title})>"
