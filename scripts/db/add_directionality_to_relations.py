"""
添加 directionality 字段到 chunk_relations 表

创建时间: 2026-04-05
创建者: TraeAI
任务: phase4-code-review-fix
说明: 为 chunk_relations 表添加 directionality 字段，存储关系方向性（directed/symmetric）
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

from dotenv import load_dotenv
from sqlalchemy import create_engine, text

project_root = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(project_root))


def _apply_schema_upgrade(database_url: str) -> None:
    engine = create_engine(database_url)
    print(f"\n=== Upgrading schema: {database_url} ===")

    statements = [
        "ALTER TABLE chunk_relations ADD COLUMN IF NOT EXISTS directionality VARCHAR(20) DEFAULT 'directed'",
    ]

    with engine.begin() as conn:
        for sql in statements:
            conn.execute(text(sql))

    print("Directionality column added to chunk_relations table.")


def main() -> None:
    load_dotenv(project_root / ".env")
    db_urls = []
    for name in ("DATABASE_URL", "TEST_DATABASE_URL"):
        value = os.getenv(name)
        if value:
            db_urls.append(value)

    if not db_urls:
        raise RuntimeError("DATABASE_URL or TEST_DATABASE_URL must be set")

    for url in db_urls:
        _apply_schema_upgrade(url)


if __name__ == "__main__":
    main()
