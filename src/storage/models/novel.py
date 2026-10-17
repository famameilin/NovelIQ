"""
小说表 ORM 模型定义

存储小说元数据，解决上传后列表不显示的问题

2026-10-16 全库 3NF 改造：novel_id 沿用当前登记身份 VARCHAR(255)（不再按历史
样本长度收窄为 8 字符）；filename/title/author 都不唯一，novel_id 是唯一候选键。
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import BigInteger, DateTime, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base


class Novel(Base):
    """
    小说表

    存储小说元数据，上传后立即可查
    """

    __tablename__ = "novels"
    __table_args__ = {"comment": "小说元数据表：上传文件登记，novel_id 是全部分析数据的隔离主键根"}

    novel_id: Mapped[str] = mapped_column(String(255), primary_key=True, comment="小说主键")
    filename: Mapped[str | None] = mapped_column(String(500), nullable=True, comment="上传原始文件名")
    file_path: Mapped[str | None] = mapped_column(Text, nullable=True, comment="原始文件存储路径")
    title: Mapped[str | None] = mapped_column(String(500), nullable=True, comment="书名")
    author: Mapped[str | None] = mapped_column(String(255), nullable=True, comment="作者")
    file_size: Mapped[int | None] = mapped_column(BigInteger, nullable=True, comment="原始文件字节数")
    upload_time: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, comment="上传时间")

    def __repr__(self) -> str:
        return f"<Novel(novel_id={self.novel_id}, title={self.title})>"
