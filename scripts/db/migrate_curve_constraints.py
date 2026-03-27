"""
数据库迁移脚本：修复 emotion_curve 和 rhythm_curve 表的唯一约束

创建时间: 2026-03-16
创建者: TraeAI
任务: 修复测试失败 - ON CONFLICT 需要唯一约束

问题：emotion_curve 和 rhythm_curve 表在数据库中缺少复合主键约束 (chunk_id, run_id)
导致 ON CONFLICT (chunk_id, run_id) 语句失败

解决方案：
1. 删除旧的主键（如果是单列主键）
2. 添加复合主键约束
"""

import os

from dotenv import load_dotenv
from sqlalchemy import create_engine, text

load_dotenv()


def get_database_url() -> str:
    """获取数据库URL"""
    url = os.getenv("DATABASE_URL") or os.getenv("TEST_DATABASE_URL")
    if not url:
        raise ValueError("DATABASE_URL 或 TEST_DATABASE_URL 环境变量未设置")
    return url


def migrate_emotion_curve(engine) -> None:
    """迁移 emotion_curve 表"""
    with engine.connect() as conn:
        # 检查当前约束
        result = conn.execute(
            text("""
                SELECT conname, contype 
                FROM pg_constraint 
                WHERE conrelid = 'emotion_curve'::regclass
            """)
        )
        constraints = list(result)
        print(f"当前 emotion_curve 约束: {constraints}")

        # 删除可能存在的旧主键
        for name, ctype in constraints:
            if ctype == "p":  # primary key
                print(f"删除旧主键: {name}")
                conn.execute(text(f"ALTER TABLE emotion_curve DROP CONSTRAINT {name}"))
                conn.commit()

        # 添加复合主键
        try:
            conn.execute(
                text("""
                    ALTER TABLE emotion_curve 
                    ADD CONSTRAINT emotion_curve_pkey 
                    PRIMARY KEY (chunk_id, run_id)
                """)
            )
            conn.commit()
            print("已添加复合主键 (chunk_id, run_id)")
        except Exception as e:
            if "already exists" in str(e) or "multiple primary keys" in str(e):
                print(f"复合主键已存在: {e}")
            else:
                raise


def migrate_rhythm_curve(engine) -> None:
    """迁移 rhythm_curve 表"""
    with engine.connect() as conn:
        # 检查当前约束
        result = conn.execute(
            text("""
                SELECT conname, contype 
                FROM pg_constraint 
                WHERE conrelid = 'rhythm_curve'::regclass
            """)
        )
        constraints = list(result)
        print(f"当前 rhythm_curve 约束: {constraints}")

        # 删除可能存在的旧主键
        for name, ctype in constraints:
            if ctype == "p":  # primary key
                print(f"删除旧主键: {name}")
                conn.execute(text(f"ALTER TABLE rhythm_curve DROP CONSTRAINT {name}"))
                conn.commit()

        # 添加复合主键
        try:
            conn.execute(
                text("""
                    ALTER TABLE rhythm_curve 
                    ADD CONSTRAINT rhythm_curve_pkey 
                    PRIMARY KEY (chunk_id, run_id)
                """)
            )
            conn.commit()
            print("已添加复合主键 (chunk_id, run_id)")
        except Exception as e:
            if "already exists" in str(e) or "multiple primary keys" in str(e):
                print(f"复合主键已存在: {e}")
            else:
                raise


def main() -> None:
    """主函数"""
    # 迁移主数据库
    db_url = os.getenv("DATABASE_URL")
    if db_url:
        print("\n=== 迁移主数据库 ===")
        print(f"连接数据库: {db_url.split('@')[1] if '@' in db_url else db_url}")
        engine = create_engine(db_url)
        print("\n--- 迁移 emotion_curve 表 ---")
        migrate_emotion_curve(engine)
        print("\n--- 迁移 rhythm_curve 表 ---")
        migrate_rhythm_curve(engine)

    # 迁移测试数据库
    test_db_url = os.getenv("TEST_DATABASE_URL")
    if test_db_url:
        print("\n=== 迁移测试数据库 ===")
        print(f"连接数据库: {test_db_url.split('@')[1] if '@' in test_db_url else test_db_url}")
        engine = create_engine(test_db_url)
        print("\n--- 迁移 emotion_curve 表 ---")
        migrate_emotion_curve(engine)
        print("\n--- 迁移 rhythm_curve 表 ---")
        migrate_rhythm_curve(engine)

    print("\n迁移完成!")


if __name__ == "__main__":
    main()
