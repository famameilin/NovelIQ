"""
恢复 model_interactions 表外键约束

创建时间: 2026-03-19
创建者: TraeAI
任务: 恢复外键约束
说明: 重新添加 model_interactions 表对 chunks 表的外键约束
"""

from __future__ import annotations

import sys
from pathlib import Path

# Add project root to Python path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from dotenv import load_dotenv
from loguru import logger
from sqlalchemy import text

# Load env from root
env_path = project_root / ".env"
load_dotenv(env_path)

from src.storage.db import get_engine


def restore_foreign_key() -> None:
    """恢复外键约束"""
    engine = get_engine()

    with engine.connect() as conn:
        with conn.begin():
            # 1. 检查外键约束是否已存在
            result = conn.execute(text("""
                SELECT conname
                FROM pg_constraint
                WHERE conname = 'model_interactions_chunk_id_run_id_fkey'
            """))
            constraint_exists = result.scalar_one_or_none()

            if constraint_exists:
                logger.info("外键约束已存在，无需恢复")
            else:
                # 2. 添加外键约束
                conn.execute(text("""
                    ALTER TABLE model_interactions
                    ADD CONSTRAINT model_interactions_chunk_id_run_id_fkey
                    FOREIGN KEY (chunk_id, run_id) REFERENCES chunks(chunk_id, run_id) ON DELETE CASCADE
                """))
                logger.info("已添加外键约束: model_interactions_chunk_id_run_id_fkey")

    logger.info("外键约束恢复完成")


def verify_restore() -> None:
    """验证恢复结果"""
    engine = get_engine()

    with engine.connect() as conn:
        # 检查外键约束
        result = conn.execute(text("""
            SELECT conname, pg_get_constraintdef(oid)
            FROM pg_constraint
            WHERE conrelid = 'model_interactions'::regclass
            AND contype = 'f'
        """))

        constraints = result.fetchall()
        logger.info("当前 model_interactions 表的外键约束:")
        for name, definition in constraints:
            logger.info(f"  - {name}: {definition}")

        if any('chunks' in str(definition) for _, definition in constraints):
            logger.info("✅ 验证通过: 已恢复对 chunks 表的外键约束")
        else:
            logger.warning("⚠️ 验证失败: 未找到对 chunks 表的外键约束")


def main():
    """主函数"""
    print("="*60)
    print("恢复 model_interactions 表外键约束")
    print("="*60)
    print()

    confirm = input("确定要恢复数据库外键约束吗？输入 'yes' 确认: ")

    if confirm.lower() == "yes":
        print("\n开始恢复...")
        restore_foreign_key()
        print("\n验证恢复结果...")
        verify_restore()
        print("\n" + "="*60)
        print("✅ 恢复完成")
        print("="*60)
    else:
        print("\n操作已取消")


if __name__ == "__main__":
    main()
