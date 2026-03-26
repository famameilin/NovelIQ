"""
创建时间: 2026-03-14
创建者: TraeAI
任务: 创建 Session 管理机制
说明: 提供 DatabaseSession 类封装数据库连接，SessionFactory 管理连接池，以及辅助函数

修改时间: 2026-03-15
修改者: TraeAI
任务: postgresql-migration
修改内容: 重写为 SQLAlchemy Session 管理，移除 SQLite 相关逻辑

本模块提供数据库会话管理机制：
- DatabaseSession: 封装 SQLAlchemy Session，支持上下文管理器和事务管理
- SessionFactory: 管理数据库会话工厂
- get_session: 辅助函数，方便获取会话
"""

from __future__ import annotations

from collections.abc import Generator
from contextlib import contextmanager

from sqlalchemy.orm import Session

from src.storage.db import get_session_factory


class DatabaseSession:
    """
    数据库会话类，封装 SQLAlchemy Session

    创建时间: 2026-03-14
    创建者: TraeAI
    任务: 创建 Session 管理机制
    说明: 提供上下文管理器支持，封装事务管理，支持依赖注入

    修改时间: 2026-03-15
    修改者: TraeAI
    任务: postgresql-migration
    修改内容: 重写为 SQLAlchemy Session 封装

    使用示例:
        with DatabaseSession() as session:
            session.execute(text("SELECT * FROM chunks"))
            session.commit()
    """

    def __init__(self, session: Session, auto_close: bool = True):
        """
        初始化数据库会话

        Args:
            session: SQLAlchemy Session 对象
            auto_close: 是否在退出上下文管理器时自动关闭连接，默认 True
        """
        self._session = session
        self._auto_close = auto_close
        self._in_transaction = False

    @property
    def connection(self) -> Session:
        """获取底层 SQLAlchemy Session 对象"""
        return self._session

    def execute(self, statement, parameters=None):
        """
        执行 SQL 语句

        Args:
            statement: SQL 语句或 ORM 查询
            parameters: 参数（可选）

        Returns:
            执行结果
        """
        if parameters is not None:
            return self._session.execute(statement, parameters)
        return self._session.execute(statement)

    def executemany(self, statement, parameters):
        """
        批量执行 SQL 语句

        Args:
            statement: SQL 语句
            parameters: 参数列表

        Returns:
            执行结果
        """
        return self._session.execute(statement, parameters)

    def commit(self) -> None:
        """提交事务"""
        self._session.commit()
        self._in_transaction = False

    def rollback(self) -> None:
        """回滚事务"""
        self._session.rollback()
        self._in_transaction = False

    def close(self) -> None:
        """关闭会话"""
        if self._session:
            self._session.close()

    def begin_transaction(self) -> None:
        """显式开始事务"""
        self._session.begin()
        self._in_transaction = True

    def is_in_transaction(self) -> bool:
        """检查是否在事务中"""
        return self._in_transaction

    def __enter__(self) -> DatabaseSession:
        """进入上下文管理器"""
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        """退出上下文管理器，自动提交或回滚"""
        if exc_type is not None:
            self.rollback()
        if self._auto_close:
            self.close()

    def cursor(self):
        """创建游标（兼容旧代码）"""
        return self._session.connection()


