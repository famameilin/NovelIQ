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
from sqlalchemy.engine import make_url

project_root = Path(__file__).resolve().parents[2]
load_dotenv(project_root / ".env")

TEST_DB_URL = os.environ.get(
    "TEST_DATABASE_URL",
    "postgresql+psycopg://postgres:sr20031109ZY@localhost:5432/novel_analysis_test"
)
TEST_DB_NAME = make_url(TEST_DB_URL).database
if not TEST_DB_NAME:
    raise RuntimeError("TEST_DATABASE_URL 必须包含数据库名")
if TEST_DB_NAME in {"postgres", "template0", "template1"}:
    raise RuntimeError(f"拒绝使用保留数据库名作为测试库: {TEST_DB_NAME}")
QUOTED_TEST_DB_NAME = f'"{TEST_DB_NAME.replace("\"", "\"\"")}"'

# 连接到默认的 postgres 数据库来创建测试数据库
DEFAULT_DB_URL = str(make_url(TEST_DB_URL).set(database="postgres"))


def create_test_database():
    """
    创建测试数据库

    修改时间: 2026-04-27
    修改者: Codex
    任务: fix-test-db-timeline-contract-bootstrap
    修改内容: 测试库若已存在则直接重建，而不是复用旧库。
              这次时间轴合同重构不再依赖运行时或手动迁移脚本兜底，
              因此测试库初始化必须显式确保得到全新的 schema。
    """
    engine = create_engine(DEFAULT_DB_URL, echo=False)

    with engine.connect() as conn:
        conn.execution_options(isolation_level="AUTOCOMMIT")

        # 检查数据库是否已存在
        result = conn.execute(
            text("SELECT 1 FROM pg_database WHERE datname = :database_name"),
            {"database_name": TEST_DB_NAME},
        )
        exists = result.fetchone()

        if exists:
            conn.execute(
                text(
                    """
                    SELECT pg_terminate_backend(pid)
                    FROM pg_stat_activity
                    WHERE datname = :database_name
                      AND pid <> pg_backend_pid()
                    """
                ),
                {"database_name": TEST_DB_NAME},
            )
            conn.execute(text(f"DROP DATABASE {QUOTED_TEST_DB_NAME}"))
            conn.execute(text(f"CREATE DATABASE {QUOTED_TEST_DB_NAME}"))
            print(f"[OK] 数据库 {TEST_DB_NAME} 已重建")
        else:
            conn.execute(text(f"CREATE DATABASE {QUOTED_TEST_DB_NAME}"))
            print(f"[OK] 数据库 {TEST_DB_NAME} 创建成功")

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
              当前测试库通过“先重建数据库，再按 ORM 建表”拿到最新时间轴合同，
              不再依赖旧的一次性迁移脚本继续补旧 schema。
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
