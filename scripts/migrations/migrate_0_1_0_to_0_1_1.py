"""0.1.0 → 0.1.1 一次性数据库升级检查与登记

本版本未修改 ORM 业务表结构。脚本核对目标库和存量数据合同；--apply 仅在
noveliq_release_migrations 中登记升级报告，不改写原文、正式标注或分析结果。
历史数组主题标签无法可靠绑定 topic_id，旧事件也没有可推断的段落证据。
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

VERSION = "0.1.1"
REQUIRED_COLUMNS = {
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
COUNT_TABLES = ("analysis_runs", "chapter_annotations", "event_nodes", "event_edges", "paragraphs", "cloud_analysis")
LEDGER_TABLE = "noveliq_release_migrations"


def _schema_errors(connection: Connection, schema: str) -> list[str]:
    """只检查本次升级所依赖的 0.1.0 业务结构，不自动建缺失业务表"""
    inspector = inspect(connection)
    tables = set(inspector.get_table_names(schema=schema))
    errors: list[str] = []
    for table, required in REQUIRED_COLUMNS.items():
        if table not in tables:
            errors.append(f"缺少表 {table}")
            continue
        columns = {column["name"] for column in inspector.get_columns(table, schema=schema)}
        for column in sorted(required - columns):
            errors.append(f"缺少列 {table}.{column}")
    if LEDGER_TABLE in tables:
        columns = {column["name"] for column in inspector.get_columns(LEDGER_TABLE, schema=schema)}
        for column in sorted({"version", "applied_at", "report"} - columns):
            errors.append(f"升级登记表缺少列 {LEDGER_TABLE}.{column}")
    return errors


def _topic_label_state(raw: str | None) -> str:
    """旧数组只能保留和提示重新诊断，不按数组位置猜测 topic_id"""
    if raw is None:
        return "missing"
    try:
        parsed = json.loads(raw)
    except (TypeError, ValueError):
        return "invalid"
    if isinstance(parsed, list):
        return "legacy_array"
    if isinstance(parsed, dict) and all(
        isinstance(key, str) and key.isascii() and key.isdecimal() and isinstance(value, str) and value.strip()
        for key, value in parsed.items()
    ):
        return "keyed"
    return "invalid"


def _audit_data(connection: Connection) -> dict[str, Any]:
    """按字段身份核对存量数据；报告只输出 ID 和计数，避免泄露小说正文"""
    counts = {
        table: connection.execute(text(f"SELECT count(*) FROM {table}")).scalar_one() for table in COUNT_TABLES
    }
    active_runs = list(
        connection.execute(
            text("SELECT run_id FROM analysis_runs WHERE status IN ('running', 'cancelling') ORDER BY run_id")
        )
        .scalars()
    )
    annotation_rows = connection.execute(
        text("SELECT annotation_id, run_id, payload FROM chapter_annotations")
    ).mappings()
    events_by_annotation: dict[str, dict[str, dict[str, Any]]] = {}
    incomplete_annotation_runs: set[str] = set()
    for row in annotation_rows:
        payload = row["payload"]
        if not isinstance(payload, dict) or not isinstance(payload.get("metrics"), dict):
            incomplete_annotation_runs.add(row["run_id"])
        events = payload.get("events") if isinstance(payload, dict) else None
        events_by_annotation[row["annotation_id"]] = {
            str(event["node_id"]): event
            for event in events or []
            if isinstance(event, dict) and event.get("node_id")
        } if isinstance(events, list) else {}

    old_evidence_count = 0
    unlinked_event_count = 0
    bad_anchor_ids: list[str] = []
    for row in connection.execute(
        text("SELECT event_id, annotation_id, anchor_paragraph_ids FROM event_nodes")
    ).mappings():
        event = events_by_annotation.get(row["annotation_id"], {}).get(row["event_id"])
        if event is None:
            unlinked_event_count += 1
            continue
        paragraph_id = event.get("evidence_paragraph_id")
        if paragraph_id is None:
            old_evidence_count += 1
        elif row["anchor_paragraph_ids"] != [paragraph_id]:
            bad_anchor_ids.append(row["event_id"])

    legacy_diagnosis_runs: set[str] = set()
    invalid_diagnosis_runs: set[str] = set()
    label_states: dict[str, int] = {"missing": 0, "legacy_array": 0, "keyed": 0, "invalid": 0}
    for row in connection.execute(text("SELECT run_id, topic_labels FROM cloud_analysis")).mappings():
        state = _topic_label_state(row["topic_labels"])
        label_states[state] += 1
        if state == "legacy_array" and row["run_id"]:
            legacy_diagnosis_runs.add(row["run_id"])
        if state == "invalid" and row["run_id"]:
            invalid_diagnosis_runs.add(row["run_id"])

    # 旧数组与章级锚点是历史精度边界；结构缺失或矛盾才阻断登记
    blocking_issues = []
    if incomplete_annotation_runs:
        blocking_issues.append("正式标注缺少 metrics 合同，需先重新分析相关任务")
    if bad_anchor_ids:
        blocking_issues.append("事件段落锚点与正式标注不一致")
    return {
        "counts": counts,
        "active_run_ids": active_runs,
        "incomplete_annotation_run_ids": sorted(incomplete_annotation_runs),
        "legacy_topic_label_run_ids": sorted(legacy_diagnosis_runs),
        "invalid_topic_label_run_ids": sorted(invalid_diagnosis_runs),
        "topic_label_states": label_states,
        "chapter_evidence_event_count": old_evidence_count,
        "event_without_annotation_payload_count": unlinked_event_count,
        "mismatched_paragraph_anchor_event_ids": sorted(bad_anchor_ids)[:50],
        "mismatched_paragraph_anchor_event_count": len(bad_anchor_ids),
        "blocking_issues": blocking_issues,
        "follow_up": [
            "旧数组主题标签保留原值；如需逐主题标签，请对列出的任务重新运行诊断",
            "旧事件保留章节级证据；如需段落级定位，请重新分析原文",
        ],
    }


def _ledger_applied(connection: Connection, schema: str) -> bool:
    if LEDGER_TABLE not in inspect(connection).get_table_names(schema=schema):
        return False
    return bool(
        connection.execute(
            text(f"SELECT 1 FROM {LEDGER_TABLE} WHERE version = :version"), {"version": VERSION}
        ).scalar_one_or_none()
    )


def migrate(
    *, database_env: DatabaseEnvironmentName, schema: str, apply: bool, expect_database: str | None
) -> dict[str, Any]:
    """dry-run 只读；apply 在一笔事务中登记结果，重复执行保持幂等"""
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
            errors = _schema_errors(connection, schema)
            if errors:
                return {"version": VERSION, "database": parsed_url.database, "schema": schema, "schema_errors": errors}
            report = {
                "version": VERSION,
                "database": parsed_url.database,
                "schema": schema,
                "schema_errors": [],
                **_audit_data(connection),
            }
            report["already_applied"] = _ledger_applied(connection, schema)
            if apply and not report["already_applied"]:
                if report["active_run_ids"]:
                    raise RuntimeError("仍有运行中的分析任务；请先停机并等待任务结束")
                if report["blocking_issues"]:
                    raise RuntimeError("存量数据存在阻断项；先按 dry-run 报告修复")
                connection.execute(text(f"""
                    CREATE TABLE IF NOT EXISTS {LEDGER_TABLE} (
                        version text PRIMARY KEY,
                        applied_at timestamptz NOT NULL DEFAULT now(),
                        report jsonb NOT NULL
                    )
                """))
                connection.execute(
                    text(f"INSERT INTO {LEDGER_TABLE} (version, report) VALUES (:version, CAST(:report AS jsonb))"),
                    {"version": VERSION, "report": json.dumps(report, ensure_ascii=False)},
                )
                after_counts = {
                    table: connection.execute(text(f"SELECT count(*) FROM {table}")).scalar_one()
                    for table in COUNT_TABLES
                }
                if after_counts != report["counts"]:
                    raise RuntimeError("业务表行数在升级事务中变化，已回滚登记")
                report["applied_now"] = True
            else:
                report["applied_now"] = False
            return report
    finally:
        engine.dispose()


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database-env", choices=("DATABASE", "TEST_DATABASE"), default="DATABASE")
    parser.add_argument("--schema", default=os.environ.get("DATABASE_SCHEMA", "public"))
    parser.add_argument("--apply", action="store_true", help="通过检查后登记 0.1.1；默认仅检查")
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
    return 0 if not report["schema_errors"] and not report["blocking_issues"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
