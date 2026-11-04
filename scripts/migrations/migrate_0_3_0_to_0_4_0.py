"""单文件发布迁移入口，复用项目 ORM 与配置，默认只读预检"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from collections import Counter, defaultdict
from collections.abc import Iterator, Mapping
from pathlib import Path
from typing import Any, Literal, cast

from dotenv import load_dotenv
from sqlalchemy import MetaData, UniqueConstraint, create_engine, inspect, text
from sqlalchemy.engine import Connection, Engine, make_url
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.pool import NullPool

_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from src.config.project_version import project_version  # noqa: E402
from src.storage.constraints import domain_constraint_statements  # noqa: E402
from src.storage.database_url import resolve_database_url_from_env  # noqa: E402
from src.storage.models import Base  # noqa: E402

DatabaseEnvironmentName = Literal["DATABASE", "TEST_DATABASE"]

_SOURCE_TABLES: dict[str, tuple[str, tuple[str, ...], tuple[str, ...]]] = {
    "novels": (
        "novel_id:uuid!|filename:varchar(500)|file_path:text|title:varchar(500)|author:varchar(255)|"
        "file_size:bigint|upload_time:timestamp without time zone",
        ("novel_id",),
        (),
    ),
    "runs": (
        "id:uuid!|novelid:uuid!|taskid:varchar(8)!|status:varchar(50)!|lda_completed:boolean!|w2v_completed:boolean!",
        ("id",),
        ("novelid->novels.novel_id",),
    ),
    "agent": (
        "id:uuid!|run_id:uuid!|type:varchar(20)!|status:varchar(20)!",
        ("id",),
        ("run_id->runs.id",),
    ),
    "agent_outbox": (
        "message_key:varchar(255)!|event_id:uuid!|stream_id:bigint!|run_id:uuid!|chapter_id:integer|"
        "event_type:varchar(60)!|emitted_bytes:bytea!|created_at:timestamp without time zone!|"
        "published_at:timestamp without time zone",
        ("event_id",),
        ("run_id->runs.id",),
    ),
    "chapters": (
        "id:uuid!|run_id:uuid!|chapter_id:integer!|sequence:integer!|title:text!|display_title:text!|"
        "display_index_label:varchar(64)|level:varchar(20)!|start_pos:integer!|end_pos:integer!|text:text|"
        "char_offset:integer",
        ("id",),
        ("run_id->runs.id",),
    ),
    "global_stats": (
        "run_id:uuid!|avg_mtld:double precision|avg_ttr:double precision|"
        "avg_sent_len:double precision|emotion_avg:double precision|"
        "lexicon_zero_hit_share:double precision|emotion_std:double precision|"
        "emotion_max:double precision|emotion_min:double precision|"
        "emotion_peak_chapter_id:integer|emotion_min_chapter_id:integer|"
        "rhythm_avg:double precision|rhythm_std:double precision|"
        "rhythm_max:double precision|rhythm_min:double precision|"
        "rhythm_peak_chapter_id:integer|rhythm_min_chapter_id:integer",
        ("run_id",),
        ("run_id->runs.id",),
    ),
    "graph_entities": (
        "entity_id:uuid!|run_id:uuid!|canonical_name:varchar(255)!|entity_type:varchar(50)!|"
        "created_at:timestamp without time zone!|updated_at:timestamp without time zone!",
        ("entity_id",),
        ("run_id->runs.id",),
    ),
    "agent_annotations": (
        "record_id:uuid!|agent_id:uuid!|run_id:uuid!|chapter_id:integer!|role:varchar(20)!|"
        "consolidation_digest:text|summary:varchar|emotional_valence:integer|narrative_function:varchar(50)|"
        "pivot_moment:boolean|cliffhanger:boolean|created_at:timestamp without time zone!|"
        "saved_at:timestamp without time zone!",
        ("record_id",),
        ("run_id,chapter_id->chapters.run_id,chapter_id", "run_id->runs.id", "agent_id->agent.id"),
    ),
    "agent_loop": (
        "id:uuid!|model:varchar(100)!|error:text|started_at:timestamp without time zone!|"
        "finished_at:timestamp without time zone|message_key:varchar(128)|agent_id:uuid|turn_index:integer|"
        "standalone_run_id:uuid|standalone_chapter_id:integer|standalone_task_type:varchar(100)|"
        "standalone_call_type:varchar(50)|prompt_tokens:integer|completion_tokens:integer|"
        "cache_read_tokens:integer|reasoning_tokens:integer|accounting_source:varchar(20)|"
        "reported_total_tokens:integer|cost:double precision|ttft_ms:integer|first_visible_ms:integer|"
        "reasoning_ms:integer|model_ms:integer|tool_wall_ms:integer|request_messages_bytes:bytea|"
        "raw_response_bytes:bytea|context_observed_bytes:bytea|timing_notes_bytes:bytea",
        ("id",),
        ("standalone_run_id->runs.id", "agent_id->agent.id"),
    ),
    "case": (
        "id:uuid!|run_id:uuid!|type:varchar(20)!|description:text!|status:varchar(20)!|"
        "producer_agent_id:uuid|promised_agent_id:uuid",
        ("id",),
        ("producer_agent_id->agent.id", "promised_agent_id->agent.id", "run_id->runs.id"),
    ),
    "diagnosis_reports": (
        "report_id:uuid!|agent_id:uuid!|diagnosis:text|value_logic_type:varchar(50)|"
        "value_logic_reason:text|power_stance_score:integer|power_stance_reason:text|"
        "common_people_dignity:integer|dignity_reason:text|cultural_depth_score:integer|"
        "cultural_depth_reason:text|narrative_arc_type:varchar(10)|focus_structure:varchar(20)|"
        "theme_color:varchar(16)|content_snapshot:text|structure_snapshot:text|"
        "created_at:timestamp without time zone!",
        ("report_id",),
        ("agent_id->agent.id",),
    ),
    "event_groups": (
        "group_id:uuid!|producer_agent_id:uuid!|title:varchar!|arc_kind:varchar(16)|arc_objective:varchar|"
        "arc_role:varchar|arc_reason:varchar|parent_arc_id:uuid|outcome_description:varchar",
        ("group_id",),
        ("parent_arc_id->event_groups.group_id", "producer_agent_id->agent.id"),
    ),
    "graph_relations": (
        "relation_id:uuid!|from_entity_id:uuid!|to_entity_id:uuid!|relation_type:varchar(100)!|"
        "created_at:timestamp without time zone!",
        ("relation_id",),
        ("to_entity_id->graph_entities.entity_id", "from_entity_id->graph_entities.entity_id"),
    ),
    "paragraphs": (
        "id:uuid!|run_id:uuid!|paragraph_id:integer!|chapter_id:integer!|paragraph_index:integer!|"
        "source_paragraph_index:integer!|fragment_index:integer!|local_start_char:integer!|text:text!|"
        "created_at:timestamp without time zone!",
        ("id",),
        ("chapter_id,run_id->chapters.chapter_id,run_id", "run_id->runs.id"),
    ),
    "agent_assessments": (
        "assessment_id:uuid!|record_id:uuid|report_id:uuid|paragraph_id:integer|emotion:integer|"
        "ordinal:integer|genre_label:varchar(100)|style_label:varchar(100)|topic_id:integer|"
        "topic_label:varchar(100)|scored_entity_id:uuid|character_score:double precision|cast_role:varchar(20)|"
        "cast_entity_id:uuid",
        ("assessment_id",),
        (
            "report_id->diagnosis_reports.report_id",
            "record_id->agent_annotations.record_id",
            "cast_entity_id->graph_entities.entity_id",
            "scored_entity_id->graph_entities.entity_id",
        ),
    ),
    "agent_toolcall": (
        "id:uuid!|agentloop_id:uuid!|tool_name:varchar(100)!|call_index:integer!|error:text|"
        "started_at:timestamp without time zone!|tool_duration_ms:integer|message_key:varchar(128)|"
        "raw_args_bytes:bytea|executed_args_bytes:bytea|response_observed_bytes:bytea|"
        "receipt_observed_bytes:bytea",
        ("id",),
        ("agentloop_id->agent_loop.id",),
    ),
    "event_records": (
        "event_id:uuid!|producer_agent_id:uuid!|local_key:varchar(255)!|annotation_record_id:uuid|"
        "from:integer!|to:integer!|reason:varchar|is_foreshadowing_root:boolean!|"
        "payoff_likelihood:varchar(20)|created_at:timestamp without time zone!|title:varchar!|"
        "problem:varchar!|summary:varchar!|event_type:varchar!|status:varchar(16)!|progress:varchar",
        ("event_id",),
        ("producer_agent_id->agent.id", "annotation_record_id->agent_annotations.record_id"),
    ),
    "lda_paragraph_topics": (
        "id:uuid!|run_id:uuid!|paragraph_id:integer!|topic_id:integer!|topic_weight:double precision!",
        ("id",),
        ("run_id,paragraph_id->paragraphs.run_id,paragraph_id",),
    ),
    "paragraph_features": (
        "id:uuid!|run_id:uuid!|paragraph_id:integer!|feature_code:varchar(64)!|vector_value:vector|"
        "scalar_value:double precision|count_value:integer|in_vocabulary_token_count:integer|"
        "created_at:timestamp without time zone!",
        ("id",),
        ("run_id,paragraph_id->paragraphs.run_id,paragraph_id",),
    ),
    "paragraph_metrics": (
        "id:uuid!|run_id:uuid!|paragraph_id:integer!|token_count:integer|sentence_count:integer|"
        "sentence_char_sum:double precision|sentence_char_sum_sq:double precision|"
        "positive_weight_sum:double precision|negative_weight_sum:double precision|"
        "fight_weight_sum:double precision|exclaim_count:integer|question_count:integer|"
        "pause_count:integer|dialogue_char_count:integer|sensory_hit_count:integer|"
        "imagery_hit_count:integer|metaphor_sentence_count:integer|body_reaction_hit_count:integer|"
        "metrics_created_at:timestamp without time zone|preprocess_observed_at:timestamp without time zone|"
        "linguistic_completed_at:timestamp without time zone|phrase_completed_at:timestamp without time zone|"
        "fw_之:integer|fw_其:integer|fw_者:integer|fw_也:integer|fw_所:integer|fw_以:integer|fw_而:integer|"
        "fw_与:integer|fw_则:integer|fw_乃:integer|fw_于:integer|fw_乎:integer|fw_矣:integer|fw_焉:integer|"
        "fw_哉:integer|fw_兮:integer|fw_尔:integer|fw_若:integer|fw_为:integer|fw_何:integer|"
        "semantic_combat:integer|semantic_body:integer|semantic_relation:integer|semantic_faction:integer|"
        "semantic_command:integer|semantic_action:integer|semantic_psychology:integer|"
        "semantic_measure:integer|semantic_emotion:integer|semantic_color:integer|"
        "boundary_pos_score_sum:double precision|boundary_neg_score_sum:double precision|inference_token_count:integer|"
        "inference_status:varchar(30)|inference_error_text:text|inference_created_at:timestamp without time zone",
        ("id",),
        ("run_id,paragraph_id->paragraphs.run_id,paragraph_id", "run_id->runs.id"),
    ),
    "paragraph_spans": (
        "span_id:uuid!|run_id:uuid!|paragraph_id:integer!|start_char:integer!|end_char:integer!|"
        "token_index:integer|raw_pos:varchar(50)|raw_entity_type:varchar(50)|phrase_match_kind:varchar(30)|"
        "created_at:timestamp without time zone!",
        ("span_id",),
        ("run_id,paragraph_id->paragraphs.run_id,paragraph_id",),
    ),
    "event_checks": (
        "check_id:uuid!|producer_agent_id:uuid!|reason:varchar!|reviewed_event_id:uuid|source_event_id:uuid|"
        "target_event_id:uuid|snapshot_hash:varchar(128)|disposition:varchar(50)",
        ("check_id",),
        (
            "target_event_id->event_records.event_id",
            "source_event_id->event_records.event_id",
            "reviewed_event_id->event_records.event_id",
            "producer_agent_id->agent.id",
        ),
    ),
    "event_foreshadowing_actions": (
        "action_id:uuid!|producer_agent_id:uuid!|source_operation_local_key:varchar(128)!|"
        "operation_order:integer!|action_type:varchar(16)!|source_event_id:uuid!|target_event_id:uuid",
        ("action_id",),
        (
            "target_event_id->event_records.event_id",
            "source_event_id->event_records.event_id",
            "producer_agent_id->agent.id",
        ),
    ),
    "event_links": (
        "link_id:uuid!|producer_agent_id:uuid!|reason:varchar!|semantic_source_event_id:uuid|"
        "semantic_target_event_id:uuid|relation_type:varchar(100)|source_operation_local_key:varchar(255)|"
        "annotation_local_key:varchar(255)|created_at:timestamp without time zone|is_active:boolean|"
        "expired_at:timestamp without time zone|cause_role:varchar(16)|contained_child_id:uuid|"
        "contained_parent_id:uuid|member_event_id:uuid|arc_group_id:uuid|outcome_group_id:uuid|"
        "arc_role:varchar(50)",
        ("link_id",),
        (
            "semantic_target_event_id->event_records.event_id",
            "producer_agent_id->agent.id",
            "outcome_group_id->event_groups.group_id",
            "member_event_id->event_records.event_id",
            "contained_child_id->event_records.event_id",
            "semantic_source_event_id->event_records.event_id",
            "arc_group_id->event_groups.group_id",
            "contained_parent_id->event_records.event_id",
        ),
    ),
    "event_participants": (
        "participant_id:uuid!|event_id:uuid!|participant_ordinal:integer!|entity_id:uuid!|role:varchar(50)!|"
        "narrative_role:varchar(50)|action:varchar(255)|emotion:integer",
        ("participant_id",),
        ("entity_id->graph_entities.entity_id", "event_id->event_records.event_id"),
    ),
    "graph_dialogues": (
        "dialogue_id:uuid!|run_id:uuid!|chapter_id:integer!|creation_agent_id:uuid!|"
        "candidate_key:varchar(100)!|start_char:integer!|end_char:integer!|"
        "current_attribution_agent_id:uuid|speaker_entity_id:uuid|tone:varchar(255)|"
        "is_inner_monologue:boolean!|related_complete_event_id:uuid|created_at:timestamp without time zone!|"
        "updated_at:timestamp without time zone!",
        ("dialogue_id",),
        (
            "creation_agent_id->agent.id",
            "related_complete_event_id->event_records.event_id",
            "current_attribution_agent_id->agent.id",
            "run_id,chapter_id->chapters.run_id,chapter_id",
            "speaker_entity_id->graph_entities.entity_id",
        ),
    ),
    "paragraph_arcs": (
        "arc_id:uuid!|dependent_span_id:uuid!|head_span_id:uuid|relation_code:varchar(50)!|source_ordinal:integer!",
        ("arc_id",),
        ("head_span_id->paragraph_spans.span_id", "dependent_span_id->paragraph_spans.span_id"),
    ),
    "graph_facts": (
        "graph_fact_id:uuid!|direct_producer_agent_id:uuid|operation_order:integer|business_call_id:text|"
        "effective_chapter_id:integer|entity_id:uuid|relation_id:uuid|participant_id:uuid|event_id:uuid|"
        "description_action:varchar(10)|description_value:text|representative_action:varchar(10)|"
        "representative_value:boolean|tags_submitted:boolean|relation_change_kind:varchar(20)|"
        "identity_kind:varchar(20)|reason:text|plotline_subject_id:varchar(255)|"
        "plotline_subject_title:varchar(255)|plotline_description:text|plotline_before:text|"
        "plotline_after:text|created_at:timestamp without time zone!",
        ("graph_fact_id",),
        (
            "event_id->event_records.event_id",
            "relation_id->graph_relations.relation_id",
            "direct_producer_agent_id->agent.id",
            "participant_id->event_participants.participant_id",
            "entity_id->graph_entities.entity_id",
        ),
    ),
    "graph_fact_entity_tags": (
        "id:uuid!|graph_fact_id:uuid!|tag_ordinal:integer!|tag:varchar(100)!",
        ("id",),
        ("graph_fact_id->graph_facts.graph_fact_id",),
    ),
    "paragraph_evidence": (
        "evidence_id:uuid!|ordinal:integer!|paragraph_id:integer!|start_char:integer!|end_char:integer!|"
        "related_complete_event_id:uuid|graph_fact_id:uuid|complete_event_id:uuid|narrative_group_id:uuid|"
        "narrative_link_id:uuid|foreshadow_action_id:uuid|check_id:uuid",
        ("evidence_id",),
        (
            "narrative_group_id->event_groups.group_id",
            "foreshadow_action_id->event_foreshadowing_actions.action_id",
            "graph_fact_id->graph_facts.graph_fact_id",
            "narrative_link_id->event_links.link_id",
            "complete_event_id->event_records.event_id",
            "check_id->event_checks.check_id",
            "related_complete_event_id->event_records.event_id",
        ),
    ),
}

#: 需要逐行转换的表；其余表按源列原样复制
_TRANSFORMED = ("event_groups", "event_links")
#: 新增可空列、复制时置空的表
_CLEARED_COLUMNS: dict[str, tuple[str, ...]] = {
    "novels": ("word_count",),
    "paragraph_spans": ("emotion_polarity", "emotion_negated", "emotion_holder_token_index"),
}

_UNMAPPABLE_REASONS = {
    "containment": "旧包含关系的父/子事件形状在新模型中没有对应列，成员无法挂到事件树",
    "duplicate_member": "同一事件出现在多个旧分组，新模型要求事件唯一归属一棵树",
    "membership_flags": "旧分组成员带着新的单树归属形状不允许的活动或因果标记",
    "unknown_membership": "旧分组成员缺少所属分组",
}


def _quote(value: str) -> str:
    "校验并引用数据库标识符"
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", value) or len(value.encode()) > 63:
        raise ValueError(f"无效的数据库标识符: {value!r}")
    if value.startswith("pg_") or value == "information_schema":
        raise ValueError(f"不能操作系统 schema: {value}")
    return '"' + value + '"'


def _key(*values: Any) -> str:
    return json.dumps(values, ensure_ascii=False, separators=(",", ":"))


def _type_name(column_type: Any, connection: Connection) -> str:
    value = str(column_type.compile(dialect=connection.dialect)).lower()
    return "double precision" if value == "float" else value


def _source_contract() -> dict[str, Any]:
    "展开内置源表的列、主键与外键事实，感叹号表示非空列"
    result = {}
    for name, (column_spec, primary_key, foreign_keys) in _SOURCE_TABLES.items():
        columns = {}
        for specification in column_spec.split("|"):
            column_name, column_type = specification.split(":", 1)
            columns[column_name] = {"type": column_type.removesuffix("!"), "nullable": not column_type.endswith("!")}
        references = []
        for specification in foreign_keys:
            source, target = specification.split("->", 1)
            target_table, target_columns = target.split(".", 1)
            references.append(
                {
                    "source_columns": source.split(","),
                    "target_table": target_table,
                    "target_columns": target_columns.split(","),
                }
            )
        result[name] = {"columns": columns, "primary_key": list(primary_key), "foreign_keys": references}
    return result


def _check_release() -> None:
    "核对迁移入口对应的项目发布版本"
    if project_version() != "0.4.0":
        raise ValueError("此入口只用于项目 0.4.0 发布代码，请使用匹配发布的代码执行")


def _catalog(connection: Connection, schema: str) -> dict[str, int]:
    return {
        row["relname"]: row["oid"]
        for row in connection.execute(
            text(
                "SELECT c.relname,c.oid FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace "
                "WHERE n.nspname=:schema AND c.relkind IN ('r','p') ORDER BY c.relname"
            ),
            {"schema": schema},
        ).mappings()
    }


def _row_counts(connection: Connection, schema: str, tables: Mapping[str, Any]) -> dict[str, int]:
    return {
        name: connection.execute(text(f"SELECT count(*) FROM {_quote(schema)}.{_quote(name)}")).scalar_one()
        for name in sorted(tables)
    }


#: 目标发布才有的列，出现即视为已完成迁移
_TARGET_COLUMNS: dict[str, tuple[str, ...]] = {
    "event_groups": ("kind", "description", "is_event_line", "line_name", "tree_key"),
    "event_links": ("tree_id", "position", "parent_tree_id", "child_tree_id"),
    "novels": ("word_count",),
    "paragraph_spans": ("emotion_polarity", "emotion_negated", "emotion_holder_token_index"),
}


def _already_migrated(connection: Connection, schema: str) -> bool:
    "按目标发布新增列判断是否已是 0.4.0 结构"
    inspector = inspect(connection)
    if set(inspector.get_table_names(schema=schema)) != set(Base.metadata.tables):
        return False
    for name, required in _TARGET_COLUMNS.items():
        present = {column["name"] for column in inspector.get_columns(name, schema=schema)}
        if not set(required) <= present:
            return False
    return True


def _check_source(connection: Connection, schema: str, source_contract: dict[str, Any]) -> list[str]:
    inspector = inspect(connection)
    existing = set(inspector.get_table_names(schema=schema))
    expected = set(source_contract)
    problems = []
    if expected - existing:
        problems.append(f"缺少源表: {sorted(expected - existing)}")
    unexpected = existing - expected - {"noveliq_release_migrations"}
    if unexpected:
        problems.append(f"存在不属于源发布的表: {sorted(unexpected)}")
    if inspector.get_view_names(schema=schema) or inspector.get_materialized_view_names(schema=schema):
        problems.append("源 schema 存在视图，不能自动改写其表绑定")
    foreign_keys: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in connection.execute(
        text(
            "SELECT source.relname AS source_table,target.relname AS target_table,"
            "target_ns.nspname AS target_schema,"
            "ARRAY(SELECT a.attname FROM unnest(c.conkey) WITH ORDINALITY k(num,ord) "
            "JOIN pg_attribute a ON a.attrelid=c.conrelid AND a.attnum=k.num ORDER BY k.ord) AS source_columns,"
            "ARRAY(SELECT a.attname FROM unnest(c.confkey) WITH ORDINALITY k(num,ord) "
            "JOIN pg_attribute a ON a.attrelid=c.confrelid AND a.attnum=k.num ORDER BY k.ord) AS target_columns "
            "FROM pg_constraint c JOIN pg_class source ON source.oid=c.conrelid "
            "JOIN pg_namespace source_ns ON source_ns.oid=source.relnamespace "
            "JOIN pg_class target ON target.oid=c.confrelid "
            "JOIN pg_namespace target_ns ON target_ns.oid=target.relnamespace "
            "WHERE c.contype='f' AND source_ns.nspname=:schema"
        ),
        {"schema": schema},
    ).mappings():
        if row["target_schema"] != schema:
            problems.append(f"{row['source_table']}: 外键指向业务 schema 以外的 {row['target_schema']}")
        foreign_keys[row["source_table"]].append(
            {key: row[key] for key in ("source_columns", "target_table", "target_columns")}
        )
    for name, contract in source_contract.items():
        if name not in existing:
            continue
        columns = {
            column["name"]: {"type": _type_name(column["type"], connection), "nullable": column["nullable"]}
            for column in inspector.get_columns(name, schema=schema)
        }
        if columns != contract["columns"]:
            problems.append(f"{name}: 字段、类型或可空性与源发布不符")
        if inspector.get_pk_constraint(name, schema=schema)["constrained_columns"] != contract["primary_key"]:
            problems.append(f"{name}: 主键与源发布不符")
        if sorted(foreign_keys[name], key=_key) != sorted(contract["foreign_keys"], key=_key):
            problems.append(f"{name}: 外键字段或实际目标与源发布不符")
    return problems


class _Sink:
    "按相同转换路径预检或分批写入目标表"

    def __init__(self, connection: Connection, schema: str, *, apply: bool) -> None:
        self.connection = connection
        self.apply = apply
        self.tables = MetaData()
        for table in Base.metadata.sorted_tables:
            table.to_metadata(self.tables, schema=schema)
        self.by_name = {table.name: table for table in self.tables.tables.values()}
        self.ordered_tables = self.tables.sorted_tables
        self.counts: Counter[str] = Counter()
        self.pending: dict[str, list[dict[str, Any]]] = defaultdict(list)
        self.unique_keys: dict[tuple[str, tuple[str, ...]], set[tuple[Any, ...]]] = defaultdict(set)

    def add(self, name: str, values: dict[str, Any]) -> None:
        table = self.by_name[name]
        row = {column.name: values.get(column.name) for column in table.columns}
        for column in table.columns:
            value = row[column.name]
            if value is None and not column.nullable and column.identity is None:
                raise ValueError(f"{name}.{column.name}: 源记录缺少必填值")
            length = getattr(column.type, "length", None)
            if length and isinstance(value, str) and len(value) > length:
                raise ValueError(f"{name}.{column.name}: 长度 {len(value)} 超过 {length}")
        unique = [tuple(column.name for column in table.primary_key)]
        unique.extend(
            tuple(column.name for column in constraint.columns)
            for constraint in table.constraints
            if isinstance(constraint, UniqueConstraint)
        )
        for columns in unique:
            key = tuple(row[column] for column in columns)
            if any(value is None for value in key):
                continue
            seen = self.unique_keys[(name, columns)]
            if key in seen:
                raise ValueError(f"{name}: 转换后业务键冲突 {columns}={key!r}")
            seen.add(key)
        self.counts[name] += 1
        if self.apply:
            self.pending[name].append(row)
            if len(self.pending[name]) >= 500:
                self.flush(name)

    def flush(self, name: str | None = None) -> None:
        for table in self.ordered_tables:
            rows = self.pending[table.name]
            if rows:
                self.connection.execute(table.insert(), rows)
                rows.clear()
            if table.name == name:
                break


class _Conversion:
    "把源记录复制到新结构，组织形状按事件树/结果组转换"

    def __init__(self, connection: Connection, source: str, target: str, *, apply: bool, drop_unmappable: bool) -> None:
        self.connection = connection
        self.source = source
        self.target = target
        self.apply = apply
        self.drop_unmappable = drop_unmappable
        self.sink = _Sink(connection, target, apply=apply)
        self.dropped: Counter[str] = Counter()
        self.dropped_by_table: Counter[str] = Counter()
        self.samples: list[dict[str, Any]] = []
        self.issues: list[str] = []
        self.members: dict[str, str] = {}

    def rows(self, table: str, *, order: str = "") -> Iterator[dict[str, Any]]:
        query = f"SELECT * FROM {_quote(self.source)}.{_quote(table)}"
        if order:
            query += " ORDER BY " + order
        result = self.connection.execute(text(query)).mappings()
        while batch := result.fetchmany(500):
            for row in batch:
                yield dict(row)

    def drop(self, table: str, row: Mapping[str, Any], reason: str) -> None:
        "记录无法映射的行；未显式允许丢弃时登记为阻断项"
        self.dropped[reason] += 1
        self.dropped_by_table[table] += 1
        if len(self.samples) < 100:
            identity = {key: str(row[key]) for key in ("link_id", "group_id", "run_id") if key in row}
            self.samples.append({"table": table, "identity": identity, "reason": reason})
        if not self.drop_unmappable:
            message = f"{table}: {_UNMAPPABLE_REASONS[reason]}"
            if message not in self.issues:
                self.issues.append(message)

    def copy(self, name: str) -> None:
        target = self.sink.by_name[name]
        cleared = _CLEARED_COLUMNS.get(name, ())
        for row in self.rows(name):
            values = {column.name: row.get(column.name) for column in target.columns if column.name not in cleared}
            self.sink.add(name, values)

    def groups(self) -> None:
        "旧叙事线转为事件树、旧结果组转为结果组；事件线名称不可推导，保持普通树"
        for row in self.rows("event_groups"):
            arc = row["arc_kind"] is not None
            if arc == (row["outcome_description"] is not None):
                raise ValueError(f"event_groups {row['group_id']}: 源行形状不符合弧线或结果组")
            self.sink.add(
                "event_groups",
                {
                    "group_id": row["group_id"],
                    "producer_agent_id": row["producer_agent_id"],
                    "title": row["title"],
                    "kind": "tree" if arc else "outcome",
                    "description": row["arc_objective"] if arc else row["outcome_description"],
                    "is_event_line": False,
                    "line_name": None,
                    "tree_key": None,
                },
            )

    def links(self) -> None:
        "语义关系原样保留；分组成员改挂树的连续位置；包含关系无对应形状"
        positions: Counter[str] = Counter()
        for row in self.rows("event_links", order="created_at NULLS LAST, link_id"):
            values = {
                "link_id": row["link_id"],
                "producer_agent_id": row["producer_agent_id"],
                "reason": row["reason"],
                "semantic_source_event_id": None,
                "semantic_target_event_id": None,
                "relation_type": None,
                "source_operation_local_key": None,
                "annotation_local_key": row["annotation_local_key"],
                "created_at": row["created_at"],
                "is_active": None,
                "expired_at": None,
                "cause_role": None,
                "tree_id": None,
                "position": None,
                "member_event_id": None,
                "parent_tree_id": None,
                "child_tree_id": None,
            }
            if row["semantic_source_event_id"] is not None:
                values.update(
                    {
                        "semantic_source_event_id": row["semantic_source_event_id"],
                        "semantic_target_event_id": row["semantic_target_event_id"],
                        "relation_type": row["relation_type"],
                        "source_operation_local_key": row["source_operation_local_key"],
                        "is_active": row["is_active"],
                        "expired_at": row["expired_at"],
                        "cause_role": row["cause_role"],
                    }
                )
                self.sink.add("event_links", values)
                continue
            if row["contained_child_id"] is not None:
                self.drop("event_links", row, "containment")
                continue
            member = row["member_event_id"]
            group = row["arc_group_id"] or row["outcome_group_id"]
            if member is None or group is None or (row["arc_group_id"] and row["outcome_group_id"]):
                self.drop("event_links", row, "unknown_membership")
                continue
            if member in self.members:
                self.drop("event_links", row, "duplicate_member")
                continue
            if row["is_active"] is not None or row["expired_at"] is not None or row["cause_role"] is not None:
                self.drop("event_links", row, "membership_flags")
                continue
            self.members[member] = group
            values.update(
                {
                    "tree_id": group,
                    "position": positions[group],
                    "member_event_id": member,
                }
            )
            positions[group] += 1
            self.sink.add("event_links", values)

    def run(self) -> dict[str, Any]:
        for table in Base.metadata.sorted_tables:
            if table.name == "event_groups":
                self.groups()
            elif table.name == "event_links":
                self.links()
            else:
                self.copy(table.name)
        self.sink.flush()
        return {
            "converted_rows": sum(self.sink.counts.values()),
            "converted_by_table": dict(sorted(self.sink.counts.items())),
            "dropped_rows": dict(sorted(self.dropped.items())),
            "dropped_by_table": dict(sorted(self.dropped_by_table.items())),
            "samples": self.samples,
        }


def _save_receipt(connection: Connection, archive: str, report: dict[str, Any]) -> None:
    connection.execute(
        text(
            f"CREATE TABLE {_quote(archive)}.migration_report "
            "(applied_at timestamptz NOT NULL DEFAULT now(),report jsonb NOT NULL)"
        )
    )
    connection.execute(
        text(f"INSERT INTO {_quote(archive)}.migration_report(report) VALUES(CAST(:report AS jsonb))"),
        {"report": json.dumps(report, ensure_ascii=False)},
    )


def _migrate(
    engine: Engine,
    *,
    apply: bool = False,
    schema: str = "public",
    archive_schema: str | None = None,
    expect_database: str | None = None,
    drop_unmappable: bool = False,
) -> dict[str, Any]:
    "在单个事务中核对源结构、完整归档并写入新结构，失败整体回滚"
    _quote(schema)
    archive = archive_schema or schema[:50] + "_pre_0_4_0"
    _quote(archive)
    if schema == archive:
        raise ValueError("归档 schema 必须与业务 schema 不同")
    if engine.dialect.name != "postgresql":
        raise ValueError("此迁移只支持 PostgreSQL")
    if apply and (not expect_database or engine.url.database != expect_database):
        raise ValueError("--apply 必须提供与实际数据库名完全匹配的 --expect-database")
    source_contract = _source_contract()
    isolation = "READ COMMITTED" if apply else "REPEATABLE READ"
    with engine.connect().execution_options(isolation_level=isolation) as connection, connection.begin():
        if not apply:
            connection.execute(text("SET TRANSACTION READ ONLY"))
        connection.execute(text("SET LOCAL statement_timeout='60s'"))
        connection.execute(text("SET LOCAL lock_timeout='5s'"))
        connection.execute(text("SET LOCAL TIME ZONE 'UTC'"))
        if not inspect(connection).has_schema(schema):
            raise ValueError(f"目标 schema 不存在: {schema}")
        extensions = {
            row["extname"]: row["nspname"]
            for row in connection.execute(
                text(
                    "SELECT e.extname,n.nspname FROM pg_extension e JOIN pg_namespace n ON n.oid=e.extnamespace "
                    "WHERE e.extname IN ('vector','pg_trgm')"
                )
            ).mappings()
        }
        if set(extensions) != {"vector", "pg_trgm"}:
            raise ValueError("缺少已安装的 vector 或 pg_trgm 扩展，请先准备数据库扩展")
        search_path = [schema, *sorted(set(extensions.values()) - {schema})]
        connection.execute(text("SET LOCAL search_path TO " + ",".join(_quote(name) for name in search_path)))
        _check_release()
        if (
            apply
            and not connection.execute(
                text("SELECT pg_try_advisory_xact_lock(hashtextextended(:key,0))"),
                {"key": f"noveliq-release:{engine.url.database}:{schema}"},
            ).scalar_one()
        ):
            raise ValueError("同一数据库与 schema 已有发布迁移正在执行")
        original_catalog = _catalog(connection, schema)
        if _already_migrated(connection, schema):
            return {
                "source_release": "0.3.0",
                "target_release": "0.4.0",
                "database": engine.url.database,
                "schema": schema,
                "already_migrated": True,
                "ready": True,
                "applied": False,
                "blocking_issues": [],
            }
        issues = _check_source(connection, schema, source_contract)
        if inspect(connection).has_schema(archive):
            issues.append(f"归档 schema 已存在，不能覆盖: {archive}")
        if not issues and apply:
            connection.execute(
                text(
                    "LOCK TABLE "
                    + ",".join(f"{_quote(schema)}.{_quote(name)}" for name in sorted(original_catalog))
                    + " IN SHARE ROW EXCLUSIVE MODE"
                )
            )
            if _catalog(connection, schema) != original_catalog:
                raise ValueError("获取停写锁期间源表目录发生变化，停止执行")
            issues.extend(_check_source(connection, schema, source_contract))
        if not issues:
            active = list(
                connection.execute(
                    text(
                        f"SELECT id,status FROM {_quote(schema)}.runs "
                        "WHERE status IN ('pending','running','cancelling')"
                    )
                ).mappings()
            )
            if active:
                tasks = [{key: str(value) for key, value in row.items()} for row in active]
                issues.append(f"存在未结束的任务: {tasks}")
            open_calls = connection.execute(
                text(f"SELECT count(*) FROM {_quote(schema)}.agent_loop WHERE finished_at IS NULL")
            ).scalar_one()
            if open_calls:
                issues.append(f"存在未结束的模型调用: {open_calls}")
        report: dict[str, Any] = {
            "source_release": "0.3.0",
            "target_release": "0.4.0",
            "database": engine.url.database,
            "schema": schema,
            "archive_schema": archive,
            "already_migrated": False,
            "ready": False,
            "applied": False,
            "blocking_issues": issues,
        }
        counts = _row_counts(connection, schema, original_catalog)
        report["source_row_counts"] = counts
        conversion = _Conversion(connection, schema, schema, apply=False, drop_unmappable=drop_unmappable)
        preview = conversion.run()
        issues.extend(conversion.issues)
        report.update(
            converted_rows=preview["converted_rows"],
            dropped_rows=preview["dropped_rows"],
            samples=preview["samples"],
            blocking_issues=issues,
            ready=not issues,
        )
        if issues or not apply:
            if issues and apply:
                raise ValueError(json.dumps(report, ensure_ascii=False, default=str))
            return report
        connection.execute(text(f"CREATE SCHEMA {_quote(archive)}"))
        for name in sorted(original_catalog):
            connection.execute(text(f"ALTER TABLE {_quote(schema)}.{_quote(name)} SET SCHEMA {_quote(archive)}"))
        if _catalog(connection, archive) != original_catalog:
            raise ValueError("归档表身份不一致，停止执行")
        Base.metadata.create_all(connection.execution_options(schema_translate_map={None: schema}))
        for statement in domain_constraint_statements():
            connection.execute(text(statement))
        if set(_catalog(connection, schema)) != set(Base.metadata.tables):
            raise ValueError("目标表目录与项目 ORM 不一致，停止执行")
        conversion = _Conversion(connection, archive, schema, apply=True, drop_unmappable=drop_unmappable)
        result = conversion.run()
        if result["converted_rows"] != preview["converted_rows"] or result["dropped_rows"] != preview["dropped_rows"]:
            raise ValueError("停写保护下转换结果与预检不一致，停止执行")
        for name, original in counts.items():
            converted = result["converted_by_table"].get(name, 0)
            dropped = result["dropped_by_table"].get(name, 0)
            if converted + dropped != original:
                raise ValueError(f"{name}: 转换 {converted} + 丢弃 {dropped} 与源记录数 {original} 不一致")
        report.update(result)
        connection.execute(text("SET CONSTRAINTS ALL IMMEDIATE"))
        if _row_counts(connection, archive, original_catalog) != counts:
            raise ValueError("原表归档前后记录数不一致，停止执行")
        report.update(applied=True, archive_verified=True)
        _save_receipt(connection, archive, report)
        return report


def migrate(
    *,
    database_env: DatabaseEnvironmentName,
    schema: str,
    apply: bool,
    expect_database: str | None,
    archive_schema: str | None = None,
    drop_unmappable: bool = False,
) -> dict[str, Any]:
    """读取项目数据库配置并执行只读预检或单事务迁移"""
    _quote(schema)
    if apply and not expect_database:
        raise ValueError("--apply 必须同时指定 --expect-database")
    url = make_url(resolve_database_url_from_env(database_env))
    if url.get_backend_name() != "postgresql" or not url.database:
        raise ValueError("迁移脚本只支持已存在的 PostgreSQL 数据库")
    if expect_database and url.database != expect_database:
        raise ValueError("目标数据库名称与 --expect-database 不一致")
    engine = create_engine(url, poolclass=NullPool, connect_args={"connect_timeout": 5})
    try:
        return _migrate(
            engine,
            apply=apply,
            schema=schema,
            archive_schema=archive_schema,
            expect_database=expect_database,
            drop_unmappable=drop_unmappable,
        )
    finally:
        engine.dispose()


def main() -> int:
    "解析显式执行参数，输出不含连接凭证的迁移报告"
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="完整归档原表并执行转换，默认只读预检")
    parser.add_argument("--database-env", choices=("DATABASE", "TEST_DATABASE"), default="DATABASE")
    parser.add_argument("--schema", help="业务 schema，默认读取对应的 *_SCHEMA 或使用 public")
    parser.add_argument("--archive-schema", help="归档 schema，默认 <业务schema>_pre_0_4_0，必须不存在")
    parser.add_argument("--expect-database", help="执行时必须明确匹配的数据库名")
    parser.add_argument(
        "--drop-unmappable",
        action="store_true",
        help="允许丢弃无法映射的旧组织行；省略时发现即阻断",
    )
    parser.add_argument("--report", type=Path, help="另存 JSON 报告，不覆盖已存在文件")
    args = parser.parse_args()
    if args.report is not None and args.report.exists():
        parser.error("报告文件已存在，停止覆盖")
    if args.report is not None and not args.report.parent.is_dir():
        parser.error("报告目录不存在，请先准备目录")
    load_dotenv(_ROOT / ".env")
    try:
        schema = args.schema or os.environ.get(args.database_env + "_SCHEMA", "public")
        report = migrate(
            database_env=cast(DatabaseEnvironmentName, args.database_env),
            apply=args.apply,
            schema=schema,
            archive_schema=args.archive_schema,
            expect_database=args.expect_database,
            drop_unmappable=args.drop_unmappable,
        )
    except (OSError, ValueError, RuntimeError, SQLAlchemyError) as error:
        print(json.dumps({"applied": False, "error": str(error)}, ensure_ascii=False, indent=2))
        return 2
    exit_code = 0 if report["ready"] else 2
    if args.report is not None:
        try:
            with args.report.open("x", encoding="utf-8") as stream:
                stream.write(json.dumps(report, ensure_ascii=False, indent=2, default=str) + "\n")
        except OSError as error:
            report["report_file_error"] = str(error)
            exit_code = 3 if report["applied"] else 2
    print(json.dumps(report, ensure_ascii=False, indent=2, default=str))
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
