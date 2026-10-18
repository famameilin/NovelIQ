"""审计与产物六表合并迁移：默认只读检查，--apply 单事务执行

表合并映射：
- agent_invocations / agent_turns / audit_messages / token_usage → model_turns 一张回合级台账
  （invocation 上下文反规范化到回合行，token 计账列内联，audit_messages 幂等职责由
  message_key 唯一列承担；回合行保留原 agent_turns.id 以维持 agent_tool_calls.turn_id）；
- chapter_annotations / cloud_analysis → analysis_outputs（kind 区分，业务内容进 payload）；
- book_case_states（状态+交付贡献）并入 book_cases 同行保存。

agent_invocations 不迁移行：成功尝试的全部事实在回合行上，失败尝试补一行
attempt_error（turn_index=0）保存执行上下文与最终错误。
cloud_analysis 只迁移每个 run 的最新一行（历史读侧即取最新，旧行不可达）。

不自动执行生产迁移。所有变动在一个 PostgreSQL 事务内；回退按备份与原发布代码恢复。
"""

from __future__ import annotations

import argparse
import json
import os
import re
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from sqlalchemy import Connection, create_engine, inspect, text
from sqlalchemy.engine import make_url

SOURCE_TABLES = (
    "agent_invocations",
    "agent_turns",
    "agent_tool_calls",
    "token_usage",
    "audit_messages",
    "chapter_annotations",
    "cloud_analysis",
    "book_cases",
    "book_case_states",
    "analysis_runs",
    "graph_facts",
    "event_nodes",
    "event_edges",
)
TARGET_TABLES = ("model_turns", "analysis_outputs")
# 本工具只接受已完成角色 work 转换的中间结构，不能把原始 0.2.0 当成该结构
SOURCE_COLUMNS = {
    "analysis_runs": {"run_id", "status"},
    "agent_invocations": {
        "id",
        "execution_id",
        "work_id",
        "role",
        "model_name",
        "run_id",
        "task_type",
        "chapter_id",
        "attempt_number",
        "status",
        "final_error",
        "started_at",
        "finished_at",
    },
    "agent_turns": {
        "id",
        "invocation_id",
        "turn_index",
        "status",
        "error",
        "raw_response",
        "context_summary",
        "request_messages",
        "timing_notes",
        "ttft_ms",
        "first_visible_ms",
        "reasoning_ms",
        "model_ms",
        "tool_wall_ms",
        "turn_ms",
        "started_at",
        "finished_at",
    },
    "agent_tool_calls": {"id", "turn_id"},
    "token_usage": {
        "run_id",
        "agent_turn_id",
        "task_type",
        "call_type",
        "model",
        "chapter_id",
        "prompt_tokens",
        "completion_tokens",
        "total_tokens",
        "cache_read_tokens",
        "reasoning_tokens",
        "cost",
        "accounting_source",
        "created_at",
    },
    "chapter_annotations": {
        "annotation_id",
        "run_id",
        "chapter_id",
        "work_id",
        "invocation_id",
        "actual_input",
        "role",
        "payload",
        "created_at",
    },
    "cloud_analysis": {
        "id",
        "run_id",
        "novel_id",
        "foreshadow_expectation",
        "arc_scores",
        "genre_labels",
        "style_labels",
        "topic_labels",
        "diagnosis",
        "value_logic_type",
        "value_logic_reason",
        "power_stance_score",
        "power_stance_reason",
        "common_people_dignity",
        "dignity_reason",
        "cultural_depth_score",
        "cultural_depth_reason",
        "narrative_arc_type",
        "focus_structure",
        "focus_characters",
        "main_characters",
        "core_cast",
        "theme_color",
    },
    "book_cases": {"case_id"},
    "book_case_states": {"case_id", "state", "contributions"},
    "audit_messages": {"message_id", "execution_id", "method", "result_id"},
    "graph_facts": {"annotation_id"},
    "event_nodes": {"annotation_id"},
    "event_edges": {"annotation_id"},
}


