"""
创建时间: 2026-03-14
创建者: TraeAI
任务: Repository 基类和 Protocol 接口定义
说明: 定义 Repository 基类，提供数据库连接的封装

修改时间: 2026-03-15
修改者: TraeAI
任务: postgresql-migration
修改内容: 从 sqlite3.Connection 迁移到 SQLAlchemy Session
"""

from __future__ import annotations

from typing import TypeVar

from sqlalchemy.orm import Session

T = TypeVar("T")


class BaseRepository[T]:
    """
    Repository 基类

    创建时间: 2026-03-14
    创建者: TraeAI
    任务: Repository 基类和 Protocol 接口定义
    说明: 所有 Repository 实现类的基类，封装数据库连接。
    使用泛型 T 表示操作的实体类型。

    修改时间: 2026-03-15
    修改者: TraeAI
    任务: postgresql-migration
    修改内容: 从 sqlite3.Connection 迁移到 SQLAlchemy Session
    """

    def __init__(self, session: Session):
        self._session = session

    @property
    def session(self) -> Session:
        """获取 SQLAlchemy Session"""
        return self._session
