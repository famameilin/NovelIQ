"""
创建时间: 2026-03-16
创建者: TraeAI
任务: 配置测试数据库
说明: 创建测试数据库并安装 pgvector 扩展
"""
import os
import sys
from pathlib import Path

from dotenv import load_dotenv
from sqlalchemy import create_engine, text

project_root = Path(__file__).resolve().parents[2]
load_dotenv(project_root / ".env")

TEST_DB_URL = os.environ.get(
    "TEST_DATABASE_URL",
    "postgresql+psycopg://postgres:sr20031109ZY@localhost:5432/novel_analysis_test"
)

# 连接到默认的 postgres 数据库来创建测试数据库
DEFAULT_DB_URL = TEST_DB_URL.replace("/novel_analysis_test", "/postgres")


def create_test_database():
    """创建测试数据库"""
    engine = create_engine(DEFAULT_DB_URL, echo=False)

    with engine.connect() as conn:
        conn.execution_options(isolation_level="AUTOCOMMIT")

        # 检查数据库是否已存在
        result = conn.execute(
            text("SELECT 1 FROM pg_database WHERE datname = 'novel_analysis_test'")
        )
        exists = result.fetchone()

        if exists:
            print("[OK] 数据库 novel_analysis_test 已存在")
        else:
            conn.execute(text("CREATE DATABASE novel_analysis_test"))
            print("[OK] 数据库 novel_analysis_test 创建成功")

    engine.dispose()


def setup_pgvector():
    """安装 pgvector 扩展"""
    engine = create_engine(TEST_DB_URL, echo=False)

    with engine.connect() as conn:
        conn.execution_options(isolation_level="AUTOCOMMIT")
        conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        print("[OK] pgvector 扩展安装成功")

    engine.dispose()


def create_tables():
    """
    创建所有表

    修改时间: 2026-04-19
    修改者: Codex (GPT-5)
    任务: fix-test-db-schema-bootstrap
    修改内容: 复用 src.storage.db.init_db(include_level3_tables=True) 统一测试库建表入口，避免脚本和应用 schema 漂移。

    修改时间: 2026-04-27
    修改者: Codex
    任务: timeline-contract-migration-call-chain-cleanup
    修改内容: 不再在测试库初始化流程中主动调用 graph projection migration 脚本。
              时间轴合同相关 schema 迁移改为显式手动入口，避免测试库建表继续挂在迁移脚本活调用链上。
    """
    sys.path.insert(0, str(project_root))
    from src.storage import db as db_module

    os.environ["DATABASE_URL"] = TEST_DB_URL
    db_module.dispose_engine()
    db_module.init_db(include_level3_tables=True)
    db_module.dispose_engine()
    print("[OK] 测试库表结构已补全")


def main():
    print("=" * 50)
    print("配置测试数据库")
    print("=" * 50)

    try:
        create_test_database()
        setup_pgvector()
        create_tables()
        print("=" * 50)
        print("[OK] 测试数据库配置完成！")
        print("=" * 50)
        return 0
    except Exception as e:
        print(f"[ERROR] 错误: {e}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