def _identifier(value: str) -> str:
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", value):
        raise ValueError(f"非法 schema/table 标识: {value}")
    return f'"{value}"'


def migration_plan(connection: Connection) -> dict[str, Any]:
    schema = str(connection.execute(text("SELECT current_schema()")).scalar_one())
    inspector = inspect(connection)
    tables = set(inspector.get_table_names(schema=schema))
    sources = [name for name in SOURCE_TABLES if name in tables]
    targets = [name for name in TARGET_TABLES if name in tables]
    book_case_columns = (
        {item["name"] for item in inspector.get_columns("book_cases", schema=schema)}
        if "book_cases" in tables
        else set()
    )
    book_case_state_column = "state" in book_case_columns or "contributions" in book_case_columns
    already_migrated = set(TARGET_TABLES) <= tables and {"state", "contributions"} <= book_case_columns
    missing_columns = {
        table: sorted(required - {column["name"] for column in inspector.get_columns(table, schema=schema)})
        for table, required in SOURCE_COLUMNS.items()
        if table in tables
    }
    active = (
        list(
            connection.execute(
                text(
                    "SELECT run_id FROM analysis_runs "
                    "WHERE status IN ('running', 'cancelling', 'pending') ORDER BY run_id"
                )
            ).scalars()
        )
        if "analysis_runs" in tables and not {"run_id", "status"}.intersection(missing_columns["analysis_runs"])
        else []
    )
    return {
        "schema": schema,
        "source_tables": sources,
        "already_migrated": already_migrated,
        "partial_target": bool(targets or book_case_state_column) and not already_migrated,
        "missing_source_tables": sorted(set(SOURCE_TABLES) - tables),
        "missing_source_columns": {table: missing for table, missing in missing_columns.items() if missing},
        "active_run_ids": [str(run_id) for run_id in active],
        "book_cases_already_merged": book_case_state_column,
        "unmigrated_run_ids": [
            str(run_id)
            for run_id in connection.execute(
                text("SELECT DISTINCT run_id FROM agent_invocations ORDER BY run_id")
            ).scalars()
        ]
        if "agent_invocations" in tables and "run_id" not in missing_columns["agent_invocations"]
        else [],
    }


def _create_model_turns(connection: Connection) -> None:
    connection.execute(
        text(
            """
            CREATE TABLE model_turns (
                id SERIAL NOT NULL PRIMARY KEY,
                row_kind VARCHAR(20) NOT NULL DEFAULT 'agent_turn',
                run_id VARCHAR(36) NOT NULL REFERENCES analysis_runs (run_id) ON DELETE CASCADE,
                task_type VARCHAR(100) NOT NULL,
                call_type VARCHAR(50) NOT NULL,
                model VARCHAR(100) NOT NULL,
                execution_id VARCHAR(64),
                attempt_number INTEGER,
                chapter_id INTEGER,
                work_id VARCHAR(64),
                role VARCHAR(20),
                turn_index INTEGER,
                status VARCHAR(20) NOT NULL DEFAULT 'running',
                error TEXT,
                raw_response JSONB,
                context_summary JSONB,
                request_messages JSONB,
                timing_notes JSONB,
                ttft_ms INTEGER,
                first_visible_ms INTEGER,
                reasoning_ms INTEGER,
                model_ms INTEGER,
                tool_wall_ms INTEGER,
                turn_ms INTEGER,
                prompt_tokens INTEGER,
                completion_tokens INTEGER,
                total_tokens INTEGER,
                cache_read_tokens INTEGER,
                reasoning_tokens INTEGER,
                cost FLOAT,
                accounting_source VARCHAR(20) NOT NULL DEFAULT 'reported',
                message_key VARCHAR(128) UNIQUE,
                started_at TIMESTAMP NOT NULL,
                finished_at TIMESTAMP,
                CONSTRAINT ck_model_turns_row_kind CHECK (row_kind IN ('agent_turn', 'usage', 'attempt_error'))
            )
            """
        )
    )
    connection.execute(text("CREATE INDEX idx_model_turns_run ON model_turns (run_id)"))
    connection.execute(text("CREATE INDEX idx_model_turns_task_type ON model_turns (run_id, task_type)"))
    connection.execute(text("CREATE INDEX idx_model_turns_execution ON model_turns (execution_id)"))


