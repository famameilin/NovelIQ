"""SQLAlchemy 会话封装与工厂"""

from __future__ import annotations

from sqlalchemy.orm import Session

from src.storage.db import get_session_factory


class DatabaseSession:
    """封装 SQLAlchemy Session 并提供事务上下文"""

    def __init__(self, session: Session, auto_close: bool = True):
        """初始化数据库会话"""
        self._session = session
        self._auto_close = auto_close

    @property
    def connection(self) -> Session:
        """获取底层 SQLAlchemy Session 对象"""
        return self._session

    def execute(self, statement, parameters=None):
        """执行 SQL 语句或 ORM 查询"""
        if parameters is not None:
            return self._session.execute(statement, parameters)
        return self._session.execute(statement)

    def commit(self) -> None:
        """提交事务"""
        self._session.commit()

    def rollback(self) -> None:
        """回滚事务"""
        self._session.rollback()

    def close(self) -> None:
        """关闭会话"""
        if self._session:
            self._session.close()

    def __enter__(self) -> DatabaseSession:
        """进入上下文管理器"""
        return self

    def __exit__(self, exc_type, _exc_val, _exc_tb) -> None:
        """退出上下文管理器，自动提交或回滚"""
        if exc_type is not None:
            self.rollback()
        else:
            self.commit()
        if self._auto_close:
            self.close()


class SessionFactory:
    """创建 PostgreSQL 数据库会话"""

    def get_session(
        self,
        init_tables: bool = False,
        auto_close: bool = True,
    ) -> DatabaseSession:
        """获取数据库会话"""
        if init_tables:
            from src.storage.db import init_db

            init_db()

        session_factory = get_session_factory()
        session = session_factory()
        return DatabaseSession(session, auto_close=auto_close)
