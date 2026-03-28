"""
测试配置文件

创建时间: 2025-03-11
创建者: TraeAI
任务: 测试配置

修改时间: 2026-03-29
修改者: TraeAI
任务: fix-duplicate-location-appearance
修改内容: 添加 chunk_locations 表到清理列表
"""

from __future__ import annotations

import os
from typing import Generator

import pytest
from dotenv import load_dotenv
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, sessionmaker

load_dotenv()

from src.storage.models import Base

_test_engine = None


def get_test_database_url() -> str:
    """获取测试数据库URL"""
    url = os.getenv("TEST_DATABASE_URL")
    if not url:
        raise ValueError("TEST_DATABASE_URL 环境变量未设置")
    return url


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
        "graph_storage",
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