def _migrate_model_turns(connection: Connection) -> dict[str, int]:
    orphaned = connection.execute(
        text(
            "SELECT count(*) FROM token_usage WHERE run_id IS NULL OR NOT EXISTS "
            "(SELECT 1 FROM analysis_runs r WHERE r.run_id = token_usage.run_id)"
        )
    ).scalar_one()
    if orphaned:
        raise ValueError(f"token_usage 存在 {orphaned} 条无 run 归属的记账行，拒绝静默丢弃，请先人工归档")

    # Agent 回合行：保留 agent_turns.id（agent_tool_calls.turn_id 外键不重接数据）
    connection.execute(
        text(
            """
            INSERT INTO model_turns (
                id, row_kind, run_id, task_type, call_type, model,
                execution_id, attempt_number, chapter_id, work_id, role, turn_index,
                status, error, raw_response, context_summary, request_messages, timing_notes,
                ttft_ms, first_visible_ms, reasoning_ms, model_ms, tool_wall_ms, turn_ms,
                prompt_tokens, completion_tokens, total_tokens, cache_read_tokens,
                reasoning_tokens, cost, accounting_source, started_at, finished_at
            )
            SELECT
                t.id, 'agent_turn', i.run_id, i.task_type,
                COALESCE(tk.call_type, CASE WHEN i.task_type = 'annotation' THEN 'agent' ELSE i.task_type END),
                COALESCE(tk.model, i.model_name, 'unknown'),
                i.execution_id, i.attempt_number, i.chapter_id, i.work_id, i.role, t.turn_index,
                t.status, t.error, t.raw_response, t.context_summary, t.request_messages, t.timing_notes,
                t.ttft_ms, t.first_visible_ms, t.reasoning_ms, t.model_ms, t.tool_wall_ms, t.turn_ms,
                tk.prompt_tokens, tk.completion_tokens, tk.total_tokens, tk.cache_read_tokens,
                tk.reasoning_tokens, tk.cost,
                COALESCE(tk.accounting_source, 'estimated'), t.started_at, t.finished_at
            FROM agent_turns t
            JOIN agent_invocations i ON i.id = t.invocation_id
            LEFT JOIN token_usage tk ON tk.agent_turn_id = t.id
            """
        )
    )
    turns = int(connection.execute(text("SELECT count(*) FROM model_turns WHERE row_kind = 'agent_turn'")).scalar_one())

    # 保留的旧 id 已占用序列起点，之后插入的记账行/派发行从 max(id) 之后取号
    connection.execute(
        text(
            "SELECT setval(pg_get_serial_sequence('model_turns', 'id'), "
            "GREATEST((SELECT COALESCE(MAX(id), 1) FROM model_turns), 1))"
        )
    )

    # 非 Agent 记账行（embedding 等）
    connection.execute(
        text(
            """
            INSERT INTO model_turns (
                row_kind, run_id, task_type, call_type, model, chapter_id, status,
                prompt_tokens, completion_tokens, total_tokens, cache_read_tokens,
                reasoning_tokens, cost, accounting_source, started_at, finished_at
            )
            SELECT 'usage', tk.run_id, tk.task_type, tk.call_type, tk.model, tk.chapter_id, 'success',
                   tk.prompt_tokens, tk.completion_tokens, tk.total_tokens, tk.cache_read_tokens,
                   tk.reasoning_tokens, tk.cost, tk.accounting_source,
                   tk.created_at::timestamp, tk.created_at::timestamp
            FROM token_usage tk
            WHERE tk.agent_turn_id IS NULL
            """
        )
    )
    usage = int(connection.execute(text("SELECT count(*) FROM model_turns WHERE row_kind = 'usage'")).scalar_one())

    # 无任何回合的失败/中断尝试补一行派发失败行，保留执行上下文与最终错误
    connection.execute(
        text(
            """
            INSERT INTO model_turns (
                row_kind, run_id, task_type, call_type, model,
                execution_id, attempt_number, chapter_id, work_id, role, turn_index,
                status, error, accounting_source, started_at, finished_at
            )
            SELECT 'attempt_error', i.run_id, i.task_type,
                   CASE WHEN i.task_type = 'annotation' THEN 'agent' ELSE i.task_type END,
                   COALESCE(i.model_name, 'unknown'),
                   i.execution_id, i.attempt_number, i.chapter_id, i.work_id, i.role, 0,
                   i.status, i.final_error, 'estimated', i.started_at, COALESCE(i.finished_at, i.started_at)
            FROM agent_invocations i
            WHERE i.status IN ('error', 'interrupted')
              AND NOT EXISTS (SELECT 1 FROM agent_turns t WHERE t.invocation_id = i.id)
            """
        )
    )
    attempts = int(
        connection.execute(text("SELECT count(*) FROM model_turns WHERE row_kind = 'attempt_error'")).scalar_one()
    )

    connection.execute(
        text(
            "SELECT setval(pg_get_serial_sequence('model_turns', 'id'), "
            "GREATEST((SELECT COALESCE(MAX(id), 1) FROM model_turns), 1))"
        )
    )
    return {"agent_turn": turns, "usage": usage, "attempt_error": attempts}


