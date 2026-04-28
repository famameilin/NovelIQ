"""
定义 Repository 基类，提供数据库连接的封装

从 sqlite3.Connection 迁移到 SQLAlchemy Session
"""

from __future__ import annotations

from typing import TypeVar

from sqlalchemy.orm import Session

T = TypeVar("T")


class BaseRepository[T]:
    """
    Repository 基类

    所有 Repository 实现类的基类，封装数据库连接。
    使用泛型 T 表示操作的实体类型。

    从 sqlite3.Connection 迁移到 SQLAlchemy Session
    """

    def __init__(self, session: Session):
        self._session = session

    @property
    def session(self) -> Session:
        """获取 SQLAlchemy Session"""
        return self._session
