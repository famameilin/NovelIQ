"""0.1.1 → 0.2.0 一次性数据库升级脚本

0.2.0（队列删除定案 2026-10-05）相对 0.1.1 的 schema 变更：
1. 新增 13 张流水线表：work_items、semantic_commands、text_evidence、command_outcomes、
   continuity_cases、case_heads、case_claims、analysis_cutoffs、partition_heads、
   cutoff_partitions、source_manifests、formal_artifacts、event_outbox；
2. analysis_runs 新增 cancellation_epoch（NOT NULL）、annotation_cutoff_hash；
3. chapter_annotations 新增 formal_work_id（UNIQUE）、payload_hash、source_manifest_hash；
4. graph_entities 的 (run_id, canonical_name) 唯一约束放宽为普通索引
   idx_graph_entities_run_canonical；
5. 指向 work_items 的外键全部解除（work_id/author_work_id 只作回执溯源标识）。

队列时代残留随升级一并清除：DROP 已被 ORM 移除的 case_pool_cases /
case_resolution_mappings（连同其数据），并清空 work_items 旧队列行（0.2.0 代码对
WorkItem 零引用，行仅剩历史残留）。--apply 在一笔事务内幂等收敛到 0.2.0 结构，并在
noveliq_release_migrations 登记报告；不改写原文、正式标注或分析结果。
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path
from typing import Any, cast

from dotenv import load_dotenv
from sqlalchemy import Connection, create_engine, inspect, text
from sqlalchemy.engine import make_url

from src.config.runtime_env import DatabaseEnvironmentName
from src.storage.database_url import resolve_database_url_from_env

VERSION = "0.2.0"
LEDGER_TABLE = "noveliq_release_migrations"
GRAPH_TABLE = "graph_entities"
GRAPH_INDEX_NAME = "idx_graph_entities_run_canonical"
FORMAL_WORK_ID_UNIQUE_NAME = "chapter_annotations_formal_work_id_key"

# 0.1.1 基线合同（与 migrate_0_1_0_to_0_1_1 的 REQUIRED_COLUMNS 一致），升级前后都必须满足
BASE_REQUIRED_COLUMNS = {
    "analysis_runs": {"run_id", "status"},
    "chapter_annotations": {"annotation_id", "run_id", "chapter_id", "payload"},
    "chapters": {"chapter_id", "run_id", "text"},
    "cloud_analysis": {"id", "run_id", "topic_labels"},
    "event_edges": {"edge_id", "run_id"},
    "event_nodes": {"event_id", "run_id", "annotation_id", "tree_id", "anchor_paragraph_ids"},
    "paragraphs": {"run_id", "paragraph_id", "chapter_id"},
    "paragraph_topics": {"run_id", "paragraph_id", "topic_id"},
    "topic_model_runs": {"run_id", "num_topics"},
}

# 0.2.0 新增列：DDL 与 ORM 定义一一对应；cancellation_epoch 借 DEFAULT 0 回填存量行，
# 建成后立即 DROP DEFAULT，终态与 create_all 产出的结构完全一致（ORM 无 server_default）
NEW_COLUMNS: dict[str, dict[str, str]] = {
    "analysis_runs": {
        "cancellation_epoch": "INTEGER DEFAULT 0 NOT NULL",
        "annotation_cutoff_hash": "VARCHAR(64)",
    },
    "chapter_annotations": {
        "formal_work_id": "VARCHAR(64)",
        "payload_hash": "VARCHAR(64)",
        "source_manifest_hash": "VARCHAR(64)",
    },
}
NEW_TABLES = (
    "analysis_cutoffs",
    "case_claims",
    "case_heads",
    "command_outcomes",
    "continuity_cases",
    "cutoff_partitions",
    "event_outbox",
    "formal_artifacts",
    "partition_heads",
    "semantic_commands",
    "source_manifests",
    "text_evidence",
    "work_items",
)
COUNT_TABLES = ("analysis_runs", "chapter_annotations", "event_nodes", "event_edges", "paragraphs", "cloud_analysis")
# 已被 0.2.0 ORM 移除的遗留表，随升级 DROP（连数据）；case_resolution_mappings 是子表，放前面
PURGED_TABLES = ("case_resolution_mappings", "case_pool_cases")


def _pipeline_tables() -> list[Any]:
    """2026-10-05 用于从当前 ORM 取 13 张流水线表的 Table 对象（保持 sorted_tables 拓扑序），
    避免在脚本里手写 CREATE TABLE 与 ORM 漂移"""
    from src.storage.models import Base

    wanted = set(NEW_TABLES)
    known = {table.name for table in Base.metadata.sorted_tables}
    missing_definitions = sorted(wanted - known)
    if missing_definitions:
        raise RuntimeError(f"当前 ORM 缺少流水线表定义: {missing_definitions}")
    return [table for table in Base.metadata.sorted_tables if table.name in wanted]


def _graph_unique_constraint_name(inspector: Any) -> str | None:
    """2026-10-05 用于找到 graph_entities 上恰好覆盖 (run_id, canonical_name) 的唯一约束"""
    for constraint in inspector.get_unique_constraints(GRAPH_TABLE):
        if set(constraint["column_names"]) == {"run_id", "canonical_name"}:
            return str(constraint["name"])
    return None


def _formal_work_id_unique_missing(inspector: Any) -> bool:
    """2026-10-05 用于判定 chapter_annotations.formal_work_id 是否已有单列 UNIQUE 约束"""
    return not any(
        set(constraint["column_names"]) == {"formal_work_id"}
        for constraint in inspector.get_unique_constraints("chapter_annotations")
    )


def _foreign_keys_into_work_items(connection: Connection) -> list[tuple[str, str]]:
    """2026-10-05 用于枚举指向 work_items 的全部外键（子表, 约束名）；0.2.0 合同要求为零"""
    rows = connection.execute(
        text(
            """
            SELECT conrelid::regclass::text AS child_table, conname
            FROM pg_constraint
            WHERE contype = 'f' AND confrelid = to_regclass('work_items')
            ORDER BY 1, 2
            """
        )
    ).mappings()
    return [(str(row["child_table"]), str(row["conname"])) for row in rows]


def _collect_state(connection: Connection, schema: str) -> dict[str, Any]:
    """2026-10-05 用于读取目标库的 0.1.1 基线合同与 0.2.0 差量状态"""
    inspector = inspect(connection)
    tables = set(inspector.get_table_names(schema=schema))
    state: dict[str, Any] = {"tables": tables}

    base_schema_errors: list[str] = []
    for table, required in BASE_REQUIRED_COLUMNS.items():
        if table not in tables:
            base_schema_errors.append(f"缺少表 {table}")
            continue
        columns = {column["name"] for column in inspector.get_columns(table, schema=schema)}
        for column in sorted(required - columns):
            base_schema_errors.append(f"缺少列 {table}.{column}")
    if LEDGER_TABLE in tables:
        columns = {column["name"] for column in inspector.get_columns(LEDGER_TABLE, schema=schema)}
        for column in sorted({"version", "applied_at", "report"} - columns):
            base_schema_errors.append(f"升级登记表缺少列 {LEDGER_TABLE}.{column}")
    state["base_schema_errors"] = base_schema_errors

    state["missing_tables"] = sorted(set(NEW_TABLES) - tables)
    missing_columns: dict[str, list[str]] = {}
    for table, columns_ddl in NEW_COLUMNS.items():
        if table not in tables:
            continue  # 基线合同错误已覆盖该情形
        existing = {column["name"] for column in inspector.get_columns(table, schema=schema)}
        missing = [name for name in columns_ddl if name not in existing]
        if missing:
            missing_columns[table] = missing
    state["missing_columns"] = missing_columns
    state["formal_work_id_unique_missing"] = (
        "chapter_annotations" in tables and _formal_work_id_unique_missing(inspector)
    )
    state["graph_unique_constraint"] = _graph_unique_constraint_name(inspector) if GRAPH_TABLE in tables else None
    state["graph_index_missing"] = (
        GRAPH_TABLE in tables
        and GRAPH_INDEX_NAME not in {index["name"] for index in inspector.get_indexes(GRAPH_TABLE)}
    )
    state["work_items_foreign_keys"] = _foreign_keys_into_work_items(connection) if "work_items" in tables else []
    state["purged_tables_present"] = [name for name in PURGED_TABLES if name in tables]
    state["work_items_residual_rows"] = (
        connection.execute(text("SELECT count(*) FROM work_items")).scalar_one() if "work_items" in tables else None
    )
    return state


def _pending_changes(state: dict[str, Any]) -> list[str]:
    """2026-10-05 用于把差量状态渲染成可读的变更计划"""
    changes: list[str] = []
    if state["missing_tables"]:
        changes.append(f"建表 {len(state['missing_tables'])} 张: {', '.join(state['missing_tables'])}")
    for table, columns in state["missing_columns"].items():
        changes.append(f"{table} 加列: {', '.join(columns)}")
    if state["formal_work_id_unique_missing"]:
        changes.append(f"chapter_annotations 补 UNIQUE 约束 {FORMAL_WORK_ID_UNIQUE_NAME} (formal_work_id)")
    if state["graph_unique_constraint"]:
        changes.append(f"删除 {GRAPH_TABLE} 唯一约束 {state['graph_unique_constraint']}")
    if state["graph_index_missing"]:
        changes.append(f"建索引 {GRAPH_INDEX_NAME} ON {GRAPH_TABLE} (run_id, canonical_name)")
    for child_table, constraint_name in state["work_items_foreign_keys"]:
        changes.append(f"解除 {child_table} → work_items 外键 {constraint_name}")
    if state["purged_tables_present"]:
        changes.append(f"删除遗留表（连数据）: {', '.join(state['purged_tables_present'])}")
    if state["work_items_residual_rows"]:
        changes.append(f"清空 work_items 队列残留 {state['work_items_residual_rows']} 行")
    return changes


def _apply_changes(connection: Connection, state: dict[str, Any]) -> list[str]:
    """2026-10-05 用于在同一事务内幂等执行 0.2.0 差量 DDL，返回实际执行的变更"""
    applied: list[str] = []
    if state["missing_tables"]:
        from src.storage.models import Base

        Base.metadata.create_all(bind=connection, tables=_pipeline_tables())
        applied.append(f"建表 {len(state['missing_tables'])} 张: {', '.join(state['missing_tables'])}")
    for table, columns in state["missing_columns"].items():
        for column in columns:
            connection.execute(
                text(f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS {column} {NEW_COLUMNS[table][column]}")
            )
            if column == "cancellation_epoch":
                connection.execute(text(f"ALTER TABLE {table} ALTER COLUMN {column} DROP DEFAULT"))
        applied.append(f"{table} 加列: {', '.join(columns)}")
    if state["formal_work_id_unique_missing"]:
        connection.execute(
            text(f"ALTER TABLE chapter_annotations ADD CONSTRAINT {FORMAL_WORK_ID_UNIQUE_NAME} UNIQUE (formal_work_id)")
        )
        applied.append(f"chapter_annotations 补 UNIQUE 约束 {FORMAL_WORK_ID_UNIQUE_NAME} (formal_work_id)")
    if state["graph_unique_constraint"]:
        connection.execute(text(f"ALTER TABLE {GRAPH_TABLE} DROP CONSTRAINT {state['graph_unique_constraint']}"))
        applied.append(f"删除 {GRAPH_TABLE} 唯一约束 {state['graph_unique_constraint']}")
    if state["graph_index_missing"]:
        connection.execute(
            text(f"CREATE INDEX IF NOT EXISTS {GRAPH_INDEX_NAME} ON {GRAPH_TABLE} (run_id, canonical_name)")
        )
        applied.append(f"建索引 {GRAPH_INDEX_NAME} ON {GRAPH_TABLE} (run_id, canonical_name)")
    for child_table, constraint_name in state["work_items_foreign_keys"]:
        connection.execute(text(f"ALTER TABLE {child_table} DROP CONSTRAINT {constraint_name}"))
        applied.append(f"解除 {child_table} → work_items 外键 {constraint_name}")
    if state["purged_tables_present"]:
        connection.execute(text(f"DROP TABLE IF EXISTS {', '.join(PURGED_TABLES)}"))
        applied.append(f"删除遗留表（连数据）: {', '.join(state['purged_tables_present'])}")
    purged_rows = connection.execute(text("DELETE FROM work_items")).rowcount
    if purged_rows:
        applied.append(f"清空 work_items 队列残留 {purged_rows} 行")
    return applied


def _ledger_applied(connection: Connection, schema: str) -> bool:
    """2026-10-05 用于检查目标版本是否已登记升级台账"""
    if LEDGER_TABLE not in inspect(connection).get_table_names(schema=schema):
        return False
    return bool(
        connection.execute(
            text(f"SELECT 1 FROM {LEDGER_TABLE} WHERE version = :version"), {"version": VERSION}
        ).scalar_one_or_none()
    )


def _count_rows(connection: Connection, tables: tuple[str, ...]) -> dict[str, int]:
    return {table: connection.execute(text(f"SELECT count(*) FROM {table}")).scalar_one() for table in tables}


def migrate(
    *, database_env: DatabaseEnvironmentName, schema: str, apply: bool, expect_database: str | None
) -> dict[str, Any]:
    """2026-10-05 用于执行 0.1.1 → 0.2.0 升级；dry-run 只读，apply 幂等收敛并在台账登记"""
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", schema):
        raise ValueError("schema 名称仅允许字母、数字和下划线")
    if apply and not expect_database:
        raise ValueError("--apply 必须同时指定 --expect-database")
    url = resolve_database_url_from_env(database_env)
    parsed_url = make_url(url)
    if parsed_url.get_backend_name() != "postgresql" or not parsed_url.database:
        raise ValueError("迁移脚本只支持已存在的 PostgreSQL 数据库")
    if expect_database and parsed_url.database != expect_database:
        raise ValueError("目标数据库名称与 --expect-database 不一致")
    engine = create_engine(url, connect_args={"connect_timeout": 5})
    try:
        with engine.begin() as connection:
            if not apply:
                connection.execute(text("SET TRANSACTION READ ONLY"))
            connection.execute(text(f'SET LOCAL search_path TO "{schema}"'))
            if connection.execute(text("SELECT current_schema()")).scalar_one_or_none() != schema:
                raise ValueError(f"目标 schema 不存在: {schema}")
            if apply and not connection.execute(
                text("SELECT pg_try_advisory_xact_lock(hashtext(:key))"),
                {"key": f"noveliq:{parsed_url.database}:{schema}:{VERSION}"},
            ).scalar_one():
                raise RuntimeError("另一个升级进程正在执行")
            state = _collect_state(connection, schema)
            if state["base_schema_errors"]:
                return {
                    "version": VERSION,
                    "database": parsed_url.database,
                    "schema": schema,
                    "schema_errors": state["base_schema_errors"],
                    "blocking_issues": ["目标库不满足 0.1.1 基线合同，拒绝升级"],
                }
            report: dict[str, Any] = {
                "version": VERSION,
                "database": parsed_url.database,
                "schema": schema,
                "schema_errors": [],
                "changes_pending": _pending_changes(state),
                "legacy_purge": {
                    "tables_to_drop": state["purged_tables_present"],
                    "work_items_residual_rows": state["work_items_residual_rows"],
                },
                "active_run_ids": list(
                    connection.execute(
                        text("SELECT run_id FROM analysis_runs WHERE status IN ('running', 'cancelling') ORDER BY run_id")
                    ).scalars()
                ),
            }
            report["already_applied"] = _ledger_applied(connection, schema)
            report["applied_now"] = False
            report["changes_applied"] = []
            if apply and report["changes_pending"]:
                if report["active_run_ids"]:
                    raise RuntimeError("仍有运行中的分析任务；请先停机并等待任务结束")
                counts_before = _count_rows(connection, COUNT_TABLES)
                report["changes_applied"] = _apply_changes(connection, state)
                remaining = _pending_changes(_collect_state(connection, schema))
                if remaining:
                    raise RuntimeError(f"DDL 执行后仍未收敛到 0.2.0 结构: {remaining}")
                if _count_rows(connection, COUNT_TABLES) != counts_before:
                    raise RuntimeError("业务表行数在升级事务中变化，已回滚全部变更")
                report["applied_now"] = True
            if "work_items" in state["tables"] or apply:
                report["work_items_rows"] = connection.execute(text("SELECT count(*) FROM work_items")).scalar_one()
            if LEDGER_TABLE in state["tables"]:
                report["ledger_versions"] = list(
                    connection.execute(text(f"SELECT version FROM {LEDGER_TABLE} ORDER BY version")).scalars()
                )
            if apply and not report["already_applied"]:
                connection.execute(
                    text(f"""
                        CREATE TABLE IF NOT EXISTS {LEDGER_TABLE} (
                            version text PRIMARY KEY,
                            applied_at timestamptz NOT NULL DEFAULT now(),
                            report jsonb NOT NULL
                        )
                    """)
                )
                connection.execute(
                    text(f"INSERT INTO {LEDGER_TABLE} (version, report) VALUES (:version, CAST(:report AS jsonb))"),
                    {"version": VERSION, "report": json.dumps(report, ensure_ascii=False)},
                )
                report.setdefault("ledger_versions", []).append(VERSION)
            report["follow_up"] = [
                "本脚本已把库完整升到 0.2.0，无需整库 rebuild",
                "队列时代残留已随升级清除：遗留表已 DROP（连数据）、work_items 已清空；0.2.0 代码对这些表零引用",
                "完成后重启 API（init_db 只补建缺失表，不重复本脚本的列/约束变更）",
            ]
            return report
    finally:
        engine.dispose()


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database-env", choices=("DATABASE", "TEST_DATABASE"), default="DATABASE")
    parser.add_argument("--schema", default=os.environ.get("DATABASE_SCHEMA", "public"))
    parser.add_argument("--apply", action="store_true", help="幂等收敛到 0.2.0 结构并登记台账；默认仅检查")
    parser.add_argument("--expect-database", help="apply 时必须填写目标数据库名")
    args = parser.parse_args()
    load_dotenv(Path(__file__).resolve().parents[2] / ".env")
    try:
        report = migrate(
            database_env=cast(DatabaseEnvironmentName, args.database_env),
            schema=args.schema,
            apply=args.apply,
            expect_database=args.expect_database,
        )
    except (RuntimeError, ValueError) as exc:
        print(json.dumps({"version": VERSION, "error": str(exc)}, ensure_ascii=False, indent=2))
        return 2
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if not report["schema_errors"] and not report.get("blocking_issues") else 2


if __name__ == "__main__":
    raise SystemExit(main())
