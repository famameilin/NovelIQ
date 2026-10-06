"""SQLAlchemy 声明式基类定义"""

from datetime import UTC, datetime

from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """SQLAlchemy 声明式基类"""

    pass


def naive_utcnow() -> datetime:
    """无时区列合同：全库时间列统一存 naive UTC 挂钟，时区语义由序列化层管理"""
    return datetime.now(UTC).replace(tzinfo=None)