class SessionFactory:
    """
    会话工厂类，管理数据库会话

    创建时间: 2026-03-14
    创建者: TraeAI
    任务: 创建 Session 管理机制
    说明: SQLAlchemy Session 工厂，支持单一 PostgreSQL 数据库

    修改时间: 2026-03-15
    修改者: TraeAI
    任务: postgresql-migration
    修改内容: 移除 base_dir 和 .db 文件路径逻辑，使用单一数据库

    使用示例:
        factory = SessionFactory()
        session = factory.get_session()
        with session:
            session.execute(text("SELECT * FROM chunks"))
    """

    def __init__(self, base_dir=None):
        """
        初始化会话工厂

        Args:
            base_dir: 保留参数（向后兼容），不再使用
        """
        self._sessions: dict[str, DatabaseSession] = {}

    def get_session(
        self,
        identifier: str | None = None,
        init_tables: bool = False,
        auto_close: bool = True,
    ) -> DatabaseSession:
        """
        获取数据库会话

        Args:
            identifier: 任务标识符（保留参数，向后兼容）
            init_tables: 是否初始化表结构，默认 False
            auto_close: 是否自动关闭连接，默认 True

        Returns:
            DatabaseSession 实例
        """
        if init_tables:
            from src.storage.db import init_db

            init_db()

        session_factory = get_session_factory()
        session = session_factory()
        return DatabaseSession(session, auto_close=auto_close)

    def create_session(
        self,
        init_tables: bool = False,
        auto_close: bool = True,
    ) -> DatabaseSession:
        """
        创建新的数据库会话

        Args:
            init_tables: 是否初始化表结构，默认 False
            auto_close: 是否自动关闭连接，默认 True

        Returns:
            DatabaseSession 实例
        """
        return self.get_session(init_tables=init_tables, auto_close=auto_close)

    def get_or_create_session(
        self,
        identifier: str,
        init_tables: bool = False,
    ) -> DatabaseSession:
        """
        获取或创建会话（带缓存）

        注意：使用缓存的会话不会自动关闭，需要手动调用 close_cached_session

        Args:
            identifier: 任务标识符
            init_tables: 是否初始化表结构，默认 False

        Returns:
            DatabaseSession 实例
        """
        if identifier in self._sessions:
            return self._sessions[identifier]

        session = self.get_session(identifier, init_tables=init_tables, auto_close=False)
        self._sessions[identifier] = session
        return session

    def close_cached_session(self, identifier: str) -> None:
        """
        关闭缓存的会话

        Args:
            identifier: 任务标识符
        """
        if identifier in self._sessions:
            self._sessions[identifier].close()
            del self._sessions[identifier]

    def close_all_cached_sessions(self) -> None:
        """关闭所有缓存的会话"""
        for session in self._sessions.values():
            session.close()
        self._sessions.clear()

    @contextmanager
    def session_context(
        self,
        identifier: str | None = None,
        init_tables: bool = False,
    ) -> Generator[DatabaseSession, None, None]:
        """
        上下文管理器方式获取会话

        Args:
            identifier: 任务标识符（保留参数）
            init_tables: 是否初始化表结构

        Yields:
            DatabaseSession 实例
        """
        session = self.get_session(identifier, init_tables=init_tables, auto_close=True)
        try:
            yield session
        finally:
            session.close()


def get_db_session(init_tables: bool = False) -> DatabaseSession:
    """
    获取数据库会话的辅助函数

    创建时间: 2026-03-14
    创建者: TraeAI
    任务: 创建 Session 管理机制
    说明: 简便函数，获取 DatabaseSession

    修改时间: 2026-03-15
    修改者: TraeAI
    任务: postgresql-migration
    修改内容: 使用 SQLAlchemy Session

    Args:
        init_tables: 是否初始化表结构，默认 False

    Returns:
        DatabaseSession 实例

    使用示例:
        with get_db_session() as session:
            cursor = session.execute(text("SELECT * FROM chunks"))
            rows = cursor.fetchall()
    """
    factory = SessionFactory()
    return factory.get_session(init_tables=init_tables, auto_close=True)


def get_session_from_run_id(
    run_id: str,
    base_dir=None,
    init_tables: bool = False,
) -> DatabaseSession:
    """
    从 run_id 获取数据库会话

    创建时间: 2026-03-14
    创建者: TraeAI
    任务: 创建 Session 管理机制
    说明: 简便函数，从 run_id 获取 DatabaseSession

    修改时间: 2026-03-15
    修改者: TraeAI
    任务: postgresql-migration
    修改内容: 移除 base_dir 参数依赖，使用单一数据库

    Args:
        run_id: 运行标识符
        base_dir: 保留参数（向后兼容），不再使用
        init_tables: 是否初始化表结构，默认 False

    Returns:
        DatabaseSession 实例

    使用示例:
        with get_session_from_run_id("abc123") as session:
            cursor = session.execute(text("SELECT * FROM chunks"))
            rows = cursor.fetchall()
    """
    factory = SessionFactory()
    return factory.get_session(identifier=run_id, init_tables=init_tables, auto_close=True)


get_session_from_task_id = get_session_from_run_id