def _retarget_tool_call_fk(connection: Connection) -> None:
    # 旧工具表没有消息幂等键；历史值保持空，后续实际消息由唯一索引去重
    connection.execute(text("ALTER TABLE agent_tool_calls ADD COLUMN IF NOT EXISTS message_key VARCHAR(128)"))
    connection.execute(
        text("CREATE UNIQUE INDEX IF NOT EXISTS uq_agent_tool_calls_message_key ON agent_tool_calls (message_key)")
    )
    constraint = connection.execute(
        text(
            "SELECT conname FROM pg_constraint "
            "WHERE conrelid = 'agent_tool_calls'::regclass AND contype = 'f' "
            "AND confrelid = 'agent_turns'::regclass LIMIT 1"
        )
    ).scalar_one_or_none()
    if constraint:
        connection.execute(text(f"ALTER TABLE agent_tool_calls DROP CONSTRAINT {_identifier(str(constraint))}"))
    connection.execute(
        text(
            "ALTER TABLE agent_tool_calls ADD CONSTRAINT fk_agent_tool_calls_turn "
            "FOREIGN KEY (turn_id) REFERENCES model_turns (id) ON DELETE CASCADE"
        )
    )


def _create_analysis_outputs(connection: Connection) -> None:
    connection.execute(
        text(
            """
            CREATE TABLE analysis_outputs (
                output_id VARCHAR(36) NOT NULL PRIMARY KEY,
                run_id VARCHAR(36) NOT NULL REFERENCES analysis_runs (run_id) ON DELETE CASCADE,
                kind VARCHAR(20) NOT NULL,
                chapter_id INTEGER,
                role VARCHAR(20),
                payload JSONB NOT NULL,
                actual_input JSONB NOT NULL DEFAULT '{}',
                invocation_id VARCHAR(64),
                work_id VARCHAR(64) UNIQUE,
                created_at TIMESTAMP NOT NULL DEFAULT now(),
                CONSTRAINT ck_analysis_outputs_kind CHECK (kind IN ('chapter_annotation', 'agent_analysis'))
            )
            """
        )
    )
    connection.execute(
        text(
            "CREATE UNIQUE INDEX uq_analysis_outputs_chapter_role ON analysis_outputs (run_id, chapter_id, role) "
            "WHERE kind = 'chapter_annotation'"
        )
    )
    connection.execute(text("CREATE INDEX idx_analysis_outputs_run ON analysis_outputs (run_id)"))
    connection.execute(text("CREATE INDEX idx_analysis_outputs_run_chapter ON analysis_outputs (run_id, chapter_id)"))


