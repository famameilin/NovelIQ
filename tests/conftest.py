"""测试配置文件"""

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
    """构造当前 pytest 进程专用的测试 schema 名称。

    这里按 worker + pid + 随机后缀生成独立 schema，避免并发 create_all 冲突。
    """
    worker_id = os.environ.get("PYTEST_XDIST_WORKER", "single")
    safe_worker = re.sub(r"[^A-Za-z0-9_]", "_", worker_id)
    return f"test_{safe_worker}_{os.getpid()}_{uuid.uuid4().hex[:8]}"


def _validate_schema_name(schema_name: str) -> str:
    """校验 schema 名称是否可安全用于 SQL 标识符。

    测试会把 schema 名称插入 DDL，必须先限制成 PostgreSQL 安全标识符。
    """
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", schema_name):
        raise ValueError(f"Invalid test schema name: {schema_name}")
    return schema_name


def _build_test_engine(database_url: str, schema_name: str):
    """创建绑定到指定测试 schema 的 SQLAlchemy Engine。

    所有测试连接都应带固定 search_path，确保 ORM 与原生 SQL 落在同一隔离 schema。
    """
    safe_schema = _validate_schema_name(schema_name)
    engine = create_engine(
        database_url,
        echo=False,
        connect_args={
            "options": f"-c search_path={safe_schema},public",
        },
        execution_options={"schema_translate_map": {None: safe_schema}},
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
    """重置后端数据库模块中的 Engine / Session 工厂单例。

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
    """当前 pytest 会话使用的独立 schema。

    schema 隔离要在整个测试会话内保持稳定，避免不同 fixture 指到不同空间。
    """
    return _build_test_schema_name()


def _create_all_orm_tables(engine) -> None:
    """与生产 init_db 同口径：建全部 35 张基表并安装领域约束触发器"""
    from src.storage.constraints import install_domain_constraints

    Base.metadata.create_all(bind=engine)
    install_domain_constraints(engine)


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
        conn.execute(text("CREATE EXTENSION IF NOT EXISTS pg_trgm"))
        conn.execute(text(f"CREATE SCHEMA {safe_schema}"))
        conn.commit()

    # 显式翻译无 schema 的元数据，禁止 create_all/drop_all 回落到 public
    _create_all_orm_tables(_test_engine)

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
    """为整个后端测试会话强制注入测试数据库 URL。"""
    database_fields = ("DATABASE_URL", "DATABASE_USERNAME", "DATABASE_PASSWORD")
    test_database_fields = ("TEST_DATABASE_URL", "TEST_DATABASE_USERNAME", "TEST_DATABASE_PASSWORD")
    original_database = {field: os.environ.get(field) for field in database_fields}
    for database_field, test_database_field in zip(database_fields, test_database_fields, strict=True):
        test_database_value = os.environ.get(test_database_field)
        if test_database_value is None or not test_database_value.strip():
            raise ValueError(f"{test_database_field} 环境变量未设置")
        os.environ[database_field] = test_database_value
    original_schema = os.environ.get("DATABASE_SCHEMA")
    os.environ["DATABASE_SCHEMA"] = test_database_schema
    _reset_backend_db_singletons()

    try:
        yield
    finally:
        for database_field, original_value in original_database.items():
            if original_value is not None:
                os.environ[database_field] = original_value
            else:
                os.environ.pop(database_field, None)

        if original_schema is not None:
            os.environ["DATABASE_SCHEMA"] = original_schema
        elif "DATABASE_SCHEMA" in os.environ:
            del os.environ["DATABASE_SCHEMA"]

        _reset_backend_db_singletons()


@pytest.fixture(autouse=True)
def reset_backend_db_singletons_per_test(force_test_database_url: None) -> Generator[None, None, None]:
    """每个测试前后都重置后端数据库单例。

    防止前一个测试缓存的 Engine 持有错误连接串，确保当前测试的数据库绑定始终可预测。
    """
    _reset_backend_db_singletons()
    try:
        yield
    finally:
        _reset_backend_db_singletons()


@pytest.fixture(autouse=True)
def reset_capacity_and_event_bus() -> Generator[None, None, None]:
    """每个测试后重置模型池容量账本与事件总线单例。"""
    from src.event_bus import EVENT_BUS
    from src.model_pool.capacity import MODEL_CAPACITY

    MODEL_CAPACITY.reset()
    EVENT_BUS.reset()
    try:
        yield
    finally:
        MODEL_CAPACITY.reset()
        EVENT_BUS.reset()


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
        _create_all_orm_tables(_test_engine)

    SessionLocal = sessionmaker(bind=_test_engine)
    session = SessionLocal()
    session.info["fixture_shared"] = True
    schema_name = _validate_schema_name(os.environ["DATABASE_SCHEMA"])
    session.execute(text(f"SET search_path TO {schema_name}, public"))

    try:
        yield session
    finally:
        session.rollback()
        session.close()


@pytest.fixture
def configured_model_pool(monkeypatch) -> None:
    """队列测试使用明确的假模型配置，不依赖开发者的真实 Key"""
    from src.config import settings
    from src.config.schemas.model import WeightedModelSettings

    monkeypatch.setattr(
        settings.models,
        "model_pool",
        [
            WeightedModelSettings("test-model", "https://test.example/v1", "test-key", max_in_flight=2),
        ],
    )
    monkeypatch.setattr(settings.models, "diagnosis_model_id", "test-model")


@pytest.fixture
def pipeline_run_cleanup(configured_model_pool: None) -> Generator[None, None, None]:
    """隔离测试 run 与进程内容量位账本，不能让前一测试占用后续测试的全局槽位"""
    from sqlalchemy import select

    from src.model_pool.capacity import MODEL_CAPACITY
    from src.storage.db import get_session_factory
    from src.storage.models import AnalysisRun

    factory = get_session_factory()
    with factory() as session:
        existing = set(session.execute(select(AnalysisRun.run_id)).scalars())
    try:
        yield
    finally:
        MODEL_CAPACITY.reset()
        with factory() as session, session.begin():
            created = set(session.execute(select(AnalysisRun.run_id)).scalars()) - existing
            for run_id in created:
                run = session.get(AnalysisRun, run_id)
                if run is not None and run.status in {"pending", "running", "cancelling"}:
                    run.status = "cancelled"


@pytest.fixture
def api_client(setup_test_database: None) -> Generator[TestClient, None, None]:
    """API 测试客户端 fixture

    基于全局数据库隔离夹具启动 FastAPI TestClient。

    使用方式:
        def test_something(api_client):
            response = api_client.get("/api/novels/")
            assert response.status_code == 200
    """
    _reset_backend_db_singletons()

    from src.api.dependencies import get_task_manager
    from src.api.main import app
    from src.sse.manager import event_manager

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


@pytest.fixture(autouse=True)
def reset_fixture_identifiers():
    "同一测试内的标签共享 UUIDv7，不同测试独立分配"
    from tests.support.storage_fixtures import _stub_task_id, fixture_id

    fixture_id.cache_clear()
    _stub_task_id.cache_clear()
