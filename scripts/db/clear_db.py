"""
清除数据库所有数据脚本

创建时间: 2026-03-18
创建者: TraeAI
任务: entity-type-relation-extraction
说明: 清除PostgreSQL数据库中的所有表数据，保留表结构
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

# Add project root to Python path
project_root = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(project_root))

from dotenv import load_dotenv  # noqa: E402
from loguru import logger  # noqa: E402
from sqlalchemy import text  # noqa: E402

# Load env from root
env_path = project_root / ".env"
load_dotenv(env_path)

from src.storage.db import get_engine  # noqa: E402


def clear_database() -> None:
    """
    清除数据库中的所有表数据

    注意: 这会删除所有数据，请谨慎使用！
    """
    engine = get_engine()

    # 按照外键依赖顺序删除数据
    tables = [
        "entity_relations",
        "entity_aliases",
        "entities",
        "chunk_relations",
        "chunk_characters",
        "chunk_appearances",
        "annotations",
        "chunks",
        "analysis_stats",
        "analysis_runs",
    ]

    with engine.connect() as conn:
        with conn.begin():
            for table in tables:
                try:
                    conn.execute(text(f"DELETE FROM {table}"))
                    logger.info(f"Cleared table: {table}")
                except Exception as e:
                    logger.warning(f"Failed to clear table {table}: {e}")

    logger.info("Database cleared successfully")


if __name__ == "__main__":
    database_url = os.getenv("DATABASE_URL")
    print(f"Clearing database: {database_url}")
    confirm = input("Are you sure? This will delete ALL data! (yes/no): ")
    if confirm.lower() == "yes":
        clear_database()
        print("Database cleared.")
    else:
        print("Cancelled.")
