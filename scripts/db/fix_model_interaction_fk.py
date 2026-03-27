"""
修复 model_interactions 表外键约束

创建时间: 2026-03-19
创建者: TraeAI
任务: 修复外键约束错误
说明: 移除 model_interactions 表对 chunks 表的外键约束，允许同步保存交互记录

修改内容:
- 删除 model_interactions_chunk_id_run_id_fkey 外键约束
- 保留 run_id 对 analysis_runs 的外键约束（因为 run_id 一定存在）
"""

from __future__ import annotations

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


def fix_foreign_key() -> None:
    """修复外键约束"""
    engine = get_engine()

    with engine.connect() as conn:
        with conn.begin():
            # 1. 检查外键约束是否存在
            result = conn.execute(text("""
                SELECT conname
                FROM pg_constraint
                WHERE conname = 'model_interactions_chunk_id_run_id_fkey'
            """))
            constraint_exists = result.scalar_one_or_none()

            if constraint_exists:
                # 2. 删除外键约束
                conn.execute(text("""
                    ALTER TABLE model_interactions
                    DROP CONSTRAINT model_interactions_chunk_id_run_id_fkey
                """))
                logger.info("已删除外键约束: model_interactions_chunk_id_run_id_fkey")
            else:
                logger.info("外键约束不存在，无需删除")

            # 3. 检查是否还有 analysis_runs 的外键约束
            result = conn.execute(text("""
                SELECT conname
                FROM pg_constraint
                WHERE conname = 'model_interactions_run_id_fkey'
            """))
            run_fk_exists = result.scalar_one_or_none()

            if run_fk_exists:
                logger.info("保留外键约束: model_interactions_run_id_fkey (关联 analysis_runs)")
            else:
                # 如果不存在，添加它
                conn.execute(text("""
                    ALTER TABLE model_interactions
                    ADD CONSTRAINT model_interactions_run_id_fkey
                    FOREIGN KEY (run_id) REFERENCES analysis_runs(run_id) ON DELETE CASCADE
                """))
                logger.info("已添加外键约束: model_interactions_run_id_fkey")

    logger.info("外键约束修复完成")


def verify_fix() -> None:
    """验证修复结果"""
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

        if not any('chunks' in str(definition) for _, definition in constraints):
            logger.info("✅ 验证通过: 已移除对 chunks 表的外键约束")
        else:
            logger.warning("⚠️ 验证失败: 仍然存在对 chunks 表的外键约束")


def main():
    """主函数"""
    print("="*60)
    print("修复 model_interactions 表外键约束")
    print("="*60)
    print()

    confirm = input("确定要修改数据库外键约束吗？输入 'yes' 确认: ")

    if confirm.lower() == "yes":
        print("\n开始修复...")
        fix_foreign_key()
        print("\n验证修复结果...")
        verify_fix()
        print("\n" + "="*60)
        print("✅ 修复完成")
        print("="*60)
    else:
        print("\n操作已取消")


if __name__ == "__main__":
    main()