def _migrate_analysis_outputs(connection: Connection) -> dict[str, int]:
    connection.execute(
        text(
            """
            INSERT INTO analysis_outputs (
                output_id, run_id, kind, chapter_id, role, payload, actual_input, invocation_id, work_id, created_at
            )
            SELECT annotation_id, run_id, 'chapter_annotation', chapter_id, role,
                   payload, COALESCE(actual_input, '{}'::jsonb), invocation_id, work_id, created_at
            FROM chapter_annotations
            """
        )
    )
    chapters = int(
        connection.execute(text("SELECT count(*) FROM analysis_outputs WHERE kind = 'chapter_annotation'")).scalar_one()
    )

    # 诊断产物只迁移每个 run 的最新一行（历史读侧即取最新），JSON 文本列转 JSONB，
    # jsonb_strip_nulls 把未填字段还原成“缺省”而不是显式 null
    connection.execute(
        text(
            """
            INSERT INTO analysis_outputs (output_id, run_id, kind, payload, created_at)
            SELECT gen_random_uuid()::text, c.run_id, 'agent_analysis', jsonb_strip_nulls(jsonb_build_object(
                'novel_id', c.novel_id,
                'foreshadow_expectation', c.foreshadow_expectation,
                'arc_scores', c.arc_scores::jsonb,
                'genre_labels', c.genre_labels::jsonb,
                'style_labels', c.style_labels::jsonb,
                'topic_labels', c.topic_labels::jsonb,
                'diagnosis', c.diagnosis,
                'value_logic_type', c.value_logic_type,
                'value_logic_reason', c.value_logic_reason,
                'power_stance_score', c.power_stance_score,
                'power_stance_reason', c.power_stance_reason,
                'common_people_dignity', c.common_people_dignity,
                'dignity_reason', c.dignity_reason,
                'cultural_depth_score', c.cultural_depth_score,
                'cultural_depth_reason', c.cultural_depth_reason,
                'narrative_arc_type', c.narrative_arc_type,
                'focus_structure', c.focus_structure,
                'focus_characters', c.focus_characters::jsonb,
                'main_characters', c.main_characters::jsonb,
                'core_cast', c.core_cast::jsonb,
                'theme_color', c.theme_color
            )), now()
            FROM (
                SELECT DISTINCT ON (run_id) *
                FROM cloud_analysis
                WHERE run_id IS NOT NULL
                ORDER BY run_id, id DESC
            ) c
            """
        )
    )
    agent = int(
        connection.execute(text("SELECT count(*) FROM analysis_outputs WHERE kind = 'agent_analysis'")).scalar_one()
    )
    return {"chapter_annotation": chapters, "agent_analysis": agent}


def _retarget_output_fks(connection: Connection) -> None:
    for table in ("graph_facts", "event_nodes", "event_edges"):
        constraint = connection.execute(
            text(
                "SELECT conname FROM pg_constraint "
                f"WHERE conrelid = '{table}'::regclass AND contype = 'f' "
                "AND confrelid = 'chapter_annotations'::regclass LIMIT 1"
            )
        ).scalar_one_or_none()
        if constraint:
            connection.execute(text(f"ALTER TABLE {table} DROP CONSTRAINT {_identifier(str(constraint))}"))
        connection.execute(
            text(
                f"ALTER TABLE {table} ADD CONSTRAINT fk_{table}_annotation "
                f"FOREIGN KEY (annotation_id) REFERENCES analysis_outputs (output_id) ON DELETE CASCADE"
            )
        )


