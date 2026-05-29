"""
数据库迁移脚本：为 chunk_dialogues 表添加 tone 列

说明: 添加 tone 列存储对话语气类型（强硬/温和/讽刺/恳求/命令/恐惧/惊慌）
"""

import sys
from pathlib import Path

from dotenv import load_dotenv
from sqlalchemy import create_engine, text

project_root = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(project_root))
load_dotenv(project_root / ".env")

from src.storage.database_url import resolve_database_url_from_env  # noqa: E402


def get_database_url() -> str:
    url = resolve_database_url_from_env("DATABASE_URL", required=False)
    if url is None:
        url = resolve_database_url_from_env("TEST_DATABASE_URL", required=False)
    if url is None:
        raise ValueError("DATABASE_URL 或 TEST_DATABASE_URL 环境变量未设置")
    return url


def migrate_chunk_dialogues(engine) -> None:
    with engine.connect() as conn:
        result = conn.execute(
            text("""
                SELECT column_name 
                FROM information_schema.columns 
                WHERE table_name = 'chunk_dialogues' AND column_name = 'tone'
            """)
        )
        if list(result):
            print("tone 列已存在，跳过迁移")
            return

        conn.execute(
            text("""
                ALTER TABLE chunk_dialogues 
                ADD COLUMN tone VARCHAR(50) NULL
            """)
        )
        conn.commit()
        print("已添加 tone 列到 chunk_dialogues 表")


def main() -> None:
    db_url = resolve_database_url_from_env("DATABASE_URL", required=False)
    if db_url:
        print("\n=== 迁移主数据库 ===")
        print(f"连接数据库: {db_url.split('@')[1] if '@' in db_url else db_url}")
        engine = create_engine(db_url)
        migrate_chunk_dialogues(engine)

    test_db_url = resolve_database_url_from_env("TEST_DATABASE_URL", required=False)
    if test_db_url:
        print("\n=== 迁移测试数据库 ===")
        print(f"连接数据库: {test_db_url.split('@')[1] if '@' in test_db_url else test_db_url}")
        engine = create_engine(test_db_url)
        migrate_chunk_dialogues(engine)

    print("\n迁移完成!")


if __name__ == "__main__":
    main()
