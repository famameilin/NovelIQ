"""
数据库迁移脚本：为 chunk_dialogues 表添加 tone 列

创建时间: 2026-03-25
创建者: TraeAI
任务: fix-tone-distribution-semantic-error
说明: 添加 tone 列存储对话语气类型（强硬/温和/讽刺/恳求/命令/恐惧/惊慌）
"""

import os

from dotenv import load_dotenv
from sqlalchemy import create_engine, text

load_dotenv()


def get_database_url() -> str:
    url = os.getenv("DATABASE_URL") or os.getenv("TEST_DATABASE_URL")
    if not url:
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
    db_url = os.getenv("DATABASE_URL")
    if db_url:
        print("\n=== 迁移主数据库 ===")
        print(f"连接数据库: {db_url.split('@')[1] if '@' in db_url else db_url}")
        engine = create_engine(db_url)
        migrate_chunk_dialogues(engine)

    test_db_url = os.getenv("TEST_DATABASE_URL")
    if test_db_url:
        print("\n=== 迁移测试数据库 ===")
        print(f"连接数据库: {test_db_url.split('@')[1] if '@' in test_db_url else test_db_url}")
        engine = create_engine(test_db_url)
        migrate_chunk_dialogues(engine)

    print("\n迁移完成!")


if __name__ == "__main__":
    main()
