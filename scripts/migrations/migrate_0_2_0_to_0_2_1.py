"""0.2.0 → 0.2.1 发布迁移：预检只读，角色 work 与审计表合并在同一事务完成"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import tomllib
import unicodedata
from importlib import import_module
from pathlib import Path
from types import SimpleNamespace
from typing import TYPE_CHECKING, Any, Literal, cast

from dotenv import load_dotenv
from pydantic import ValidationError
from sqlalchemy import Connection, DateTime, Engine, create_engine, inspect, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from src.storage.database_url import resolve_database_url_from_env

if TYPE_CHECKING:
    from src.agents.annotation.output_models import BoundChapterAnnotation
    from src.event_trees.trees import EventTrees
    from src.fact_graph.contributions import FactContribution
    from src.fact_graph.evidence import EvidenceParagraph
    from src.fact_graph.graph import FactGraph, mention_uuid
    from src.storage.models import (
        AnalysisOutput,
        AnnotationWork,
        Base,
        BookCase,
        Chapter,
        EventEdge,
        EventNode,
        GraphEntity,
        Paragraph,
    )
    from src.utils.identity import stable_digest
    from src.work.annotation_work import annotation_work_id

DatabaseEnvironmentName = Literal["DATABASE", "TEST_DATABASE"]

VERSION = "0.2.1"

# 历史发布检查固定在该版本的表边界，不能随当前 ORM 增长而要求后续功能表
RELEASE_TABLES = frozenset(
    {
        "agent_tool_calls",
        "analysis_outputs",
        "analysis_runs",
        "annotation_work",
        "book_cases",
        "chapters",
        "dialogue_records",
        "entity_states",
        "event_edges",
        "event_nodes",
        "event_outbox",
        "global_stats",
        "graph_entities",
        "graph_facts",
        "graph_relations",
        "model_turns",
        "novels",
        "paragraph_curves",
        "paragraph_entities",
        "paragraph_linguistic_features",
        "paragraph_metrics",
        "paragraph_phrase_hits",
        "paragraph_pos_embeddings",
        "paragraph_topic_inference",
        "paragraph_topics",
        "paragraphs",
        "relation_states",
        "topic_model_runs",
        "word2vec_model_runs",
    }
)


_MERGE_SOURCE_TABLES = (
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


_MERGE_TARGET_TABLES = ("model_turns", "analysis_outputs")


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


_MERGE_ARCHIVE_TABLES = (
    "agent_invocations",
    "agent_turns",
    "token_usage",
    "audit_messages",
    "chapter_annotations",
    "cloud_analysis",
    "book_case_states",
    "agent_tool_calls",
    "book_cases",
)


def _merge_identifier(value: str) -> str:
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", value):
        raise ValueError(f"非法 schema/table 标识: {value}")
    return f'"{value}"'


def _merge_migration_plan(connection: Connection) -> dict[str, Any]:
    schema = str(connection.execute(text("SELECT current_schema()")).scalar_one())
    inspector = inspect(connection)
    tables = set(inspector.get_table_names(schema=schema))
    sources = [name for name in _MERGE_SOURCE_TABLES if name in tables]
    targets = [name for name in _MERGE_TARGET_TABLES if name in tables]
    book_case_columns = (
        {item["name"] for item in inspector.get_columns("book_cases", schema=schema)}
        if "book_cases" in tables
        else set()
    )
    book_case_state_column = "state" in book_case_columns or "contributions" in book_case_columns
    already_migrated = set(_MERGE_TARGET_TABLES) <= tables and {"state", "contributions"} <= book_case_columns
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
    archive = schema[:35] + "_turn_outputs_archive"
    return {
        "schema": schema,
        "archive_schema": schema[:35] + "_turn_outputs_archive",
        "source_tables": sources,
        "already_migrated": already_migrated,
        "partial_target": bool(targets or book_case_state_column) and not already_migrated,
        "missing_source_tables": sorted(set(_MERGE_SOURCE_TABLES) - tables),
        "missing_source_columns": {table: missing for table, missing in missing_columns.items() if missing},
        "active_run_ids": [str(run_id) for run_id in active],
        "archive_collision": inspector.has_schema(archive) and bool(inspector.get_table_names(schema=archive)),
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


def _merge_archive(connection: Connection, schema: str, archive: str) -> None:
    connection.execute(text(f"CREATE SCHEMA IF NOT EXISTS {_merge_identifier(archive)}"))
    for table in _MERGE_ARCHIVE_TABLES:
        connection.execute(
            text(
                f"CREATE TABLE {_merge_identifier(archive)}.{_merge_identifier(table)} AS "
                f"TABLE {_merge_identifier(schema)}.{_merge_identifier(table)}"
            )
        )


def _merge_create_model_turns(connection: Connection) -> None:
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


def _merge_migrate_model_turns(connection: Connection) -> dict[str, int]:
    orphaned = connection.execute(
        text(
            "SELECT count(*) FROM token_usage WHERE run_id IS NULL OR NOT EXISTS "
            "(SELECT 1 FROM analysis_runs r WHERE r.run_id = token_usage.run_id)"
        )
    ).scalar_one()
    if orphaned:
        raise ValueError(f"token_usage 存在 {orphaned} 条无 run 归属的记账行，拒绝静默丢弃，请先人工归档")

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

    connection.execute(
        text(
            "SELECT setval(pg_get_serial_sequence('model_turns', 'id'), "
            "GREATEST((SELECT COALESCE(MAX(id), 1) FROM model_turns), 1))"
        )
    )

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


def _merge_retarget_tool_call_fk(connection: Connection) -> None:

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
        connection.execute(text(f"ALTER TABLE agent_tool_calls DROP CONSTRAINT {_merge_identifier(str(constraint))}"))
    connection.execute(
        text(
            "ALTER TABLE agent_tool_calls ADD CONSTRAINT fk_agent_tool_calls_turn "
            "FOREIGN KEY (turn_id) REFERENCES model_turns (id) ON DELETE CASCADE"
        )
    )


def _merge_create_analysis_outputs(connection: Connection) -> None:
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


def _merge_migrate_analysis_outputs(connection: Connection) -> dict[str, int]:
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


def _merge_retarget_output_fks(connection: Connection) -> None:
    for table in ("graph_facts", "event_nodes", "event_edges"):
        constraint = connection.execute(
            text(
                "SELECT conname FROM pg_constraint "
                f"WHERE conrelid = '{table}'::regclass AND contype = 'f' "
                "AND confrelid = 'chapter_annotations'::regclass LIMIT 1"
            )
        ).scalar_one_or_none()
        if constraint:
            connection.execute(text(f"ALTER TABLE {table} DROP CONSTRAINT {_merge_identifier(str(constraint))}"))
        connection.execute(
            text(
                f"ALTER TABLE {table} ADD CONSTRAINT fk_{table}_annotation "
                f"FOREIGN KEY (annotation_id) REFERENCES analysis_outputs (output_id) ON DELETE CASCADE"
            )
        )


def _merge_merge_book_case_states(connection: Connection) -> int:
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


def _merge_drop_source_tables(connection: Connection) -> None:
    connection.execute(text("DROP TABLE audit_messages"))
    connection.execute(text("DROP TABLE token_usage"))
    connection.execute(text("DROP TABLE agent_turns"))
    connection.execute(text("DROP TABLE agent_invocations"))
    connection.execute(text("DROP TABLE chapter_annotations"))
    connection.execute(text("DROP TABLE cloud_analysis"))


def _merge_turn_outputs(connection: Connection) -> dict[str, Any]:
    plan = _merge_migration_plan(connection)
    schema = str(plan["schema"])
    archive = str(plan["archive_schema"])
    if plan["already_migrated"]:
        raise ValueError("检测到目标结构已存在（model_turns/analysis_outputs 或 book_cases.state），无需重复迁移")
    if plan["partial_target"]:
        raise ValueError("目标结构只有部分存在，拒绝继续迁移，请先核对备份与实际结构")
    missing = sorted(set(_MERGE_SOURCE_TABLES) - set(plan["source_tables"]))
    if missing:
        raise ValueError(f"源表缺失，无法迁移: {missing}")
    if plan["missing_source_columns"]:
        raise ValueError(f"源字段不满足角色 work 中间结构，不能跳过旧数据转换: {plan['missing_source_columns']}")
    if plan["active_run_ids"]:
        raise ValueError("存在待运行或运行中的分析任务，请先停写并收口任务")
    if plan["archive_collision"]:
        raise ValueError("归档 schema 已有表，拒绝覆盖恢复依据")
    counts: dict[str, Any] = {}
    connection.execute(text(f"CREATE SCHEMA IF NOT EXISTS {_merge_identifier(archive)}"))
    _merge_archive(connection, schema, archive)
    _merge_create_model_turns(connection)
    counts["model_turns"] = _merge_migrate_model_turns(connection)
    _merge_retarget_tool_call_fk(connection)
    _merge_create_analysis_outputs(connection)
    counts["analysis_outputs"] = _merge_migrate_analysis_outputs(connection)
    _merge_retarget_output_fks(connection)
    counts["book_cases_merged_states"] = _merge_merge_book_case_states(connection)
    _merge_drop_source_tables(connection)
    counts["archive_schema"] = archive
    return counts


def _load_release_models() -> None:
    """加载匹配目标发布的领域模型与 ORM"""
    root = Path(__file__).resolve().parents[2]
    with (root / "pyproject.toml").open("rb") as stream:
        release = tomllib.load(stream)["project"]["version"]
    if release != VERSION:
        raise ValueError(f"请使用 {VERSION} 发布代码运行本迁移，当前项目版本为 {release}")
    modules = {
        "src.agents.annotation.output_models": ("BoundChapterAnnotation",),
        "src.event_trees.trees": ("EventTrees",),
        "src.fact_graph.contributions": ("FactContribution",),
        "src.fact_graph.evidence": ("EvidenceParagraph",),
        "src.fact_graph.graph": ("FactGraph", "mention_uuid"),
        "src.storage.models": (
            "AnalysisOutput",
            "AnnotationWork",
            "Base",
            "BookCase",
            "Chapter",
            "EventEdge",
            "EventNode",
            "GraphEntity",
            "Paragraph",
        ),
        "src.utils.identity": ("stable_digest",),
        "src.work.annotation_work": ("annotation_work_id",),
    }
    for module_name, names in modules.items():
        module = import_module(module_name)
        for name in names:
            globals()[name] = getattr(module, name)


def inspect_current_schema(engine: Engine | Connection, *, schema: str = "public") -> dict[str, Any]:
    """核对 0.2.1 发布表的字段与外键，动态向量表继续由专用入口管理"""
    schema_inspector = inspect(engine)
    existing = set(schema_inspector.get_table_names(schema=schema))
    required = {name: Base.metadata.tables[name] for name in RELEASE_TABLES}
    missing_tables = sorted(required.keys() - existing)
    missing_columns: dict[str, list[str]] = {}
    missing_foreign_keys: dict[str, list[str]] = {}
    for name, table in required.items():
        if name not in existing:
            continue
        columns = {column["name"] for column in schema_inspector.get_columns(name, schema=schema)}
        missing = sorted(set(table.columns.keys()) - columns)
        if missing:
            missing_columns[name] = missing
        actual = {
            (
                tuple(fk["constrained_columns"]),
                fk.get("referred_schema") or schema,
                fk["referred_table"],
                tuple(fk["referred_columns"]),
            )
            for fk in schema_inspector.get_foreign_keys(name, schema=schema)
        }
        for fk in table.foreign_key_constraints:
            expected = (
                tuple(element.parent.name for element in fk.elements),
                fk.referred_table.schema or schema,
                fk.referred_table.name,
                tuple(element.column.name for element in fk.elements),
            )
            if expected not in actual:
                missing_foreign_keys.setdefault(name, []).append(
                    f"{','.join(expected[0])} -> {expected[1]}.{expected[2]}({','.join(expected[3])})"
                )
    return {
        "ready": not missing_tables and not missing_columns and not missing_foreign_keys,
        "missing_tables": missing_tables,
        "missing_columns": missing_columns,
        "missing_foreign_keys": missing_foreign_keys,
    }


RETIRED = (
    "work_items",
    "semantic_commands",
    "text_evidence",
    "command_outcomes",
    "continuity_cases",
    "case_heads",
    "case_claims",
    "analysis_cutoffs",
    "partition_heads",
    "cutoff_partitions",
    "source_manifests",
    "formal_artifacts",
    "global_context",
    "chapter_summaries",
    "stage_summaries",
)
# 六表合并迁移会 DROP 的源表；外键解除与退役范围都包含它们
MERGE_DROPPED = frozenset(
    {
        "audit_messages",
        "token_usage",
        "agent_turns",
        "agent_invocations",
        "chapter_annotations",
        "cloud_analysis",
        "book_case_states",
    }
)
RETIRED_TABLES = frozenset(RETIRED) | MERGE_DROPPED
ADDITIONS = {
    "chapter_annotations": {
        "role": "varchar(20) NOT NULL DEFAULT 'solo'",
        "actual_input": "jsonb NOT NULL DEFAULT '{}'",
        "invocation_id": "varchar(64)",
    },
    "agent_invocations": {"work_id": "varchar(64)", "role": "varchar(20)", "execution_id": "varchar(64) UNIQUE"},
    "agent_tool_calls": {"message_key": "varchar(128)"},
    "graph_facts": {"author_work_id": "varchar(64)"},
    "entity_states": {"author_work_id": "varchar(64)"},
    "relation_states": {"author_work_id": "varchar(64)"},
    "event_nodes": {
        "author_work_id": "varchar(64)",
        "producer_invocation_id": "varchar(64)",
        "parent_node_id": "varchar(36)",
    },
    "event_edges": {"author_work_id": "varchar(64)", "cause_role": "varchar(16)"},
    "dialogue_records": {"author_work_id": "varchar(64)"},
}
NEW_TABLES = {"model_turns", "analysis_outputs", "annotation_work", "book_cases"}


def _identifier(value: str) -> str:
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", value) or len(value) > 63:
        raise ValueError(f"非法 PostgreSQL 标识符: {value}")
    return f'"{value}"'


def _constraint_identifier(name: str | None) -> str:
    if name is None:
        raise ValueError("源约束没有名称，不能安全重接归档外键")
    return _identifier(name)


def normalized_name(value: str) -> str:
    """冻结 0.2.0 身份裁决的名称口径，不修改当前运行时接口"""
    return unicodedata.normalize("NFC", value).strip().casefold()


def _current_annotations(session: Session) -> list[Any]:
    return [
        SimpleNamespace(
            annotation_id=row.output_id,
            run_id=row.run_id,
            chapter_id=row.chapter_id,
            payload=row.payload,
            actual_input=row.actual_input,
            work_id=row.work_id,
            invocation_id=row.invocation_id,
            role=row.role,
        )
        for row in session.execute(select(AnalysisOutput).where(AnalysisOutput.kind == "chapter_annotation")).scalars()
    ]


def _legacy_annotations(connection: Connection) -> list[Any]:
    return [SimpleNamespace(**row) for row in connection.execute(text("SELECT * FROM chapter_annotations")).mappings()]


def migration_plan(connection: Connection) -> dict[str, Any]:
    """检查原始源结构与转换阻塞，不借预检创建当前表或修改历史身份"""
    schema = str(connection.execute(text("SELECT current_schema()")).scalar_one())
    inspector = inspect(connection)
    tables = set(inspector.get_table_names(schema=schema))
    current = inspect_current_schema(connection, schema=schema)
    retired = sorted(set(RETIRED) & tables)
    result: dict[str, Any] = {
        "version": VERSION,
        "schema": schema,
        "already_migrated": current["ready"] and not retired,
        "retired_tables": retired,
        "current_schema": current,
        "blocking_issues": [],
        "active_run_ids": [],
    }
    if result["already_migrated"]:
        result["active_run_ids"] = list(
            connection.execute(
                text(
                    "SELECT run_id FROM analysis_runs WHERE status IN ('pending', 'running', 'cancelling') "
                    "ORDER BY run_id"
                )
            ).scalars()
        )
        return result
    issues = result["blocking_issues"]
    if {"model_turns", "analysis_outputs"} & tables:
        issues.append({"reason": "目标结构部分存在或混有旧流水线，先核对备份和迁移记录"})
        return result
    required = {
        table.name: set(table.columns.keys()) - set(ADDITIONS.get(table.name, {}))
        for table in Base.metadata.sorted_tables
        if table.name in RELEASE_TABLES - NEW_TABLES
    }
    for name, fields in SOURCE_COLUMNS.items():
        if name in {"book_cases", "book_case_states", "audit_messages"}:
            continue
        required[name] = required.get(name, set()) | (fields - set(ADDITIONS.get(name, {})))
    required["chapter_annotations"] = {"annotation_id", "run_id", "chapter_id", "payload", "created_at"}
    missing_tables = sorted(required.keys() - tables)
    missing_columns = {
        name: sorted(fields - {column["name"] for column in inspector.get_columns(name, schema=schema)})
        for name, fields in required.items()
        if name in tables
    }
    result["missing_source_tables"] = missing_tables
    result["missing_source_columns"] = {name: fields for name, fields in missing_columns.items() if fields}
    if missing_tables or result["missing_source_columns"]:
        issues.append(
            {
                "reason": "源数据库不满足 0.2.0 合同",
                "tables": missing_tables,
                "columns": result["missing_source_columns"],
            }
        )
        return result
    result["active_run_ids"] = list(
        connection.execute(
            text(
                "SELECT run_id FROM analysis_runs WHERE status IN ('pending', 'running', 'cancelling') ORDER BY run_id"
            )
        ).scalars()
    )
    if result["active_run_ids"]:
        issues.append({"reason": "分析任务尚未收口", "run_ids": result["active_run_ids"]})
    if "annotation_work" in tables and not retired:
        merge_plan = _merge_migration_plan(connection)
        result["merge_only"] = True
        result["merge_plan"] = merge_plan
        for key in ("partial_target", "missing_source_tables", "missing_source_columns", "archive_collision"):
            if merge_plan[key]:
                issues.append({"reason": "审计产物合并预检未通过", "check": key, "details": merge_plan[key]})
        return result
    records = _legacy_annotations(connection)
    current_records = [
        row for row in records if getattr(row, "actual_input", None) and getattr(row, "invocation_id", None)
    ]
    legacy_records = [row for row in records if row not in current_records]
    result["output_preflight"] = {"legacy_count": len(legacy_records), "current_saved_count": len(current_records)}
    if current_records and legacy_records:
        issues.append(
            {
                "reason": "旧章与当前已保存 work 混存，不能重建不可变贡献",
                "annotation_ids": [row.annotation_id for row in legacy_records],
                "current_annotation_ids": [row.annotation_id for row in current_records],
            }
        )
    if current_records and retired:
        issues.append({"reason": "角色 work 已保存但旧流水线仍在，先核对实际转换阶段"})
    elif current_records and not legacy_records:
        issues.append({"reason": "角色 work 已保存但缺少 annotation_work 表，先核对备份和实际结构"})
    identity = _identity_preflight(connection, tables)
    result["identity_preflight"] = identity
    issues.extend(identity["issues"])
    for row in records:
        chapter = connection.execute(
            text("SELECT text FROM chapters WHERE run_id=:run AND chapter_id=:chapter"),
            {"run": row.run_id, "chapter": row.chapter_id},
        ).scalar_one_or_none()
        paragraphs = connection.execute(
            text("SELECT count(*) FROM paragraphs WHERE run_id=:run AND chapter_id=:chapter"),
            {"run": row.run_id, "chapter": row.chapter_id},
        ).scalar_one()
        if not chapter or not paragraphs:
            issues.append(
                {
                    "annotation_id": row.annotation_id,
                    "run_id": row.run_id,
                    "chapter_id": row.chapter_id,
                    "reason": "原章输入或段落缺失",
                }
            )
        try:
            BoundChapterAnnotation.model_validate(row.payload)
        except ValidationError as error:
            issues.append(
                {
                    "annotation_id": row.annotation_id,
                    "reason": "原章产物不满足迁移合同",
                    "fields": [".".join(map(str, item["loc"])) for item in error.errors(include_input=False)],
                }
            )
    for table in ("graph_facts", "event_nodes", "event_edges"):
        orphans = list(
            connection.execute(
                text(
                    f"SELECT DISTINCT source.annotation_id FROM {_identifier(table)} source "
                    "LEFT JOIN chapter_annotations saved ON saved.annotation_id=source.annotation_id "
                    "AND saved.run_id=source.run_id WHERE saved.annotation_id IS NULL"
                )
            ).scalars()
        )
        if orphans:
            issues.append({"table": table, "annotation_ids": orphans, "reason": "有业务记录缺成功保存章来源"})
    for table, key in (("entity_states", "entity_id"), ("relation_states", "relation_id")):
        orphan_states = list(
            connection.execute(
                text(
                    f"SELECT source.run_id, source.chapter_id, source.{_identifier(key)} "
                    f"FROM {_identifier(table)} source LEFT JOIN chapter_annotations saved "
                    "ON saved.run_id=source.run_id AND saved.chapter_id=source.chapter_id "
                    "WHERE saved.annotation_id IS NULL"
                )
            ).mappings()
        )
        if orphan_states:
            issues.append(
                {"table": table, "records": [dict(row) for row in orphan_states], "reason": "状态缺成功保存章来源"}
            )
    if "continuity_cases" in tables:
        for row in connection.execute(text("SELECT case_id, description FROM continuity_cases")).mappings():
            description = " ".join(unicodedata.normalize("NFC", row["description"] or "").split())
            if not description or len(description) > 100:
                issues.append({"case_id": row["case_id"], "reason": "案例说明不满足 1..100 字"})
    return result


def _prepare_role_schema(connection: Connection, plan: dict[str, Any]) -> None:
    """原 schema 增量改造：解除退役表外键、补列建表、替换约束，不复制不归档"""
    schema = plan["schema"]
    inspector = inspect(connection)
    source_tables = inspector.get_table_names(schema=schema)
    for table in source_tables:
        for fk in inspector.get_foreign_keys(table, schema=schema):
            if fk["referred_table"] in RETIRED_TABLES:
                connection.execute(
                    text(f"ALTER TABLE {_identifier(table)} DROP CONSTRAINT {_constraint_identifier(fk['name'])}")
                )
    columns = {column["name"] for column in inspect(connection).get_columns("chapter_annotations", schema=schema)}
    if "work_id" not in columns:
        if "formal_work_id" in columns:
            connection.execute(text("ALTER TABLE chapter_annotations RENAME COLUMN formal_work_id TO work_id"))
        else:
            connection.execute(text("ALTER TABLE chapter_annotations ADD COLUMN work_id varchar(64) UNIQUE"))
    for table, additions in ADDITIONS.items():
        existing = {column["name"] for column in inspect(connection).get_columns(table, schema=schema)}
        for column, ddl in additions.items():
            if column not in existing:
                connection.execute(text(f"ALTER TABLE {_identifier(table)} ADD COLUMN {_identifier(column)} {ddl}"))
    Base.metadata.tables["annotation_work"].create(connection, checkfirst=True)
    connection.execute(
        text(
            "CREATE TABLE IF NOT EXISTS book_cases (case_id varchar(64) PRIMARY KEY, "
            "run_id varchar(36) NOT NULL REFERENCES analysis_runs(run_id) ON DELETE CASCADE, "
            "description text NOT NULL, created_at timestamp NOT NULL DEFAULT now())"
        )
    )
    connection.execute(
        text(
            "CREATE TABLE IF NOT EXISTS book_case_states (case_id varchar(64) PRIMARY KEY "
            "REFERENCES book_cases(case_id) ON DELETE CASCADE, "
            "state varchar(20) NOT NULL, contributions jsonb NOT NULL)"
        )
    )
    connection.execute(
        text(
            "CREATE TABLE IF NOT EXISTS audit_messages (message_id varchar(128) PRIMARY KEY, "
            "execution_id varchar(64) NOT NULL, method varchar(50) NOT NULL, "
            "local_id integer NOT NULL, result_id integer)"
        )
    )
    for constraint in inspect(connection).get_unique_constraints("chapter_annotations", schema=schema):
        if set(constraint["column_names"]) == {"run_id", "chapter_id"}:
            connection.execute(
                text(f"ALTER TABLE chapter_annotations DROP CONSTRAINT {_constraint_identifier(constraint['name'])}")
            )
    for constraint in inspect(connection).get_unique_constraints("event_edges", schema=schema):
        if set(constraint["column_names"]) in (
            {"run_id", "source_event_id", "target_event_id"},
            {"run_id", "source_event_id", "target_event_id", "author_work_id"},
        ):
            connection.execute(
                text(f"ALTER TABLE event_edges DROP CONSTRAINT {_constraint_identifier(constraint['name'])}")
            )
    if "uq_event_edges_author" not in {
        constraint["name"] for constraint in inspect(connection).get_unique_constraints("event_edges", schema=schema)
    }:
        connection.execute(
            text(
                "ALTER TABLE event_edges ADD CONSTRAINT uq_event_edges_author "
                "UNIQUE(run_id, source_event_id, target_event_id, edge_type, author_work_id)"
            )
        )
    if "global_context" in plan["retired_tables"]:
        connection.execute(
            text(
                f"UPDATE novels n SET title=g.novel_title FROM {_identifier('global_context')} g "
                "WHERE n.novel_id=g.novel_id AND n.title IS NULL"
            )
        )


def _align_timestamps(connection: Connection, schema: str) -> None:
    """旧带时区时间转为当前 UTC 无时区列，显式保留同一时刻"""
    inspector = inspect(connection)
    tables = set(inspector.get_table_names(schema=schema))
    for table in Base.metadata.sorted_tables:
        if table.name not in tables or table.name not in RELEASE_TABLES:
            continue
        for column in inspector.get_columns(table.name, schema=schema):
            expected = table.columns.get(column["name"])
            if (
                expected is not None
                and isinstance(expected.type, DateTime)
                and not expected.type.timezone
                and isinstance(column["type"], DateTime)
                and column["type"].timezone
            ):
                field = _identifier(column["name"])
                connection.execute(
                    text(
                        f"ALTER TABLE {_identifier(table.name)} ALTER COLUMN {field} "
                        f"TYPE timestamp without time zone USING {field} AT TIME ZONE 'UTC'"
                    )
                )


def _convert_outputs(session: Session) -> int:
    """恢复原始正文输入和真实生产身份，不补造模型请求或用量"""
    records = _legacy_annotations(session.connection())
    for record in records:
        if record.actual_input and record.invocation_id:
            continue
        chapter = session.get(Chapter, (record.chapter_id, record.run_id))
        paragraphs = list(
            session.execute(
                select(Paragraph)
                .where(Paragraph.run_id == record.run_id, Paragraph.chapter_id == record.chapter_id)
                .order_by(Paragraph.paragraph_index)
            ).scalars()
        )
        if chapter is None or chapter.text is None or not paragraphs:
            raise ValueError(f"annotation_id={record.annotation_id} 原章输入或段落缺失")
        output = BoundChapterAnnotation.model_validate(record.payload)
        work_id = annotation_work_id(record.run_id, record.chapter_id, "solo")
        audits = (
            session.execute(
                text(
                    "SELECT id, execution_id FROM agent_invocations WHERE run_id=:run AND chapter_id=:chapter "
                    "AND task_type='annotation' AND status='success' ORDER BY id"
                ),
                {"run": record.run_id, "chapter": record.chapter_id},
            )
            .mappings()
            .all()
        )
        # 旧表没有审计到产物的外键，多条成功尝试不能按最新 id 推测实际生产者
        audit = audits[0] if len(audits) == 1 else None
        invocation = (audit["execution_id"] or f"audit:{audit['id']}") if audit else record.annotation_id
        if audit:
            session.execute(
                text("UPDATE agent_invocations SET work_id=:work, role='solo' WHERE id=:id"),
                {"work": work_id, "id": audit["id"]},
            )
        actual = {
            "chapter_id": record.chapter_id,
            "chapter_sequence": chapter.sequence,
            "chapter_label": chapter.display_index_label or str(chapter.sequence),
            "chapter_text": chapter.text,
            "chapter_chars": len(chapter.text),
            "role": "solo",
            "paragraphs": [
                {
                    name: getattr(row, name)
                    for name in ("chapter_id", "paragraph_id", "text", "local_start_char", "local_end_char")
                }
                for row in paragraphs
            ],
        }
        session.execute(
            text(
                "UPDATE chapter_annotations SET work_id=:work, invocation_id=:invocation, role='solo', "
                "actual_input=CAST(:actual AS jsonb) WHERE annotation_id=:annotation"
            ),
            {
                "work": work_id,
                "invocation": invocation,
                "actual": json.dumps(actual, ensure_ascii=False),
                "annotation": record.annotation_id,
            },
        )
        session.add(
            AnnotationWork(
                work_id=work_id,
                run_id=record.run_id,
                chapter_id=record.chapter_id,
                role="solo",
                invocation_id=invocation,
                state="saved",
            )
        )
        events = {event.node_id: event for event in output.events}
        for node in session.execute(select(EventNode).where(EventNode.annotation_id == record.annotation_id)).scalars():
            if node.event_id not in events:
                raise ValueError(f"event_id={node.event_id} 缺少原产物节点")
            node.author_work_id, node.producer_invocation_id = work_id, invocation
            node.parent_node_id = events[node.event_id].parent_node_id
        for edge in session.execute(select(EventEdge).where(EventEdge.annotation_id == record.annotation_id)).scalars():
            edge.author_work_id = work_id
            child = events.get(edge.target_event_id)
            edge.cause_role = (
                child.cause_role
                if edge.edge_type == "causal" and child and child.parent_node_id == edge.source_event_id
                else None
            )
        session.execute(
            text("UPDATE graph_facts SET author_work_id=:work WHERE annotation_id=:annotation"),
            {"work": work_id, "annotation": record.annotation_id},
        )
        session.execute(
            text("UPDATE dialogue_records SET author_work_id=:work WHERE run_id=:run AND chapter_id=:chapter"),
            {"work": work_id, "run": record.run_id, "chapter": record.chapter_id},
        )
        session.flush()
    return len(records)


def _convert_cases(session: Session) -> int:
    """只迁移真实保存章的纯文字登记，旧结构化办理状态随退役表一并退出"""
    if not inspect(session.connection()).has_table("continuity_cases"):
        return 0
    by_id = {row.annotation_id: row for row in _current_annotations(session)}
    count = 0
    for row in session.execute(text(f"SELECT * FROM {_identifier('continuity_cases')}")).mappings():
        record = by_id.get(row["originating_annotation_id"])
        if record is None:
            continue
        description = " ".join(unicodedata.normalize("NFC", row["description"]).split())
        identifier = stable_digest(row["run_id"], description)
        case = session.get(BookCase, identifier)
        contribution = {"invocation_id": record.invocation_id, "deliveries": []}
        if case is None:
            session.add(
                BookCase(
                    case_id=identifier,
                    run_id=row["run_id"],
                    description=description,
                    state="pending",
                    contributions={record.work_id: contribution},
                    created_at=row["created_at"],
                )
            )
            count += 1
        else:
            case.contributions = {**case.contributions, record.work_id: contribution}
        session.flush()
    return count


def _migrate_identity_decisions(
    entities: list[Any],
    states: list[Any],
    records: list[Any],
    facts: list[Any],
    operations: dict[str, dict[str, list[dict[str, Any]]]],
    *,
    decision_entity_ids: set[str] | None = None,
) -> int:
    """将明确旧裁决迁为同一人物贡献，作者只取真实身份事实或实体状态来源"""
    from copy import deepcopy

    entity_by_id = {row.entity_id: row for row in entities}
    record_by_annotation = {row.annotation_id: row for row in records}
    record_by_chapter = {(row.run_id, row.chapter_id): row for row in records}
    active: dict[str, set[tuple[str, str]]] = {}
    for record in sorted(records, key=lambda row: (row.run_id, row.actual_input["chapter_sequence"], row.work_id)):
        for op in operations[record.work_id]["relation_assert_ops"]:
            if op["relation_type"] != "同一人物":
                continue
            left_name, right_name = sorted((normalized_name(op["from_entity"]), normalized_name(op["to_entity"])))
            pair = (left_name, right_name)
            edges = active.setdefault(record.run_id, set())
            if op.get("change_kind", "assert") in {"break", "retract"}:
                edges.discard(pair)
            else:
                edges.add(pair)

    def already_connected(run_id: str, left: str, right: str) -> bool:
        seen, todo = set(), [normalized_name(left)]
        target = normalized_name(right)
        while todo:
            current = todo.pop()
            if current == target:
                return True
            if current in seen:
                continue
            seen.add(current)
            for a, b in active.get(run_id, set()):
                if current == a:
                    todo.append(b)
                elif current == b:
                    todo.append(a)
        return False

    converted = 0
    for entity in entities:
        if decision_entity_ids is not None and entity.entity_id not in decision_entity_ids:
            continue
        attributes = entity.attributes or {}
        target_id = attributes.get("canonical_entity_id")
        if not target_id or target_id == entity.entity_id or attributes.get("identity_status") == "contested":
            continue
        target = entity_by_id.get(target_id)
        if target is None or target.run_id != entity.run_id:
            raise ValueError(f"旧身份 entity_id={entity.entity_id} canonical_entity_id={target_id} 没有同 run 有效端点")
        if entity.entity_type != "character" or target.entity_type != "character":
            raise ValueError(f"旧身份 entity_id={entity.entity_id} canonical_entity_id={target_id} 端点不是人物")
        if target_id in attributes.get("different_entity_ids", []) or entity.entity_id in (target.attributes or {}).get(
            "different_entity_ids", []
        ):
            raise ValueError(
                f"旧身份 entity_id={entity.entity_id} canonical_entity_id={target_id} 与 different 裁决冲突"
            )
        identity_facts = [
            fact
            for fact in facts
            if fact.run_id == entity.run_id
            and fact.fact_type == "identity"
            and fact.subject_entity_id == entity.entity_id
        ]
        if identity_facts:
            latest_fact = identity_facts[-1]
            latest_value = latest_fact.value if isinstance(latest_fact.value, dict) else {}
            targets = {
                value
                for value in (
                    (latest_fact.content or {}).get("canonical_entity_id"),
                    latest_value.get("canonical_entity_id"),
                )
                if value
            }
            kinds = {
                value
                for value in ((latest_fact.content or {}).get("identity_kind"), latest_value.get("identity_kind"))
                if value
            }
            if len(targets) > 1 or len(kinds) > 1 or targets and target_id not in targets:
                raise ValueError(
                    f"旧身份 fact_id={latest_fact.fact_id} 裁决目标={sorted(targets)} "
                    f"与 entity_id={entity.entity_id} canonical_entity_id={target_id} 不一致"
                )
            if "different" in kinds:
                raise ValueError(f"旧身份 fact_id={latest_fact.fact_id} 与当前 canonical 同一人物裁决冲突")
        exact = [
            fact
            for fact in identity_facts
            if (fact.content or {}).get("canonical_entity_id") == target_id
            or (isinstance(fact.value, dict) and fact.value.get("canonical_entity_id") == target_id)
        ]
        if exact and (exact[-1].content or {}).get("identity_kind") == "different":
            raise ValueError(
                f"旧身份 fact_id={exact[-1].fact_id} canonical_entity_id={target_id} 与 different 裁决冲突"
            )
        if already_connected(entity.run_id, entity.canonical_name, target.canonical_name):
            continue
        source: dict[str, Any]
        if exact:
            fact = exact[-1]
            record = record_by_annotation.get(fact.annotation_id)
            if record is None or record.run_id != fact.run_id or record.chapter_id != fact.chapter_id:
                raise ValueError(f"旧身份 fact_id={fact.fact_id} annotation_id={fact.annotation_id} 缺成功保存章来源")
            source = {
                "table": "graph_facts",
                "fact_id": fact.fact_id,
                "annotation_id": fact.annotation_id,
                "chapter_id": fact.chapter_id,
                "value": deepcopy(fact.value),
                "content": deepcopy(fact.content),
            }
            reason = fact.value.get("reason") if isinstance(fact.value, dict) else None
        else:
            candidates = [
                state
                for state in states
                if state.entity_id == entity.entity_id
                and isinstance(state.state, dict)
                and state.state.get("attributes", state.state).get("canonical_entity_id") == target_id
                and state.state.get("attributes", state.state).get("identity_status") != "contested"
                and (entity.run_id, state.chapter_id) in record_by_chapter
            ]
            if not candidates:
                raise ValueError(
                    f"旧身份 entity_id={entity.entity_id} canonical_entity_id={target_id} "
                    "缺可对应成功保存章的 identity 事实或实体状态裁决来源，不能推测作者和章节"
                )
            state = max(
                candidates,
                key=lambda row: record_by_chapter[(entity.run_id, row.chapter_id)].actual_input["chapter_sequence"],
            )
            record = record_by_chapter[(entity.run_id, state.chapter_id)]
            source = {
                "table": "entity_states",
                "entity_id": entity.entity_id,
                "chapter_id": state.chapter_id,
                "state": deepcopy(state.state),
            }
            reason = None
        op = {
            "from_entity": entity.canonical_name,
            "to_entity": target.canonical_name,
            "relation_type": "同一人物",
            "chapter_id": record.chapter_id,
            "change_kind": "assert",
            "identity_kind": "same",
            "reason": reason,
            "migration_source": source,
        }
        operations[record.work_id]["relation_assert_ops"].append(op)
        left_name, right_name = sorted((normalized_name(entity.canonical_name), normalized_name(target.canonical_name)))
        active.setdefault(entity.run_id, set()).add((left_name, right_name))
        converted += 1
    return converted


def _identity_preflight(connection: Connection, tables: set[str]) -> dict[str, Any]:
    """旧 schema 直接只读取事实，转换规则与 apply 相同，逐记录报告身份来源阻塞"""
    from copy import deepcopy

    required = {"graph_entities", "entity_states", "graph_facts", "chapter_annotations", "chapters"}
    if not required <= tables:
        return {
            "checked_decisions": 0,
            "convertible_decisions": 0,
            "issues": [{"missing_tables": sorted(required - tables), "reason": "无法检查旧身份来源"}],
        }

    def read(table: str, *, order: str | None = None) -> list[Any]:
        suffix = f" ORDER BY {_identifier(order)}" if order else ""
        return [
            SimpleNamespace(**row)
            for row in connection.execute(text(f"SELECT * FROM {_identifier(table)}{suffix}")).mappings()
        ]

    entities, states = read("graph_entities"), read("entity_states")
    facts, records = read("graph_facts", order="graph_fact_id"), read("chapter_annotations")
    chapters = {(row.run_id, row.chapter_id): row for row in read("chapters")}
    for record in records:
        actual = getattr(record, "actual_input", None) or {}
        chapter = chapters.get((record.run_id, record.chapter_id))
        record.actual_input = {
            **actual,
            "chapter_sequence": actual.get("chapter_sequence", chapter.sequence if chapter else record.chapter_id),
        }
        # 仅预测原保存回执将对应的确定性 work 身份，不创建 work、审计或历史事实
        record.work_id = (
            getattr(record, "work_id", None)
            if actual and getattr(record, "invocation_id", None)
            else annotation_work_id(record.run_id, record.chapter_id, "solo")
        )
    operations: dict[str, dict[str, list[dict[str, Any]]]] = {
        record.work_id: {"entity_ops": [], "relation_assert_ops": []} for record in records
    }
    by_chapter = {(record.run_id, record.chapter_id): record for record in records}
    by_entity = {entity.entity_id: entity for entity in entities}
    relations = {row.relation_id: row for row in read("graph_relations")} if "graph_relations" in tables else {}
    for state in read("relation_states") if "relation_states" in tables else []:
        record, relation = by_chapter.get((state.run_id, state.chapter_id)), relations.get(state.relation_id)
        if record is None or relation is None:
            continue
        left, right = by_entity.get(relation.from_entity_id), by_entity.get(relation.to_entity_id)
        if left is None or right is None:
            continue
        operations[record.work_id]["relation_assert_ops"].append(
            {
                "from_entity": left.canonical_name,
                "to_entity": right.canonical_name,
                "relation_type": state.relation_type,
                "change_kind": next(
                    (change["change_kind"] for change in reversed(state.changes) if change.get("change_kind")),
                    "assert" if state.is_active else "break",
                ),
            }
        )
    for record in records:
        exact = [
            deepcopy(fact.value)
            for fact in facts
            if fact.annotation_id == record.annotation_id
            and fact.fact_type == "relation"
            and isinstance(fact.value, dict)
            and {"from_entity", "to_entity", "relation_type"} <= set(fact.value)
        ]
        if exact:
            operations[record.work_id]["relation_assert_ops"] = exact
    candidates = [
        entity
        for entity in entities
        if (entity.attributes or {}).get("canonical_entity_id") not in (None, "", entity.entity_id)
        and (entity.attributes or {}).get("identity_status") != "contested"
    ]
    converted, issues = 0, []
    for entity in candidates:
        try:
            converted += _migrate_identity_decisions(
                entities,
                states,
                records,
                facts,
                operations,
                decision_entity_ids={entity.entity_id},
            )
        except ValueError as error:
            target = by_entity.get(entity.attributes["canonical_entity_id"])
            issues.append(
                {
                    "run_id": entity.run_id,
                    "entity_id": entity.entity_id,
                    "canonical_entity_id": entity.attributes["canonical_entity_id"],
                    "source_entity_type": entity.entity_type,
                    "target_entity_type": target.entity_type if target else None,
                    "reason": str(error),
                }
            )
    return {
        "checked_decisions": len(candidates),
        "convertible_decisions": converted,
        "already_current_decisions": len(candidates) - converted - len(issues),
        "issues": issues,
    }


def _convert_graph(session: Session) -> int:
    """从原存储的实体边界状态、关系和观察迁移，不从案例说明推断业务事实"""
    from copy import deepcopy

    from sqlalchemy import delete

    from src.storage.models import DialogueRecord, EntityState, GraphFact, GraphRelation, RelationState

    entities = list(session.execute(select(GraphEntity)).scalars())
    entity_by_id = {entity.entity_id: entity for entity in entities}
    states = list(session.execute(select(EntityState)).scalars())
    relations = {row.relation_id: row for row in session.execute(select(GraphRelation)).scalars()}
    relation_states = list(session.execute(select(RelationState)).scalars())
    identifiers = {
        entity.entity_id: mention_uuid(entity.run_id, entity.first_seen_chapter, entity.canonical_name)
        for entity in entities
    }

    def remap(value: Any) -> Any:
        # 规范实体身份时同步迁移属性和事实内的实际引用，避免别名仍指向退出的旧实体
        if isinstance(value, dict):
            mapped: dict[str, Any] = {}
            for key, item in value.items():
                if key.endswith("entity_id") and isinstance(item, str):
                    mapped[key] = identifiers.get(item, item)
                elif key.endswith("entity_ids") and isinstance(item, list):
                    mapped[key] = [
                        identifiers.get(entry, entry) if isinstance(entry, str) else remap(entry) for entry in item
                    ]
                else:
                    mapped[key] = remap(item)
            return mapped
        if isinstance(value, list):
            return [remap(item) for item in value]
        return value

    records = _current_annotations(session)
    ops_by_work: dict[str, dict[str, list[dict[str, Any]]]] = {
        record.work_id: {"entity_ops": [], "relation_assert_ops": []} for record in records
    }
    record_by_chapter = {(record.run_id, record.chapter_id): record for record in records}
    for entity in entities:
        supported_states: list[Any] = [state for state in states if state.entity_id == entity.entity_id]
        if not supported_states:
            supported_states = [
                SimpleNamespace(chapter_id=entity.first_seen_chapter, state={"attributes": entity.attributes})
            ]
        for state in supported_states:
            record = record_by_chapter.get((entity.run_id, state.chapter_id))
            if record is None:
                continue
            attributes = remap(dict(state.state.get("attributes", state.state)))
            attributes.pop("entity_type", None)
            ops_by_work[record.work_id]["entity_ops"].append(
                {
                    "name": entity.canonical_name,
                    "entity_type": entity.entity_type,
                    "tags": state.state.get("tags", entity.tags),
                    "description": attributes.get("description"),
                    "attributes": attributes,
                    "chapter_id": state.chapter_id,
                }
            )
    for relation_state in relation_states:
        relation = relations[relation_state.relation_id]
        record = record_by_chapter.get((relation_state.run_id, relation_state.chapter_id))
        if record is None:
            continue
        left, right = entity_by_id[relation.from_entity_id], entity_by_id[relation.to_entity_id]
        ops_by_work[record.work_id]["relation_assert_ops"].append(
            {
                "from_entity": left.canonical_name,
                "to_entity": right.canonical_name,
                "relation_type": relation_state.relation_type,
                "chapter_id": relation_state.chapter_id,
                "change_kind": "assert" if relation_state.is_active else "break",
            }
        )
    original_facts = list(session.execute(select(GraphFact).order_by(GraphFact.graph_fact_id)).scalars())
    # 事件和身份事实仍有查询消费者，按原记录迁移，不改写成关系推断
    retained_facts = [
        {column.name: deepcopy(getattr(fact, column.name)) for column in GraphFact.__table__.columns}
        for fact in original_facts
        if fact.fact_type not in {"entity", "relation", "character_observation", "entity_reference"}
    ]
    for record in records:
        own = [fact for fact in original_facts if fact.annotation_id == record.annotation_id]
        for kind, field in (("entity", "entity_ops"), ("relation", "relation_assert_ops")):
            exact = [
                remap(deepcopy(fact.value))
                for fact in own
                if fact.fact_type == kind
                and isinstance(fact.value, dict)
                and (
                    "name" in fact.value
                    if kind == "entity"
                    else {"from_entity", "to_entity", "relation_type"} <= set(fact.value)
                )
            ]
            if exact:
                ops_by_work[record.work_id][field] = exact
    converted_identities = _migrate_identity_decisions(entities, states, records, original_facts, ops_by_work)
    # 原图和状态已完整备份，重建当前事实来源时不删除原文、审计、用量或有效事件节点
    for model in (GraphFact, EntityState, RelationState, GraphRelation):
        session.execute(delete(model))
    session.flush()
    for entity in entities:
        identifier = identifiers[entity.entity_id]
        if session.get(GraphEntity, identifier) is None:
            session.add(
                GraphEntity(
                    entity_id=identifier,
                    run_id=entity.run_id,
                    canonical_name=entity.canonical_name,
                    entity_type=entity.entity_type,
                    tags=entity.tags,
                    attributes=remap(entity.attributes),
                    first_seen_chapter=entity.first_seen_chapter,
                    last_seen_chapter=entity.last_seen_chapter,
                    created_at=entity.created_at,
                    updated_at=entity.updated_at,
                )
            )
    session.flush()
    for row in session.execute(select(DialogueRecord)).scalars():
        if row.speaker is not None:
            row.speaker = identifiers.get(row.speaker, row.speaker)
    for node in session.execute(select(EventNode)).scalars():
        values = deepcopy(node.participants)
        for participant in values:
            descriptor = participant.get("entity")
            if isinstance(descriptor, dict):
                participant_id = descriptor.get("entity_id")
                if isinstance(participant_id, str):
                    descriptor["entity_id"] = identifiers.get(participant_id, participant_id)
        node.participants = values
    session.flush()
    session.execute(delete(GraphEntity).where(GraphEntity.entity_id.not_in(set(identifiers.values()))))
    session.flush()
    for record in sorted(records, key=lambda value: (value.run_id, value.actual_input["chapter_sequence"])):
        operations = ops_by_work[record.work_id]
        output = record.payload
        names = {op["name"] for op in operations["entity_ops"]}
        for op in operations["relation_assert_ops"]:
            names.update((op["from_entity"], op["to_entity"]))
        names.update(item["character"] for item in output["character_observations"])
        names.update(item["speaker"] for item in output["dialogues"] if item["speaker"])
        for event in output["events"]:
            names.update(item["entity"] for item in event["participants"])
        descriptors = {}
        for name in names:
            matched_entity = next(
                (value for value in entities if value.run_id == record.run_id and value.canonical_name == name), None
            )
            if matched_entity is None:
                raise ValueError(f"迁移实体事实缺少原记录: {name}")
            descriptors[mention_uuid(record.run_id, record.chapter_id, name)] = {
                "entity_id": mention_uuid(record.run_id, record.chapter_id, name),
                "name": name,
                "entity_type": matched_entity.entity_type,
            }
        contribution = FactContribution(
            run_id=record.run_id,
            work_id=record.work_id,
            invocation_id=record.invocation_id,
            chapter_id=record.chapter_id,
            paragraphs=tuple(EvidenceParagraph(**row) for row in record.actual_input["paragraphs"]),
            snapshot_json=json.dumps({**operations, "entities": descriptors}, ensure_ascii=False),
            observations_json=json.dumps(output["character_observations"], ensure_ascii=False),
        )
        FactGraph(run_scope=record.run_id).save_work(session, contribution, record.annotation_id)
    for run_id in {record.run_id for record in records}:
        # 重算事件结构时保留已保存的伏笔状态
        roots = list(
            session.execute(
                select(EventNode).where(EventNode.run_id == run_id, EventNode.is_foreshadowing_root.is_(True))
            ).scalars()
        )
        statuses = {node.event_id: node.foreshadowing_status for node in roots}
        EventTrees(run_id).rebuild_storage(session)
        for node in roots:
            node.foreshadowing_status = statuses[node.event_id]
        session.flush()

    for content in retained_facts:
        session.add(GraphFact(**remap(content)))
    session.flush()
    return converted_identities


def _migrate(
    engine: Engine, *, apply: bool = False, schema: str = "public", expect_database: str | None = None
) -> dict[str, Any]:
    """先预检后转换；所有 DDL 与业务变换共用事务，重复执行不重复写入"""
    _identifier(schema)
    _load_release_models()
    if apply and (not expect_database or engine.url.database != expect_database):
        raise ValueError("--apply 必须提供匹配的 --expect-database")
    with engine.begin() as connection:
        if not apply:
            connection.execute(text("SET TRANSACTION READ ONLY"))
        connection.execute(text(f"SET LOCAL search_path TO {_identifier(schema)}"))
        if connection.execute(text("SELECT current_schema()")).scalar_one_or_none() != schema:
            raise ValueError(f"目标 schema 不存在: {schema}")
        connection.execute(text("SET LOCAL statement_timeout='60s'"))
        connection.execute(text("SET LOCAL lock_timeout='5s'"))
        connection.execute(text("SET LOCAL TIME ZONE 'UTC'"))
        if apply:
            if not connection.execute(
                text("SELECT pg_try_advisory_xact_lock(hashtextextended(:key,0))"),
                {"key": f"release:{engine.url.database}:{schema}:{VERSION}"},
            ).scalar_one():
                raise ValueError("另一迁移进程正在执行")
        plan = migration_plan(connection)
        if not apply or plan["already_migrated"]:
            return {**plan, "applied": False}
        if plan["blocking_issues"]:
            raise ValueError(json.dumps({"blocking_issues": plan["blocking_issues"]}, ensure_ascii=False))
        tables = inspect(connection).get_table_names(schema=schema)
        connection.execute(
            text("LOCK TABLE " + ", ".join(_identifier(name) for name in tables) + " IN SHARE ROW EXCLUSIVE MODE")
        )
        plan = migration_plan(connection)
        if plan["blocking_issues"]:
            raise ValueError(json.dumps({"blocking_issues": plan["blocking_issues"]}, ensure_ascii=False))
        if plan.get("merge_only"):
            chapters = cases = identities = 0
            merged = _merge_turn_outputs(connection)
        else:
            _prepare_role_schema(connection, plan)
            _align_timestamps(connection, schema)
            with Session(bind=connection) as session:
                chapters = _convert_outputs(session)
                session.flush()
                merged = _merge_turn_outputs(connection)
                session.expire_all()
                identities = _convert_graph(session) if chapters else 0
                cases = _convert_cases(session)
                session.flush()
        for table, columns in {
            "analysis_runs": ("cancellation_epoch", "annotation_cutoff_hash"),
            "event_outbox": ("cutoff_hash",),
        }.items():
            existing = {column["name"] for column in inspect(connection).get_columns(table, schema=schema)}
            for column in set(columns) & existing:
                connection.execute(text(f"ALTER TABLE {_identifier(table)} DROP COLUMN {_identifier(column)}"))
        # 转换已在原 schema 就地完成，退出旧流水线表连数据一并退役
        connection.execute(
            text("DROP TABLE IF EXISTS " + ", ".join(_identifier(name) for name in sorted(RETIRED)) + " CASCADE")
        )
        result = inspect_current_schema(connection, schema=schema)
        if not result["ready"]:
            raise ValueError(json.dumps({"target_schema_errors": result}, ensure_ascii=False))
        report = {
            **plan,
            "applied": True,
            "converted_chapters": chapters,
            "converted_cases": cases,
            "converted_identity_decisions": identities,
            "merged_outputs": merged,
            "target_schema": result,
        }
        connection.execute(
            text(
                "CREATE TABLE IF NOT EXISTS noveliq_release_migrations (version text PRIMARY KEY, "
                "applied_at timestamptz NOT NULL DEFAULT now(), report jsonb NOT NULL)"
            )
        )
        connection.execute(
            text("INSERT INTO noveliq_release_migrations (version,report) VALUES (:version,CAST(:report AS jsonb))"),
            {"version": VERSION, "report": json.dumps(report, ensure_ascii=False)},
        )
        return report


def migrate(
    *, database_env: DatabaseEnvironmentName, schema: str, apply: bool, expect_database: str | None
) -> dict[str, Any]:
    """读取项目数据库配置并执行只读预检或单事务迁移"""
    _identifier(schema)
    if apply and not expect_database:
        raise ValueError("--apply 必须同时指定 --expect-database")
    url = make_url(resolve_database_url_from_env(database_env))
    if url.get_backend_name() != "postgresql" or not url.database:
        raise ValueError("迁移脚本只支持已存在的 PostgreSQL 数据库")
    if expect_database and url.database != expect_database:
        raise ValueError("目标数据库名称与 --expect-database 不一致")
    engine = create_engine(url, connect_args={"connect_timeout": 5})
    try:
        return _migrate(engine, apply=apply, schema=schema, expect_database=expect_database)
    finally:
        engine.dispose()


def main() -> int:
    """解析统一入口参数并输出迁移报告"""
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database-env", choices=("DATABASE", "TEST_DATABASE"), default="DATABASE")
    parser.add_argument("--schema", help="业务 schema，默认读取对应的 *_SCHEMA 或使用 public")
    parser.add_argument("--apply", action="store_true", help="实际迁移；默认只读预检")
    parser.add_argument("--expect-database", help="执行时必须明确匹配的数据库名")
    args = parser.parse_args()
    load_dotenv(Path(__file__).resolve().parents[2] / ".env")
    try:
        report = migrate(
            database_env=cast(DatabaseEnvironmentName, args.database_env),
            schema=args.schema or os.environ.get(args.database_env + "_SCHEMA", "public"),
            apply=args.apply,
            expect_database=args.expect_database,
        )
    except (OSError, RuntimeError, ValueError, SQLAlchemyError) as error:
        print(json.dumps({"version": VERSION, "error": str(error)}, ensure_ascii=False, indent=2))
        return 2
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 2 if report["blocking_issues"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
