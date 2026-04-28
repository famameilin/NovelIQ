"""
迁移 chunk_dialogues.speaker 列类型：text → text[]

不需要兼容旧数据，直接清空后改列类型。

使用方法：
    uv run python scripts/db/migrate_speaker_to_array.py
"""

from __future__ import annotations

import os
import sys

from dotenv import load_dotenv
from loguru import logger
from sqlalchemy import create_engine, text

load_dotenv()


def migrate() -> None:
    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        logger.error("DATABASE_URL environment variable is not set")
        sys.exit(1)

    engine = create_engine(database_url)

    with engine.connect() as conn:
        # 1. 检查当前列类型
        result = conn.execute(
            text(
                "SELECT data_type, udt_name FROM information_schema.columns "
                "WHERE table_name = 'chunk_dialogues' AND column_name = 'speaker'"
            )
        )
        row = result.fetchone()
        if row is None:
            logger.error("chunk_dialogues.speaker column not found")
            sys.exit(1)

        current_type = row[0]
        current_udt = row[1]
        logger.info(f"Current speaker column type: {current_type} (udt_name={current_udt})")

        if current_udt == "_text" or current_type == "ARRAY":
            logger.info("Column is already text[] type, no migration needed")
            return

        # 2. 删除所有旧数据（不需要兼容）
        delete_result = conn.execute(text("DELETE FROM chunk_dialogues"))
        logger.info(f"Deleted {delete_result.rowcount} rows from chunk_dialogues")

        # 3. 改列类型
        conn.execute(text("ALTER TABLE chunk_dialogues ALTER COLUMN speaker TYPE text[] USING NULL"))
        conn.commit()
        logger.info("Migration completed successfully")

        # 4. 验证
        verify_result = conn.execute(
            text(
                "SELECT data_type, udt_name FROM information_schema.columns "
                "WHERE table_name = 'chunk_dialogues' AND column_name = 'speaker'"
            )
        )
        verify_row = verify_result.fetchone()
        logger.info(f"Verified speaker column type: {verify_row[0]} (udt_name={verify_row[1]})")


if __name__ == "__main__":
    migrate()
