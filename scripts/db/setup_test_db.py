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


# 2026-04-28，任务：fix-setup-test-db-fallback-and-console-errors
# 新建原因：Windows 控制台在打印包含坏编码字符的数据库异常时会再次抛 UnicodeEncodeError，
# 这里统一做一次“按当前终端编码可打印”的降级处理，避免原始错误被二次覆盖。
def _safe_console_text(message: object) -> str:
    raw_text = str(message)
    encoding = getattr(sys.stdout, "encoding", None) or "utf-8"
    return raw_text.encode(encoding, errors="replace").decode(encoding, errors="replace")


# 2026-04-28，任务：fix-setup-test-db-fallback-and-console-errors
# 新建原因：脚本在数据库认证失败时必须稳定输出可读错误，
# 不能因为控制台编码问题再次中断整个 bootstrap 流程。
def _safe_print(message: object) -> None:
    print(_safe_console_text(message))


# 2026-04-28，任务：fix-setup-test-db-fallback-and-console-errors
# 新建原因：当前环境里连接维护库 `postgres` 可能失败，
# 但目标测试库本身仍然可连接；这里显式判断是否具备“原地重建表结构”的降级条件。
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
    """
    创建测试数据库

    修改时间: 2026-04-27
    修改者: Codex
    任务: fix-test-db-timeline-contract-bootstrap
    修改内容: 测试库若已存在则直接重建，而不是复用旧库。
              这次时间轴合同重构不再依赖运行时或手动迁移脚本兜底，
              因此测试库初始化必须显式确保得到全新的 schema。

    修改时间: 2026-04-28
    修改者: Codex
    任务: fix-setup-test-db-fallback-and-console-errors
    修改内容: 返回是否真的完成了整库重建；主流程可根据结果决定是否需要降级到“原地重建表结构”。
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

    修改时间: 2026-04-28
    修改者: Codex
    任务: fix-setup-test-db-fallback-and-console-errors
    修改内容: 当无法整库重建但目标测试库仍可连接时，允许显式 drop_all + init_db 原地重建表结构。
    """
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
