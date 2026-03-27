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
            print("✓ 数据库 novel_analysis_test 已存在")
        else:
            conn.execute(text("CREATE DATABASE novel_analysis_test"))
            print("✓ 数据库 novel_analysis_test 创建成功")

    engine.dispose()


def setup_pgvector():
    """安装 pgvector 扩展"""
    engine = create_engine(TEST_DB_URL, echo=False)

    with engine.connect() as conn:
        conn.execution_options(isolation_level="AUTOCOMMIT")
        conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        print("✓ pgvector 扩展安装成功")

    engine.dispose()


def create_tables():
    """创建所有表"""
    sys.path.insert(0, str(project_root))
    from src.storage.models import Base

    engine = create_engine(TEST_DB_URL, echo=False)
    Base.metadata.create_all(bind=engine)
    print("✓ 所有表创建成功")

    engine.dispose()


def main():
    print("=" * 50)
    print("配置测试数据库")
    print("=" * 50)

    try:
        create_test_database()
        setup_pgvector()
        create_tables()
        print("=" * 50)
        print("✓ 测试数据库配置完成！")
        print("=" * 50)
        return 0
    except Exception as e:
        print(f"✗ 错误: {e}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
