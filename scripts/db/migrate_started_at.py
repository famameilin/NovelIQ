"""
创建时间: 2026-04-20
创建者: TraeAI
任务: task-system-db-driven-refactor
说明: 为 analysis_runs 表添加 started_at 字段，记录任务实际开始执行时间
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

from dotenv import load_dotenv
from sqlalchemy import create_engine, text


def _apply_schema_upgrade(database_url: str) -> None:
    engine = create_engine(database_url)
    print(f"\n=== Upgrading schema: {database_url} ===")

    with engine.begin() as conn:
        conn.execute(
            text(
                "ALTER TABLE analysis_runs ADD COLUMN IF NOT EXISTS started_at TIMESTAMP WITHOUT TIME ZONE"
            )
        )
        print("[OK] Added started_at column to analysis_runs")

    print("started_at schema upgrade completed.")


def main() -> None:
    project_root = Path(__file__).resolve().parents[2]
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
