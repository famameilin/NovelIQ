"""
测试配置文件

创建时间: 2025-03-11
任务: 测试配置

修改时间: 2026-03-29
任务: fix-duplicate-location-appearance
修改内容: 添加 chunk_locations 表到清理列表

修改时间: 2026-04-05
任务: fix-test-data-pollution
修改内容: 添加 api_client fixture，确保 API 测试使用测试数据库

修改时间: 2026-04-20
任务: fix-test-db-isolation
修改内容: 将后端测试默认数据库强制切换到 TEST_DATABASE，
    并在每个测试前后重置 SQLAlchemy 单例，防止直接调用 get_session_factory() 时污染开发库
"""

from __future__ import annotations

import os
import re
import uuid
from collections.abc import Generator

import pytest
from dotenv import load_dotenv
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event, text
from sqlalchemy.orm import Session, sessionmaker

from src.storage.database_url import resolve_database_url_from_env
from src.storage.models import Base

load_dotenv()

_test_engine = None


def _build_test_schema_name() -> str:
    """
    构造当前 pytest 进程专用的测试 schema 名称。

    创建时间: 2026-04-22
    任务: fix-test-db-concurrency
    说明: 不能再让多个 pytest 进程共享 public schema；
          这里按 worker + pid + 随机后缀生成独立 schema，避免并发 create_all 冲突。
    """
    worker_id = os.environ.get("PYTEST_XDIST_WORKER", "single")
    safe_worker = re.sub(r"[^A-Za-z0-9_]", "_", worker_id)
    return f"test_{safe_worker}_{os.getpid()}_{uuid.uuid4().hex[:8]}"


def _validate_schema_name(schema_name: str) -> str:
    """
    校验 schema 名称是否可安全用于 SQL 标识符。

    创建时间: 2026-04-22
    任务: fix-test-db-concurrency
    说明: 测试会把 schema 名称插入 DDL，必须先限制成 PostgreSQL 安全标识符。
    """
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", schema_name):
        raise ValueError(f"Invalid test schema name: {schema_name}")
    return schema_name


def _build_test_engine(database_url: str, schema_name: str):
    """
    创建绑定到指定测试 schema 的 SQLAlchemy Engine。

    创建时间: 2026-04-22
    任务: fix-test-db-concurrency
    说明: 所有测试连接都应带固定 search_path，确保 ORM 与原生 SQL 落在同一隔离 schema。
    """
    safe_schema = _validate_schema_name(schema_name)
    engine = create_engine(
        database_url,
        echo=False,
        connect_args={
            "options": f"-c search_path={safe_schema},public",
        },
    )

    @event.listens_for(engine, "connect")
    def _set_test_search_path(dbapi_connection, connection_record) -> None:
        # 仅靠 connect_args 在某些建表/复用连接路径上不够稳定，
        # 这里对每条测试连接再次显式固定 search_path，避免表意外落回 public 导致用例互相串数据。
        cursor = dbapi_connection.cursor()
        cursor.execute(f"SET search_path TO {safe_schema}, public")
        cursor.close()

    return engine


def get_test_database_url() -> str:
    """获取测试数据库URL"""
    try:
        return resolve_database_url_from_env("TEST_DATABASE")
    except RuntimeError as exc:
        raise ValueError("TEST_DATABASE 环境变量未设置") from exc


def _reset_backend_db_singletons() -> None:
    """
    重置后端数据库模块中的 Engine / Session 工厂单例。

    创建时间: 2026-04-20
    任务: fix-test-db-isolation
    说明: 测试中存在直接调用 get_session_factory()() 的路径。
    若不在切换 DATABASE 后立即重置单例，这些调用会继续复用旧连接，导致写入开发库。
    """
    from src.storage import db as db_module

    db_module.dispose_engine()
    db_module._engine = None
    db_module._session_factory = None


@pytest.fixture(scope="session")
def test_database_url() -> str:
    """测试数据库URL fixture"""
    return get_test_database_url()


@pytest.fixture(scope="session")
def test_database_schema() -> str:
    """
    当前 pytest 会话使用的独立 schema。

    创建时间: 2026-04-22
    任务: fix-test-db-concurrency
    说明: schema 隔离要在整个测试会话内保持稳定，避免不同 fixture 指到不同空间。
    """
    return _build_test_schema_name()


@pytest.fixture(scope="session")
def setup_test_database(test_database_url: str, test_database_schema: str) -> Generator[None, None, None]:
    """
    会话级别的测试数据库设置

    在测试会话开始时：
    1. 安装 pgvector 扩展
    2. 创建当前 pytest 进程独立 schema
    3. 在该 schema 下创建所有表

    注意：这里不再复用 public，而是让每个 pytest 进程独占一个 schema，
    从根上消除并发 create_all 互相踩表/复合类型的竞争。
    """
    global _test_engine

    safe_schema = _validate_schema_name(test_database_schema)
    _test_engine = _build_test_engine(test_database_url, safe_schema)

    with _test_engine.connect() as conn:
        conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        conn.execute(text(f"DROP SCHEMA IF EXISTS {safe_schema} CASCADE"))
        conn.execute(text(f"CREATE SCHEMA {safe_schema}"))
        conn.commit()

    # 当前 ORM 元数据仍未声明显式 schema，PostgreSQL dialect 的默认建表目标仍是 public。
    # 因此测试会话启动时需要把 public 里的 ORM 表整体重建一次，清掉上次运行残留的固定 run_id/task_id 数据，
    # 否则即便 search_path 指向隔离 schema，未限定表名仍会回落到 public 并撞上旧主键。
    Base.metadata.drop_all(bind=_test_engine)
    Base.metadata.create_all(bind=_test_engine)

    yield

    with _test_engine.connect() as conn:
        conn.execute(text(f"DROP SCHEMA IF EXISTS {safe_schema} CASCADE"))
        conn.commit()

    _test_engine.dispose()
    _test_engine = None


