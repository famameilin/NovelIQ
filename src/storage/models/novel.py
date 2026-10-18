"小说表 ORM 模型定义"

from __future__ import annotations

from datetime import datetime

from sqlalchemy import BigInteger, DateTime, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from src.storage.ids import new_id
from src.storage.uuid_type import Uuid7 as Uuid

from .base import Base


class Novel(Base):
    "小说表"

    __tablename__ = "novels"
    __table_args__ = {"comment": "小说元数据表：上传文件登记，novel_id 是全部分析数据的隔离主键根"}

    novel_id: Mapped[str] = mapped_column(
        Uuid(as_uuid=False), primary_key=True, comment="小说主键", default=new_id, autoincrement=False
    )
    filename: Mapped[str | None] = mapped_column(String(500), nullable=True, comment="上传原始文件名")
    file_path: Mapped[str | None] = mapped_column(Text, nullable=True, comment="原始文件存储路径")
    title: Mapped[str | None] = mapped_column(String(500), nullable=True, comment="书名")
    author: Mapped[str | None] = mapped_column(String(255), nullable=True, comment="作者")
    file_size: Mapped[int | None] = mapped_column(BigInteger, nullable=True, comment="原始文件字节数")
    upload_time: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, comment="上传时间")

    def __repr__(self) -> str:
        return f"<Novel(novel_id={self.novel_id}, title={self.title})>"
