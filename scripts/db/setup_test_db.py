"""
创建测试数据库并安装 pgvector 扩展。
"""
import os
import sys
from pathlib import Path

from dotenv import load_dotenv
from sqlalchemy import create_engine, text
from sqlalchemy.engine import URL, make_url
from sqlalchemy.exc import SQLAlchemyError

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
DEFAULT_DB_URL: URL = make_url(TEST_DB_URL).set(database="postgres")


# 按当前终端编码降级异常文本，避免打印数据库错误时再次触发 UnicodeEncodeError。
def _safe_console_text(message: object) -> str:
    raw_text = str(message)
    encoding = getattr(sys.stdout, "encoding", None) or "utf-8"
    return raw_text.encode(encoding, errors="replace").decode(encoding, errors="replace")


# 稳定输出可读错误，避免控制台编码问题中断 bootstrap 流程。
def _safe_print(message: object) -> None:
    print(_safe_console_text(message))


# 显式判断是否具备“原地重建表结构”的降级条件。
def _can_connect(database_url: str) -> tuple[bool, str | None]:
    engine = create_engine(database_url, echo=False)
    try:
        with engine.connect():
            return True, None
    except SQLAlchemyError as exc:
        return False, _safe_console_text(exc)
    finally:
        engine.dispose()


def create_test_database():
    """创建或重建测试数据库，并返回是否完成了整库重建。"""
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
            _safe_print(f"[OK] 数据库 {TEST_DB_NAME} 已重建")
        else:
            conn.execute(text(f"CREATE DATABASE {QUOTED_TEST_DB_NAME}"))
            _safe_print(f"[OK] 数据库 {TEST_DB_NAME} 创建成功")

    engine.dispose()
    return True


def setup_pgvector():
    """安装 pgvector 扩展"""
    engine = create_engine(TEST_DB_URL, echo=False)

    with engine.connect() as conn:
        conn.execution_options(isolation_level="AUTOCOMMIT")
        conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        _safe_print("[OK] pgvector 扩展安装成功")

    engine.dispose()


def create_tables(*, reset_existing_tables: bool = False):
    """按当前 ORM 建表；必要时先 drop_all 做原地表级重建。"""
    sys.path.insert(0, str(project_root))
    from src.storage import db as db_module
    from src.storage.models import Base

    os.environ["DATABASE_URL"] = TEST_DB_URL
    db_module.dispose_engine()
    if reset_existing_tables:
        engine = db_module.get_engine()
        Base.metadata.drop_all(bind=engine)
    db_module.init_db(include_level3_tables=True)
    db_module.dispose_engine()
    _safe_print("[OK] 测试库表结构已补全")


def main():
    _safe_print("=" * 50)
    _safe_print("配置测试数据库")
    _safe_print("=" * 50)

    try:
        database_recreated = create_test_database()
        setup_pgvector()
        create_tables(reset_existing_tables=not database_recreated)
        _safe_print("=" * 50)
        _safe_print("[OK] 测试数据库配置完成！")
        _safe_print("=" * 50)
        return 0
    except Exception as e:
        maintenance_db_error = _safe_console_text(e)
        can_connect_target_db, target_db_error = _can_connect(TEST_DB_URL)
        if can_connect_target_db:
            _safe_print(f"[WARN] 无法连接维护库 `{DEFAULT_DB_URL}`，将改为原地重建测试库表结构。")
            _safe_print(f"[WARN] 维护库错误: {maintenance_db_error}")
            try:
                setup_pgvector()
                create_tables(reset_existing_tables=True)
                _safe_print("=" * 50)
                _safe_print("[OK] 测试数据库已通过原地重建表结构完成配置")
                _safe_print("=" * 50)
                return 0
            except Exception as fallback_error:
                _safe_print(f"[ERROR] 维护库降级路径也失败: {fallback_error}")
                return 1

        _safe_print(f"[ERROR] 错误: {maintenance_db_error}")
        if target_db_error:
            _safe_print(f"[ERROR] 目标测试库连接同样失败: {target_db_error}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