def _merge_book_case_states(connection: Connection) -> int:
    connection.execute(text("ALTER TABLE book_cases ADD COLUMN state VARCHAR(20) NOT NULL DEFAULT 'pending'"))
    connection.execute(text("ALTER TABLE book_cases ADD COLUMN contributions JSONB NOT NULL DEFAULT '{}'"))
    connection.execute(
        text(
            "UPDATE book_cases bc SET state = s.state, contributions = s.contributions "
            "FROM book_case_states s WHERE s.case_id = bc.case_id"
        )
    )
    connection.execute(
        text(
            "ALTER TABLE book_cases ADD CONSTRAINT ck_book_case_state "
            "CHECK (state IN ('pending', 'resolved', 'deferred', 'contested'))"
        )
    )
    merged = int(connection.execute(text("SELECT count(*) FROM book_cases WHERE state <> 'pending'")).scalar_one())
    connection.execute(text("DROP TABLE book_case_states"))
    return merged


def _drop_source_tables(connection: Connection) -> None:
    connection.execute(text("DROP TABLE audit_messages"))
    connection.execute(text("DROP TABLE token_usage"))
    connection.execute(text("DROP TABLE agent_turns"))
    connection.execute(text("DROP TABLE agent_invocations"))
    connection.execute(text("DROP TABLE chapter_annotations"))
    connection.execute(text("DROP TABLE cloud_analysis"))


def apply_migration(connection: Connection) -> dict[str, Any]:
    plan = migration_plan(connection)
    if plan["already_migrated"]:
        raise ValueError("检测到目标结构已存在（model_turns/analysis_outputs 或 book_cases.state），无需重复迁移")
    if plan["partial_target"]:
        raise ValueError("目标结构只有部分存在，拒绝继续迁移，请先核对备份与实际结构")
    missing = sorted(set(SOURCE_TABLES) - set(plan["source_tables"]))
    if missing:
        raise ValueError(f"源表缺失，无法迁移: {missing}")
    if plan["missing_source_columns"]:
        raise ValueError(f"源字段不满足角色 work 中间结构，不能跳过旧数据转换: {plan['missing_source_columns']}")
    if plan["active_run_ids"]:
        raise ValueError("存在待运行或运行中的分析任务，请先停写并收口任务")
    counts: dict[str, Any] = {}
    _create_model_turns(connection)
    counts["model_turns"] = _migrate_model_turns(connection)
    _retarget_tool_call_fk(connection)
    _create_analysis_outputs(connection)
    counts["analysis_outputs"] = _migrate_analysis_outputs(connection)
    _retarget_output_fks(connection)
    counts["book_cases_merged_states"] = _merge_book_case_states(connection)
    _drop_source_tables(connection)
    return counts


def main() -> None:
    load_dotenv(Path(__file__).resolve().parents[2] / ".env")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="实际执行迁移（默认只读打印迁移计划）")
    parser.add_argument("--database-env", choices=("DATABASE", "TEST_DATABASE"), default="DATABASE")
    parser.add_argument("--schema", default=os.environ.get("DATABASE_SCHEMA", "public"))
    parser.add_argument("--expect-database", help="执行时必须提供实际目标数据库名")
    args = parser.parse_args()

    from src.storage.database_url import resolve_database_url_from_env

    url = resolve_database_url_from_env(args.database_env)
    if not url:
        raise SystemExit("DATABASE 环境变量未配置，无法连接数据库")
    if args.apply and args.expect_database != make_url(url).database:
        raise ValueError("--apply 必须用 --expect-database 指明匹配的数据库名")
    schema = _identifier(args.schema)
    engine = create_engine(url, connect_args={"connect_timeout": 5})
    try:
        # 在任何查询前开启事务，避免预检 SQL 已 autobegin 后再次 begin 报错
        with engine.begin() as connection:
            if not args.apply:
                connection.execute(text("SET TRANSACTION READ ONLY"))
            connection.execute(text(f"SET LOCAL search_path TO {schema}, public"))
            if connection.execute(text("SELECT current_schema()")).scalar_one() != args.schema:
                raise ValueError("目标 schema 不存在，拒绝回退到 public")
            plan = migration_plan(connection)
            print(json.dumps(plan, ensure_ascii=False, indent=2))
            if not args.apply:
                return
            counts = apply_migration(connection)
        print(json.dumps({"applied": True, "counts": counts}, ensure_ascii=False, indent=2))
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
