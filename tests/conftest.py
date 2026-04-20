"""
测试配置文件

创建时间: 2025-03-11
创建者: TraeAI
任务: 测试配置

修改时间: 2026-03-29
修改者: TraeAI
任务: fix-duplicate-location-appearance
修改内容: 添加 chunk_locations 表到清理列表

修改时间: 2026-04-05
修改者: AI Assistant
任务: fix-test-data-pollution
修改内容: 添加 api_client fixture，确保 API 测试使用测试数据库

修改时间: 2026-04-20
修改者: Codex (GPT-5)
任务: fix-test-db-isolation
修改内容: 将后端测试默认数据库强制切换到 TEST_DATABASE_URL，并在每个测试前后重置 SQLAlchemy 单例，防止直接调用 get_session_factory() 时污染开发库
"""

from __future__ import annotations

import os
from collections.abc import Generator

import pytest
from dotenv import load_dotenv
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, sessionmaker

from src.storage.models import Base

load_dotenv()

_test_engine = None


def get_test_database_url() -> str:
    """获取测试数据库URL"""
    url = os.getenv("TEST_DATABASE_URL")
    if not url:
        raise ValueError("TEST_DATABASE_URL 环境变量未设置")
    return url


def _reset_backend_db_singletons() -> None:
    """
    重置后端数据库模块中的 Engine / Session 工厂单例。

    创建时间: 2026-04-20
    创建者: Codex (GPT-5)
    任务: fix-test-db-isolation
    说明: 测试中存在直接调用 get_session_factory()() 的路径。
    若不在切换 DATABASE_URL 后立即重置单例，这些调用会继续复用旧连接，导致写入开发库。
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
def setup_test_database(test_database_url: str) -> Generator[None, None, None]:
    """
    会话级别的测试数据库设置

    在测试会话开始时：
    1. 安装 pgvector 扩展
    2. 删除所有旧表
    3. 创建所有表

    注意：使用全局 engine 避免并发创建表
    """
    global _test_engine

    _test_engine = create_engine(test_database_url, echo=False)

    with _test_engine.connect() as conn:
        conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        conn.commit()

    tables = [
        "emotion_curve",
        "rhythm_curve",
        "global_stats",
        "cloud_analysis",
        "chunk_dialogues",
        "chunk_characters",
        "chunk_relations",
        "character_appearances",
        "chunk_style",
        "chunk_topics",
        "chunk_summaries",
        "chunk_culture",
        "chunk_embeddings",
        "chunk_annotation",
        "chunks",
        "analysis_runs",
        "global_context",
        "token_usage",
        "graph_relations_current",
        "graph_relation_events",
        "graph_entity_aliases",
        "graph_entities",
        "novels",
        "entity_knowledge_graph",
        "entity_aliases",
        "entity_relations",
        "entity_snapshots",
        "diagnosis_results",
        "topic_model_results",
        "preprocess_results",
        "disambig_checkpoint",
        "chunk_locations",
    ]
    with _test_engine.connect() as conn:
        for table in tables:
            conn.execute(text(f"DROP TABLE IF EXISTS {table} CASCADE"))
        conn.commit()

    Base.metadata.create_all(bind=_test_engine)

    yield

    _test_engine.dispose()
    _test_engine = None


@pytest.fixture(scope="session", autouse=True)
def force_test_database_url(setup_test_database: None, test_database_url: str) -> Generator[None, None, None]:
    """
    为整个后端测试会话强制注入测试数据库 URL。

    创建时间: 2026-04-20
    创建者: Codex (GPT-5)
    任务: fix-test-db-isolation
    说明:
    - 把 DATABASE_URL 固定指向 TEST_DATABASE_URL
    - 覆盖所有直接调用 get_session_factory()() / get_engine() 的路径
    - 会话结束后恢复原始环境变量，避免影响开发命令
    """
    original_url = os.environ.get("DATABASE_URL")
    os.environ["DATABASE_URL"] = test_database_url
    _reset_backend_db_singletons()

    try:
        yield
    finally:
        if original_url is not None:
            os.environ["DATABASE_URL"] = original_url
        elif "DATABASE_URL" in os.environ:
            del os.environ["DATABASE_URL"]

        _reset_backend_db_singletons()


@pytest.fixture(autouse=True)
def reset_backend_db_singletons_per_test(force_test_database_url: None) -> Generator[None, None, None]:
    """
    每个测试前后都重置后端数据库单例。

    创建时间: 2026-04-20
    创建者: Codex (GPT-5)
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
        _test_engine = create_engine(get_test_database_url(), echo=False)
        Base.metadata.create_all(bind=_test_engine)

    SessionLocal = sessionmaker(bind=_test_engine)
    session = SessionLocal()

    try:
        yield session
    finally:
        session.rollback()
        session.close()


@pytest.fixture
def api_client(setup_test_database: None) -> Generator[TestClient, None, None]:
    """
    API 测试客户端 fixture

    创建时间: 2026-04-05
    创建者: AI Assistant
    任务: fix-test-data-pollution
    说明: 基于全局数据库隔离夹具启动 FastAPI TestClient。

    修改时间: 2026-04-20
    修改者: Codex (GPT-5)
    任务: fix-test-db-isolation
    修改内容: 删除局部 DATABASE_URL 覆盖逻辑，改为复用全局自动隔离，避免夹具之间出现连接串切换竞态

    使用方式:
        def test_something(api_client):
            response = api_client.get("/api/novels/")
            assert response.status_code == 200
    """
    _reset_backend_db_singletons()

    from src.api.main import app

    client = TestClient(app)

    try:
        yield client
    finally:
        _reset_backend_db_singletons()
