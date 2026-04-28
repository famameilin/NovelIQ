"""
创建时间: 2026-04-28
创建者: Codex
任务: remove-timeline-version-columns
说明: 一次性删除 analysis_runs 上的 graph/timeline 版本标签列。
      当前主线已不再依赖 run-level version gate；
      该脚本用于把已存在数据库直接收口到最新 schema，不做历史兼容。
"""

from __future__ import annotations

import argparse
import os
import re
import sys
from pathlib import Path

from dotenv import load_dotenv
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Connection, Engine

project_root = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(project_root))
load_dotenv(project_root / ".env")


# 2026-04-28，任务：remove-timeline-version-columns
# 新建原因：脚本既支持显式指定单个目标库，也支持默认尝试处理主库和测试库；
# 默认模式下若某个 URL 未配置应显式跳过，只有显式指定时才应报错。
def get_database_url_from_env(env_var_name: str, *, required: bool) -> str | None:
    database_url = os.environ.get(env_var_name)
    if not database_url:
        if required:
            raise RuntimeError(f"{env_var_name} environment variable is not set")
        return None
    return database_url


# 2026-04-28，任务：remove-timeline-version-columns
# 新建原因：脚本需要复用和应用主链一致的 schema 语义，
# 若配置了 DATABASE_SCHEMA，则 drop 列必须落在同一 search_path 下。
def get_database_schema_from_env() -> str | None:
    schema = os.environ.get("DATABASE_SCHEMA")
    if not schema:
        return None
    normalized = schema.strip()
    if not normalized:
        return None
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", normalized):
        raise RuntimeError(f"Invalid DATABASE_SCHEMA: {schema}")
    return normalized


# 2026-04-28，任务：remove-timeline-version-columns
# 新建原因：drop 列脚本需要在连接建立时固定 search_path，
# 避免 schema-isolated 环境下误删 public 或其他 schema 的同名表。
def build_engine(database_url: str, database_schema: str | None) -> Engine:
    connect_args: dict[str, str] = {}
    if database_schema:
        connect_args["options"] = f"-c search_path={database_schema},public"
    return create_engine(database_url, echo=False, connect_args=connect_args)


# 2026-04-28，任务：remove-timeline-version-columns
# 新建原因：执行 destructive DDL 前需要显式确认 analysis_runs 表存在，
# 避免把错误库或未初始化库也误判成“脚本执行成功”。
def has_analysis_runs_table(connection: Connection) -> bool:
    exists = connection.execute(
        text(
            """
            SELECT 1
            FROM information_schema.tables
            WHERE table_schema = current_schema()
              AND table_name = 'analysis_runs'
            LIMIT 1
            """
        )
    ).scalar_one_or_none()
    return bool(exists)


# 2026-04-28，任务：remove-timeline-version-columns
# 新建原因：删除后需要再次读取当前列集合做强校验，
# 不允许只执行 DROP COLUMN 而不确认 schema 已经真正收口。
def fetch_analysis_runs_columns(connection: Connection) -> list[str]:
    rows = connection.execute(
        text(
            """
            SELECT column_name
            FROM information_schema.columns
            WHERE table_schema = current_schema()
              AND table_name = 'analysis_runs'
            ORDER BY ordinal_position
            """
        )
    ).fetchall()
    return [str(row.column_name) for row in rows]


# 2026-04-28，任务：remove-timeline-version-columns
# 新建原因：把真正的 destructive DDL 集中到一个函数里，便于对 dev/test 库统一复用。
def drop_version_columns(database_url: str, database_schema: str | None, *, label: str) -> None:
    engine = build_engine(database_url, database_schema)
    try:
        with engine.begin() as connection:
            if database_schema:
                connection.execute(text(f"SET search_path TO {database_schema}, public"))
            if not has_analysis_runs_table(connection):
                print(f"[SKIP] {label}: current schema has no analysis_runs table, nothing to drop")
                return
            before_columns = fetch_analysis_runs_columns(connection)
            connection.execute(text("ALTER TABLE analysis_runs DROP COLUMN IF EXISTS graph_projection_version"))
            connection.execute(text("ALTER TABLE analysis_runs DROP COLUMN IF EXISTS timeline_contract_version"))
            after_columns = fetch_analysis_runs_columns(connection)

        print(f"[OK] {label}: analysis_runs columns before -> {before_columns}")
        print(f"[OK] {label}: analysis_runs columns after  -> {after_columns}")
    finally:
        engine.dispose()


def main() -> int:
    parser = argparse.ArgumentParser(description="Drop timeline version columns from analysis_runs")
    parser.add_argument(
        "--env-var",
        dest="env_vars",
        action="append",
        choices=["DATABASE_URL", "TEST_DATABASE_URL"],
        help="Database URL environment variable to migrate. Defaults to both DATABASE_URL and TEST_DATABASE_URL.",
    )
    args = parser.parse_args()

    database_schema = get_database_schema_from_env()
    env_vars = args.env_vars or ["DATABASE_URL", "TEST_DATABASE_URL"]
    processed_pairs: set[tuple[str, str | None]] = set()
    processed_any = False

    for env_var_name in env_vars:
        database_url = get_database_url_from_env(env_var_name, required=bool(args.env_vars))
        if database_url is None:
            print(f"[SKIP] {env_var_name}: environment variable is not set")
            continue
        dedupe_key = (database_url, database_schema)
        if dedupe_key in processed_pairs:
            print(f"[SKIP] {env_var_name}: same database/schema already processed")
            continue
        drop_version_columns(database_url, database_schema, label=env_var_name)
        processed_pairs.add(dedupe_key)
        processed_any = True

    if not processed_any:
        raise RuntimeError("No database URLs were available for timeline version column cleanup")

    print("[OK] timeline / graph projection version columns removed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