@pytest.fixture(scope="session", autouse=True)
def force_test_database_url(
    setup_test_database: None,
    test_database_url: str,
    test_database_schema: str,
) -> Generator[None, None, None]:
    """
    为整个后端测试会话强制注入测试数据库 URL。

    创建时间: 2026-04-20
    任务: fix-test-db-isolation
    说明:
    - 把 DATABASE 固定为 TEST_DATABASE 的完整 JSON 对象
    - 把 DATABASE_SCHEMA 固定指向当前 pytest 进程独立 schema
    - 覆盖所有直接调用 get_session_factory()() / get_engine() 的路径
    - 会话结束后恢复原始环境变量，避免影响开发命令
    """
    original_database = os.environ.get("DATABASE")
    test_database_config = os.environ.get("TEST_DATABASE")
    if test_database_config is None or not test_database_config.strip():
        raise ValueError("TEST_DATABASE 环境变量未设置")
    original_schema = os.environ.get("DATABASE_SCHEMA")
    os.environ["DATABASE"] = test_database_config
    os.environ["DATABASE_SCHEMA"] = test_database_schema
    _reset_backend_db_singletons()

    try:
        yield
    finally:
        if original_database is not None:
            os.environ["DATABASE"] = original_database
        elif "DATABASE" in os.environ:
            del os.environ["DATABASE"]

        if original_schema is not None:
            os.environ["DATABASE_SCHEMA"] = original_schema
        elif "DATABASE_SCHEMA" in os.environ:
            del os.environ["DATABASE_SCHEMA"]

        _reset_backend_db_singletons()


@pytest.fixture(autouse=True)
def reset_backend_db_singletons_per_test(force_test_database_url: None) -> Generator[None, None, None]:
    """
    每个测试前后都重置后端数据库单例。

    创建时间: 2026-04-20
    任务: fix-test-db-isolation
    说明: 防止前一个测试缓存的 Engine 持有错误连接串，确保当前测试的数据库绑定始终可预测。
    """
    _reset_backend_db_singletons()
    try:
        yield
    finally:
        _reset_backend_db_singletons()


@pytest.fixture
def db_session(setup_test_database: None) -> Generator[Session, None, None]:
    """
    数据库会话 fixture

    每个测试使用独立的事务，测试结束后回滚
    """
    global _test_engine

    if _test_engine is None:
        database_url = get_test_database_url()
        schema_name = _validate_schema_name(os.environ["DATABASE_SCHEMA"])
        _test_engine = _build_test_engine(database_url, schema_name)
        Base.metadata.create_all(bind=_test_engine)

    SessionLocal = sessionmaker(bind=_test_engine)
    session = SessionLocal()
    schema_name = _validate_schema_name(os.environ["DATABASE_SCHEMA"])
    session.execute(text(f"SET search_path TO {schema_name}, public"))

    try:
        yield session
    finally:
        session.rollback()
        session.close()


@pytest.fixture
def insert_test_novel(db_session) -> callable:
    """
    插入测试用 Novel 记录，避免 create_run 时 ForeignKeyViolation。

    创建时间: 2026-04-23
    任务: 修复 pytest ForeignKeyViolation
    """

    def _insert(novel_id: str) -> None:
        from src.storage.models import Novel

        db_session.add(
            Novel(
                novel_id=novel_id,
                filename=f"{novel_id}.txt",
                file_path=f"data/uploads/{novel_id}.txt",
                file_size=128,
            )
        )
        db_session.commit()

    return _insert


@pytest.fixture
def api_client(setup_test_database: None) -> Generator[TestClient, None, None]:
    """
    API 测试客户端 fixture

    创建时间: 2026-04-05
    任务: fix-test-data-pollution
    说明: 基于全局数据库隔离夹具启动 FastAPI TestClient。

    修改时间: 2026-04-20
    任务: fix-test-db-isolation
    修改内容: 删除局部 DATABASE 覆盖逻辑，改为复用全局自动隔离，避免夹具之间出现连接对象切换竞态

    使用方式:
        def test_something(api_client):
            response = api_client.get("/api/novels/")
            assert response.status_code == 200
    """
    _reset_backend_db_singletons()

    from src.api.dependencies import get_task_manager
    from src.api.main import app
    from src.api.services.event_manager import event_manager

    get_task_manager().reset_for_testing()
    event_manager.reset_for_testing()

    client = TestClient(app)
    try:
        yield client
    finally:
        try:
            client.close()
        finally:
            get_task_manager().reset_for_testing()
            event_manager.reset_for_testing()
            _reset_backend_db_singletons()
