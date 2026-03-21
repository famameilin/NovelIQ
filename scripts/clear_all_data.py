"""
清除所有数据和日志脚本

创建时间: 2026-03-19
创建者: TraeAI
任务: 清理数据库和日志
说明: 清除PostgreSQL数据库中的所有表数据，并删除所有日志文件

警告: 这会删除所有数据，请谨慎使用！
"""

from __future__ import annotations

import os
import sys
import shutil
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


def clear_database() -> None:
    """清除数据库中的所有表数据"""
    engine = get_engine()

    # 按照外键依赖顺序删除数据（子表先删，父表后删）
    tables = [
        # 实体相关表
        "entity_relations",
        "entity_aliases",
        "entity_snapshots",
        "character_appearances",
        "entities",
        # chunk相关子表
        "chunk_relations",
        "chunk_characters",
        "chunk_dialogues",
        "chunk_topics",
        "chunk_style",
        "chunk_culture",
        "chunk_embeddings",
        "chunk_summaries",
        "chunk_annotation",
        "emotion_curve",
        "rhythm_curve",
        "character_appearances",
        "entity_registry",
        # 诊断和统计
        "cloud_analysis",
        "global_stats",
        "global_context",
        "graph_storage",
        "token_usage",
        "disambig_checkpoint",
        "model_interactions",
        # chunk主表
        "chunks",
        # 运行记录（最后删除）
        "analysis_runs",
    ]

    with engine.connect() as conn:
        with conn.begin():
            for table in tables:
                try:
                    result = conn.execute(text(f"DELETE FROM {table}"))
                    logger.info(f"Cleared table: {table}")
                except Exception as e:
                    logger.warning(f"Failed to clear table {table}: {e}")

    logger.info("Database cleared successfully")


def clear_logs() -> None:
    """清除所有日志文件"""
    log_dirs = [
        project_root / "logs",
        project_root / "log",
    ]

    for log_dir in log_dirs:
        if log_dir.exists():
            try:
                # 删除目录下的所有内容，但保留目录本身
                for item in log_dir.iterdir():
                    if item.is_file():
                        item.unlink()
                        logger.info(f"Deleted log file: {item}")
                    elif item.is_dir():
                        shutil.rmtree(item)
                        logger.info(f"Deleted log directory: {item}")
                logger.info(f"Cleared log directory: {log_dir}")
            except Exception as e:
                logger.warning(f"Failed to clear log directory {log_dir}: {e}")
        else:
            logger.info(f"Log directory does not exist: {log_dir}")

    logger.info("Logs cleared successfully")


def clear_outputs() -> None:
    """清除结果输出文件"""
    outputs_dir = project_root / "outputs"

    if outputs_dir.exists():
        try:
            for item in outputs_dir.iterdir():
                if item.is_file():
                    item.unlink()
                    logger.info(f"Deleted output file: {item}")
                elif item.is_dir():
                    shutil.rmtree(item)
                    logger.info(f"Deleted output directory: {item}")
            logger.info(f"Cleared outputs directory: {outputs_dir}")
        except Exception as e:
            logger.warning(f"Failed to clear outputs directory {outputs_dir}: {e}")
    else:
        logger.info(f"Outputs directory does not exist: {outputs_dir}")


def main():
    """主函数"""
    database_url = os.getenv("DATABASE_URL")
    print(f"Database URL: {database_url}")
    print("\n" + "="*60)
    print("警告: 这将删除以下内容:")
    print("  1. 数据库中的所有数据")
    print("  2. 所有日志文件")
    print("  3. 所有结果输出文件")
    print("="*60 + "\n")

    confirm = input("确定要删除所有数据吗？输入 'yes' 确认: ")

    if confirm.lower() == "yes":
        print("\n开始清理数据库...")
        clear_database()

        print("\n开始清理日志...")
        clear_logs()

        print("\n开始清理结果文件...")
        clear_outputs()

        print("\n" + "="*60)
        print("✅ 所有数据和日志已清除")
        print("="*60)
    else:
        print("\n操作已取消")


if __name__ == "__main__":
    main()
