"""发布升级默认只读预检，执行时完整归档原表并转换可可靠映射的数据"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
from collections import Counter, defaultdict
from collections.abc import Iterator, Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from sqlalchemy import MetaData, UniqueConstraint, create_engine, inspect, text
from sqlalchemy.engine import Connection, Engine
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.pool import NullPool
from sqlalchemy.schema import CreateIndex, CreateTable

_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from src.config.project_version import project_version  # noqa: E402
from src.storage.constraints import domain_constraint_statements  # noqa: E402
from src.storage.database_url import resolve_database_url_from_env  # noqa: E402
from src.storage.db import validate_existing_schema  # noqa: E402
from src.storage.ids import new_id, new_task_id  # noqa: E402
from src.storage.models import Base  # noqa: E402

_ROLES = {"solo": "annotation", "structure": "entity", "event": "event", "evidence": "metric"}
_SIDECAR = Path(__file__).with_suffix(".json")
_ARCHIVE_REASONS = {
    "event_nodes": "缺少完整事件的标题、问题、类型和生命周期状态，不能补造正文",
    "event_edges": "原事件未转为完整事件，保留原端点、证据和树关系",
    "graph_facts": "缺少新事实合同所需的可靠操作顺序或互斥形状，保留原事实与来源",
    "entity_states": "保留实体状态、属性和变化，不把状态反推为历史写入操作",
    "relation_states": "保留关系观察与变化，不把状态反推为历史写入操作",
    "book_cases": "缺少可靠案例类型或已解决案例的真实承诺人，不推断或重置案例状态",
    "event_outbox": "旧消息没有新消息幂等键且载荷使用旧身份，保留原消息而不重放",
    "topic_model_runs": "模型参数、产物位置与构建记录在归档中保留，完成事实写入 runs",
    "word2vec_model_runs": "模型参数、产物位置与构建记录在归档中保留，完成事实写入 runs",
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


def _document(value: Any) -> bytes | None:
    if value is None:
        return None
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _time(value: Any) -> datetime | None:
    if value is None or isinstance(value, datetime):
        result = value
    else:
        result = datetime.fromisoformat(value)
    if result is not None and result.tzinfo is not None:
        result = result.astimezone(UTC).replace(tzinfo=None)
    return result


def _type_name(column_type: Any, connection: Connection) -> str:
    value = str(column_type.compile(dialect=connection.dialect)).lower()
    return "double precision" if value == "float" else value


def _target_contract(connection: Connection) -> dict[str, Any]:
    return {
        table.name: {
            "columns": {
                column.name: {"type": _type_name(column.type, connection), "nullable": column.nullable}
                for column in table.columns
            },
            "primary_key": [column.name for column in table.primary_key],
        }
        for table in Base.metadata.sorted_tables
    }


def _check_release(connection: Connection, manifest: dict[str, Any]) -> None:
    "核对发布代码与随脚本保存的结构清单，拒绝随当前模型漂移"
    if project_version() != "0.3.0":
        raise ValueError("此入口只用于项目 0.3.0 发布代码，请使用匹配发布的代码执行")
    digest = hashlib.sha256("\n".join(domain_constraint_statements()).encode()).hexdigest()
    statements = []
    for table in Base.metadata.sorted_tables:
        statements.append(str(CreateTable(table).compile(dialect=connection.dialect)))
        statements.extend(
            str(CreateIndex(index).compile(dialect=connection.dialect))
            for index in sorted(table.indexes, key=lambda item: str(item.name))
        )
    ddl_digest = hashlib.sha256("\n".join(statements).encode()).hexdigest()
    if (
        _target_contract(connection) != manifest["target"]
        or digest != manifest["target_constraints_sha256"]
        or ddl_digest != manifest["target_ddl_sha256"]
    ):
        raise ValueError("当前 ORM 或领域约束与此迁移的目标清单不符，停止执行")


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


def _check_source(connection: Connection, schema: str, manifest: dict[str, Any]) -> list[str]:
    inspector = inspect(connection)
    existing = set(inspector.get_table_names(schema=schema))
    expected = set(manifest["source"])
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
    for name, contract in manifest["source"].items():
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


class _Ids:
    "维护真实旧身份到新 UUIDv7 身份的映射"

    def __init__(self) -> None:
        self.values: dict[tuple[str, str], str] = {}

    def create(self, kind: str, old: Any) -> str:
        key = (kind, str(old))
        if key not in self.values:
            self.values[key] = new_id()
        return self.values[key]

    def get(self, kind: str, old: Any) -> str:
        try:
            return self.values[(kind, str(old))]
        except KeyError:
            raise ValueError(f"缺少真实来源身份: {kind}={old!r}") from None


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
    "只转换源记录能够直接证明的目标事实"

    def __init__(self, connection: Connection, source: str, target: str, *, apply: bool) -> None:
        self.connection = connection
        self.source = source
        self.sink = _Sink(connection, target, apply=apply)
        self.ids = _Ids()
        self.archived: Counter[tuple[str, str]] = Counter()
        self.samples: list[dict[str, Any]] = []
        self.reanalysis: dict[str, set[str]] = defaultdict(set)
        self.agents: dict[tuple[str, str], tuple[str, str]] = {}
        self.works: dict[str, dict[str, Any]] = {}
        self.chapters: dict[tuple[str, int], str | None] = {}
        self.paragraphs: dict[tuple[str, int], int] = {}
        self.artifacts: list[dict[str, Any]] = []

    def rows(self, table: str, *, order: str = "") -> Iterator[dict[str, Any]]:
        query = f"SELECT * FROM {_quote(self.source)}.{_quote(table)}"
        if order:
            query += " ORDER BY " + order
        result = self.connection.execute(text(query)).mappings()
        while batch := result.fetchmany(500):
            for row in batch:
                yield dict(row)

    def archive(self, table: str, row: Mapping[str, Any], reason: str, *, count: int = 1) -> None:
        self.archived[(table, reason)] += count
        run = row.get("run_id")
        if run:
            self.reanalysis[str(run)].add(reason)
        if len(self.samples) < 100:
            identity = {key: row[key] for key in ("run_id", "output_id", "work_id", "case_id", "id") if key in row}
            self.samples.append({"table": table, "identity": identity, "reason": reason})

    def agent(self, run: str, invocation: str, role: str) -> str:
        key = (run, invocation)
        if key in self.agents:
            identifier, actual_role = self.agents[key]
            if actual_role != role:
                raise ValueError(f"同一真实执行的角色不一致: invocation_id={invocation!r}")
            return identifier
        identifier = self.ids.create("agent", _key(run, invocation))
        self.agents[key] = (identifier, role)
        self.sink.add(
            "agent", {"id": identifier, "run_id": self.ids.get("run", run), "type": role, "status": "success"}
        )
        return identifier

    def inputs(self) -> None:
        model_runs = {table: list(self.rows(table)) for table in ("topic_model_runs", "word2vec_model_runs")}
        lda = {row["run_id"] for row in model_runs["topic_model_runs"]}
        w2v = {row["run_id"] for row in model_runs["word2vec_model_runs"]}
        for row in self.rows("novels"):
            self.sink.add("novels", {**row, "novel_id": self.ids.create("novel", row["novel_id"])})
        self.sink.flush()
        task_ids: set[str] = set()
        for row in self.rows("analysis_runs"):
            task = new_task_id()
            while task in task_ids:
                task = new_task_id()
            task_ids.add(task)
            self.sink.add(
                "runs",
                {
                    "id": self.ids.create("run", row["run_id"]),
                    "novelid": self.ids.get("novel", row["novel_id"]),
                    "taskid": task,
                    "status": row["status"],
                    "lda_completed": row["run_id"] in lda,
                    "w2v_completed": row["run_id"] in w2v,
                },
            )
        self.sink.flush()
        for table, records in model_runs.items():
            for row in records:
                self.artifacts.append(
                    {
                        "source_table": table,
                        "source_run_id": row["run_id"],
                        "target_run_id": self.ids.get("run", row["run_id"]),
                        "source_artifact_key": row["artifact_key"],
                    }
                )
        for row in self.rows("chapters"):
            run, chapter = row["run_id"], row["chapter_id"]
            self.chapters[(run, chapter)] = row["text"]
            self.sink.add(
                "chapters",
                {**row, "id": self.ids.create("chapter", _key(run, chapter)), "run_id": self.ids.get("run", run)},
            )
        self.sink.flush()

    def paragraph_results(self) -> None:
        source = _quote(self.source)
        query = (
            f"SELECT p.*,row_to_json(m) AS metric,row_to_json(l) AS linguistic,row_to_json(i) AS inference "
            f"FROM {source}.paragraphs p LEFT JOIN {source}.paragraph_metrics m USING (run_id,paragraph_id) "
            f"LEFT JOIN {source}.paragraph_linguistic_features l USING (run_id,paragraph_id) "
            f"LEFT JOIN {source}.paragraph_topic_inference i USING (run_id,paragraph_id) "
            "ORDER BY p.run_id,p.paragraph_id"
        )
        for mapping in self.connection.execute(text(query)).mappings():
            row = dict(mapping)
            run, paragraph = row["run_id"], row["paragraph_id"]
            if (run, row["chapter_id"]) not in self.chapters:
                raise ValueError(f"原文段落缺少所属章节: run_id={run} paragraph_id={paragraph}")
            self.paragraphs[(run, paragraph)] = row["chapter_id"]
            self.sink.add(
                "paragraphs",
                {**row, "id": self.ids.create("paragraph", _key(run, paragraph)), "run_id": self.ids.get("run", run)},
            )
            metric, linguistic, inference = row["metric"], row["linguistic"], row["inference"]
            values = {
                "id": self.ids.create("paragraph_metric", _key(run, paragraph)),
                "run_id": self.ids.get("run", run),
                "paragraph_id": paragraph,
                "token_count": row["token_count"],
                "preprocess_observed_at": row["created_at"],
            }
            if metric:
                if metric["token_count"] != row["token_count"]:
                    raise ValueError(f"段落与指标的 token_count 冲突: run_id={run} paragraph_id={paragraph}")
                excluded = {"id", "run_id", "paragraph_id", "created_at"}
                values.update({key: value for key, value in metric.items() if key not in excluded})
                values["metrics_created_at"] = _time(metric["created_at"])
                for column in Base.metadata.tables["paragraph_metrics"].columns:
                    if column.name.startswith("fw_"):
                        values[column.name] = (metric["function_word_counts"] or {}).get(column.name[3:], 0)
                    elif column.name.startswith("semantic_"):
                        values[column.name] = (metric["semantic_category_counts"] or {}).get(column.name[9:], 0)
                self.feature(row, "tension_z", scalar=metric["surface_tension_z"], created=_time(metric["created_at"]))
            if linguistic:
                if metric and metric["sentence_count"] != linguistic["sentence_count"]:
                    raise ValueError(f"指标与语言结果的 sentence_count 冲突: run_id={run} paragraph_id={paragraph}")
                values["sentence_count"] = linguistic["sentence_count"]
                values["linguistic_completed_at"] = _time(linguistic["created_at"])
                values["boundary_pos_score_sum"] = linguistic["boundary_pos_score_sum"]
                values["boundary_neg_score_sum"] = linguistic["boundary_neg_score_sum"]
                self.linguistic(row, linguistic)
            if inference:
                values.update(
                    inference_token_count=inference["inference_token_count"],
                    inference_status=inference["inference_status"],
                    inference_error_text=(
                        inference["unavailable_reason"] if inference["inference_status"] == "failed" else None
                    ),
                    inference_created_at=_time(inference["created_at"]),
                )
            self.sink.add("paragraph_metrics", values)
        self.sink.flush()
        for row in self.rows("paragraph_topics"):
            self.sink.add(
                "lda_paragraph_topics",
                {
                    **row,
                    "id": self.ids.create("topic", _key(row["run_id"], row["paragraph_id"], row["topic_id"])),
                    "run_id": self.ids.get("run", row["run_id"]),
                },
            )
        for row in self.rows("paragraph_curves"):
            for source_column, code in (
                ("smoothed_net_density", "lowess_net_density"),
                ("smoothed_surface_tension", "lowess_surface_tension"),
            ):
                self.feature(row, code, scalar=row[source_column], created=row["created_at"])
        for row in self.rows("paragraph_embeddings"):
            self.feature(row, "semantic_vector", vector=row["embedding_vector"], created=row["created_at"])
        for row in self.rows("paragraph_pos_embeddings"):
            self.feature(
                row,
                "pos_vector:" + row["pos_group"],
                vector=row["embedding_vector"],
                created=row["created_at"],
                in_vocabulary=row["in_vocabulary_token_count"],
            )
        for table, kind in (("paragraph_entities", "ner"), ("paragraph_phrase_hits", "phrase")):
            for row in self.rows(table):
                self.sink.add(
                    "paragraph_spans",
                    {
                        "span_id": self.ids.create(kind, row["id"]),
                        "run_id": self.ids.get("run", row["run_id"]),
                        "paragraph_id": row["paragraph_id"],
                        "start_char": row["local_start_char"],
                        "end_char": row["local_end_char"],
                        "raw_entity_type": row["raw_entity_type"] if kind == "ner" else None,
                        "phrase_match_kind": row["match_kind"] if kind == "phrase" else None,
                        "created_at": row["created_at"],
                    },
                )
        self.sink.flush()

    def feature(
        self,
        row: Mapping[str, Any],
        code: str,
        *,
        scalar: Any = None,
        vector: Any = None,
        count: Any = None,
        created: Any = None,
        in_vocabulary: Any = None,
    ) -> None:
        if scalar is None and vector is None and count is None and in_vocabulary != 0:
            return
        if created is None:
            self.archive("paragraph_embeddings", row, "向量结果没有真实生成时间，不能补造时间")
            return
        if isinstance(vector, str):
            vector = json.loads(vector)
        self.sink.add(
            "paragraph_features",
            {
                "id": self.ids.create("feature", _key(row["run_id"], row["paragraph_id"], code)),
                "run_id": self.ids.get("run", row["run_id"]),
                "paragraph_id": row["paragraph_id"],
                "feature_code": code,
                "scalar_value": scalar,
                "vector_value": vector,
                "count_value": count,
                "in_vocabulary_token_count": in_vocabulary,
                "created_at": created,
            },
        )

    def linguistic(self, paragraph: dict[str, Any], row: dict[str, Any]) -> None:
        run, pid = paragraph["run_id"], paragraph["paragraph_id"]
        tokens = {}
        for token in row["tokens"]:
            index = token["token_index"]
            if index < 1 or index in tokens:
                raise ValueError(f"语言词元序号非法或重复: run_id={run} paragraph_id={pid} token_index={index}")
            if paragraph["text"][token["local_start_char"] : token["local_end_char"]] != token["text"]:
                raise ValueError(f"语言词元与原文不符: run_id={run} paragraph_id={pid} token_index={index}")
            identifier = self.ids.create("token", _key(run, pid, index))
            tokens[index] = identifier
            self.sink.add(
                "paragraph_spans",
                {
                    "span_id": identifier,
                    "run_id": self.ids.get("run", run),
                    "paragraph_id": pid,
                    "start_char": token["local_start_char"],
                    "end_char": token["local_end_char"],
                    "token_index": index - 1,
                    "raw_pos": token["pos_tag"],
                    "created_at": _time(row["created_at"]),
                },
            )
        self.sink.flush("paragraph_spans")
        for field, prefix, label in (("dependency_arcs", "dep:", "relation"), ("sdp_arcs", "sdp:", "label")):
            for ordinal, arc in enumerate(row[field]):
                dependent, head = arc["dependent_index"], arc["head_index"]
                if dependent not in tokens or (head != 0 and head not in tokens):
                    raise ValueError(f"语言弧引用不存在的词元: run_id={run} paragraph_id={pid} arc={arc!r}")
                self.sink.add(
                    "paragraph_arcs",
                    {
                        "arc_id": self.ids.create("arc", _key(run, pid, prefix, ordinal)),
                        "dependent_span_id": tokens[dependent],
                        "head_span_id": tokens.get(head),
                        "relation_code": prefix + arc[label],
                        "source_ordinal": ordinal,
                    },
                )
        for name in ("short", "medium", "long", "compound", "parallel_candidate"):
            self.feature(
                paragraph,
                "sentence_" + name,
                count=row["sentence_pattern_counts"].get(name, 0),
                created=_time(row["created_at"]),
            )

    def annotations(self) -> None:
        for row in self.rows("annotation_work"):
            if row["role"] not in _ROLES or not row["invocation_id"] or row["saved_at"] is None:
                self.archive("annotation_work", row, "标注工作缺少可映射角色、真实执行身份或保存时间")
                continue
            row["agent_id"] = self.agent(row["run_id"], row["invocation_id"], _ROLES[row["role"]])
            self.works[row["work_id"]] = row
        self.sink.flush()
        for row in self.rows("analysis_outputs", order="created_at,output_id"):
            if row["kind"] != "chapter_annotation":
                self.archive("analysis_outputs", row, "诊断产物未保存真实生产执行，不能从时间邻近或调用状态推断作者")
                continue
            work = self.works.get(row["work_id"])
            if work is None:
                self.archive("analysis_outputs", row, "标注产物没有匹配的成功工作记录")
                continue
            if (row["run_id"], row["chapter_id"], row["role"], row["invocation_id"]) != (
                work["run_id"],
                work["chapter_id"],
                work["role"],
                work["invocation_id"],
            ):
                raise ValueError(f"产物与成功工作来源冲突: output_id={row['output_id']}")
            metrics = row["payload"].get("metrics") or {}
            identifier = self.ids.create("annotation", row["output_id"])
            self.sink.add(
                "agent_annotations",
                {
                    **metrics,
                    "record_id": identifier,
                    "agent_id": work["agent_id"],
                    "run_id": self.ids.get("run", row["run_id"]),
                    "chapter_id": row["chapter_id"],
                    "role": _ROLES[row["role"]],
                    "created_at": row["created_at"],
                    "saved_at": work["saved_at"],
                },
            )
            self.sink.flush("agent_annotations")
            for label in row["payload"].get("paragraph_labels", []):
                paragraph = label["paragraph_id"]
                if self.paragraphs.get((row["run_id"], paragraph)) != row["chapter_id"]:
                    raise ValueError(f"段落情绪标签不属于标注章: output_id={row['output_id']} paragraph_id={paragraph}")
                self.sink.add(
                    "agent_assessments",
                    {
                        "assessment_id": self.ids.create("emotion", _key(row["output_id"], paragraph)),
                        "record_id": identifier,
                        "paragraph_id": paragraph,
                        "emotion": label["emotion"],
                    },
                )
        self.sink.flush()

    def graph(self) -> None:
        for row in self.rows("graph_entities"):
            identifier = self.ids.create("entity", row["entity_id"])
            self.sink.add(
                "graph_entities", {**row, "entity_id": identifier, "run_id": self.ids.get("run", row["run_id"])}
            )
            if row["tags"] or row["attributes"]:
                self.archive("graph_entities", row, "实体身份已转换，标签与属性保留归档，不能推断其真实写入顺序")
        self.sink.flush()
        source = _quote(self.source)
        query = (
            f"SELECT r.*,array_agg(DISTINCT s.relation_type) FILTER (WHERE s.relation_type IS NOT NULL) AS types "
            f"FROM {source}.graph_relations r LEFT JOIN {source}.relation_states s USING (relation_id) "
            "GROUP BY r.relation_id"
        )
        for mapping in self.connection.execute(text(query)).mappings():
            row = dict(mapping)
            if not row["types"] or len(row["types"]) != 1:
                self.archive("graph_relations", row, "关系没有唯一可证明的关系类型，不能选择或拆分历史关系")
                continue
            self.sink.add(
                "graph_relations",
                {
                    **row,
                    "relation_id": self.ids.create("relation", row["relation_id"]),
                    "from_entity_id": self.ids.get("entity", row["from_entity_id"]),
                    "to_entity_id": self.ids.get("entity", row["to_entity_id"]),
                    "relation_type": row["types"][0],
                },
            )
        for row in self.rows("dialogue_records"):
            work = self.works.get(row["author_work_id"])
            if work is None or row["event_id"] is not None:
                self.archive("dialogue_records", row, "对话缺少真实创建执行或关联事件未转换")
                continue
            if work["run_id"] != row["run_id"] or work["chapter_id"] != row["chapter_id"]:
                raise ValueError(f"对话创建工作归属冲突: dialogue_id={row['dialogue_id']}")
            chapter_text = self.chapters.get((row["run_id"], row["chapter_id"]))
            if chapter_text is None or chapter_text[row["start"] : row["end"]] != row["content"]:
                self.archive("dialogue_records", row, "对话原文与新读取合同的章节字符坐标不符")
                continue
            self.sink.add(
                "graph_dialogues",
                {
                    **row,
                    "dialogue_id": self.ids.create("dialogue", row["dialogue_id"]),
                    "run_id": self.ids.get("run", row["run_id"]),
                    "creation_agent_id": work["agent_id"],
                    "start_char": row["start"],
                    "end_char": row["end"],
                    "speaker_entity_id": self.ids.get("entity", row["speaker"]) if row["speaker"] else None,
                },
            )
        self.sink.flush()

    def statistics(self) -> None:
        grouped: dict[str, dict[str, Any]] = {}
        columns = set(Base.metadata.tables["global_stats"].columns.keys()) - {"run_id"}
        for row in self.rows("global_stats"):
            if row["stat_name"] not in columns:
                self.archive("global_stats", row, "统计名称不属于目标的具名统计列")
                continue
            values = grouped.setdefault(row["run_id"], {"run_id": self.ids.get("run", row["run_id"])})
            value = row["stat_value"]
            if value is not None and row["stat_name"].endswith("_chapter_id"):
                if not float(value).is_integer():
                    raise ValueError(f"统计章节号不是整数: stat_name={row['stat_name']} stat_value={value}")
                value = int(value)
            values[row["stat_name"]] = value
        for values in grouped.values():
            self.sink.add("global_stats", values)
        self.sink.flush()

    def audit(self) -> None:
        source = _quote(self.source)
        duplicates = {
            (row["run_id"], row["execution_id"], row["turn_index"])
            for row in self.connection.execute(
                text(
                    f"SELECT run_id,execution_id,turn_index FROM {source}.model_turns "
                    "WHERE execution_id IS NOT NULL GROUP BY run_id,execution_id,turn_index HAVING count(*)>1"
                )
            ).mappings()
        }
        for row in self.rows("model_turns"):
            producer = self.agents.get((row["run_id"], row["execution_id"]))
            is_agent = (
                producer is not None
                and row["turn_index"] is not None
                and (row["run_id"], row["execution_id"], row["turn_index"]) not in duplicates
            )
            values = {
                **row,
                "id": self.ids.create("model_turn", row["id"]),
                "request_messages_bytes": _document(row["request_messages"]),
                "raw_response_bytes": _document(row["raw_response"]),
                "context_observed_bytes": _document(row["context_summary"]),
                "timing_notes_bytes": _document(row["timing_notes"]),
                "reported_total_tokens": row["total_tokens"] if row["accounting_source"] == "reported" else None,
                "turn_index": row["turn_index"] if is_agent else None,
            }
            if is_agent:
                assert producer is not None
                values["agent_id"] = producer[0]
            else:
                values.update(
                    standalone_run_id=self.ids.get("run", row["run_id"]),
                    standalone_chapter_id=row["chapter_id"],
                    standalone_task_type=row["task_type"],
                    standalone_call_type=row["call_type"],
                )
            self.sink.add("agent_loop", values)
        self.sink.flush()
        for row in self.rows("agent_tool_calls"):
            self.sink.add(
                "agent_toolcall",
                {
                    **row,
                    "id": self.ids.create("tool_call", row["id"]),
                    "agentloop_id": self.ids.get("model_turn", row["turn_id"]),
                    "raw_args_bytes": row["raw_args"].encode("utf-8") if row["raw_args"] is not None else None,
                    "executed_args_bytes": _document(row["request_args"]),
                    "response_observed_bytes": _document(row["response"]),
                    "receipt_observed_bytes": _document(row["receipt"]),
                },
            )
        self.sink.flush()

    def run(self) -> dict[str, Any]:
        self.inputs()
        self.paragraph_results()
        self.annotations()
        self.graph()
        self.statistics()
        self.audit()
        for table, reason in _ARCHIVE_REASONS.items():
            for row in self.connection.execute(
                text(f"SELECT run_id,count(*) AS count FROM {_quote(self.source)}.{_quote(table)} GROUP BY run_id")
            ).mappings():
                self.archive(table, dict(row), reason, count=row["count"])
        return {
            "converted_rows": dict(sorted(self.sink.counts.items())),
            "archived_items": [
                {"table": table, "count": count, "reason": reason}
                for (table, reason), count in sorted(self.archived.items())
            ],
            "archive_samples": self.samples,
            "requires_reanalysis": [
                {"source_run_id": run, "target_run_id": self.ids.get("run", run), "reasons": sorted(reasons)}
                for run, reasons in sorted(self.reanalysis.items())
            ],
            "external_artifacts": {
                "copied": False,
                "items": self.artifacts,
                "note": "原始文件路径保持原值；模型文件不复制，模型完成标志只保留原构建事实，不代表新路径可读",
            },
        }


def _save_receipt(connection: Connection, archive: str, conversion: _Conversion, report: dict[str, Any]) -> None:
    connection.execute(
        text(
            f"CREATE TABLE {_quote(archive)}.migration_ids "
            "(kind text NOT NULL,source_id text NOT NULL,target_id uuid NOT NULL,"
            "PRIMARY KEY(kind,source_id))"
        )
    )
    statement = text(
        f"INSERT INTO {_quote(archive)}.migration_ids(kind,source_id,target_id) "
        "VALUES (:kind,:source_id,CAST(:target_id AS uuid))"
    )
    batch = []
    for (kind, source), target in conversion.ids.values.items():
        batch.append({"kind": kind, "source_id": source, "target_id": target})
        if len(batch) >= 500:
            connection.execute(statement, batch)
            batch.clear()
    if batch:
        connection.execute(statement, batch)
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


def migrate(
    engine: Engine,
    *,
    apply: bool = False,
    schema: str = "public",
    archive_schema: str | None = None,
    expect_database: str | None = None,
) -> dict[str, Any]:
    "在单个事务中核对源结构、完整归档并写入新结构，失败整体回滚"
    _quote(schema)
    archive = archive_schema or schema[:50] + "_pre_0_3_0"
    _quote(archive)
    if schema == archive:
        raise ValueError("归档 schema 必须与业务 schema 不同")
    if engine.dialect.name != "postgresql":
        raise ValueError("此迁移只支持 PostgreSQL")
    if apply and (not expect_database or engine.url.database != expect_database):
        raise ValueError("--apply 必须提供与实际数据库名完全匹配的 --expect-database")
    manifest = json.loads(_SIDECAR.read_text(encoding="utf-8"))
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
        _check_release(connection, manifest)
        if (
            apply
            and not connection.execute(
                text("SELECT pg_try_advisory_xact_lock(hashtextextended(:key,0))"),
                {"key": f"noveliq-release:{engine.url.database}:{schema}"},
            ).scalar_one()
        ):
            raise ValueError("同一数据库与 schema 已有发布迁移正在执行")
        original_catalog = _catalog(connection, schema)
        if set(original_catalog) == set(Base.metadata.tables):
            validate_existing_schema(connection, schema=schema)
            return {
                "source_release": "0.2.1",
                "target_release": "0.3.0",
                "database": engine.url.database,
                "schema": schema,
                "already_migrated": True,
                "ready": True,
                "applied": False,
                "blocking_issues": [],
            }
        issues = _check_source(connection, schema, manifest)
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
            issues.extend(_check_source(connection, schema, manifest))
        if not issues:
            active = list(
                connection.execute(
                    text(
                        f"SELECT run_id,status FROM {_quote(schema)}.analysis_runs "
                        "WHERE status IN ('pending','running','cancelling')"
                    )
                ).mappings()
            )
            if active:
                issues.append(f"存在未结束的任务: {[dict(row) for row in active]}")
            open_calls = connection.execute(
                text(f"SELECT count(*) FROM {_quote(schema)}.model_turns WHERE status='running'")
            ).scalar_one()
            if open_calls:
                issues.append(f"存在未结束的模型调用: {open_calls}")
        report: dict[str, Any] = {
            "source_release": "0.2.1",
            "target_release": "0.3.0",
            "database": engine.url.database,
            "schema": schema,
            "archive_schema": archive,
            "already_migrated": False,
            "ready": not issues,
            "applied": False,
            "blocking_issues": issues,
        }
        if issues:
            if apply:
                raise ValueError(json.dumps(report, ensure_ascii=False))
            return report
        counts = _row_counts(connection, schema, original_catalog)
        report["source_row_counts"] = counts
        conversion = _Conversion(connection, schema, schema, apply=False)
        report.update(conversion.run())
        if not apply:
            for item in report["requires_reanalysis"]:
                item.pop("target_run_id")
            for item in report["external_artifacts"]["items"]:
                item.pop("target_run_id")
            return report
        connection.execute(text(f"CREATE SCHEMA {_quote(archive)}"))
        for name in sorted(original_catalog):
            connection.execute(text(f"ALTER TABLE {_quote(schema)}.{_quote(name)} SET SCHEMA {_quote(archive)}"))
        if _catalog(connection, archive) != original_catalog:
            raise ValueError("归档表身份不一致，停止执行")
        Base.metadata.create_all(connection.execution_options(schema_translate_map={None: schema}))
        for statement in domain_constraint_statements():
            connection.execute(text(statement))
        conversion = _Conversion(connection, archive, schema, apply=True)
        result = conversion.run()
        if result["converted_rows"] != report["converted_rows"] or result["archived_items"] != report["archived_items"]:
            raise ValueError("停写保护下转换结果与预检不一致，停止执行")
        report.update(result)
        validate_existing_schema(connection, schema=schema)
        connection.execute(text("SET CONSTRAINTS ALL IMMEDIATE"))
        if _row_counts(connection, archive, original_catalog) != counts:
            raise ValueError("原表归档前后记录数不一致，停止执行")
        report.update(applied=True, archive_verified=True)
        _save_receipt(connection, archive, conversion, report)
        return report


def main() -> int:
    "解析显式执行参数，输出不含连接凭证的迁移报告"
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="完整归档原表并执行转换，默认只读预检")
    parser.add_argument("--database-env", choices=("DATABASE", "TEST_DATABASE"), default="DATABASE")
    parser.add_argument("--schema", help="业务 schema，默认读取对应的 *_SCHEMA 或使用 public")
    parser.add_argument("--archive-schema", help="归档 schema，默认 <业务schema>_pre_0_3_0，必须不存在")
    parser.add_argument("--expect-database", help="执行时必须明确匹配的数据库名")
    parser.add_argument("--report", type=Path, help="另存 JSON 报告，不覆盖已存在文件")
    args = parser.parse_args()
    if args.report is not None and args.report.exists():
        parser.error("报告文件已存在，停止覆盖")
    if args.report is not None and not args.report.parent.is_dir():
        parser.error("报告目录不存在，请先准备目录")
    load_dotenv(_ROOT / ".env")
    engine = None
    try:
        schema = args.schema or os.environ.get(args.database_env + "_SCHEMA", "public")
        engine = create_engine(
            resolve_database_url_from_env(args.database_env), poolclass=NullPool, connect_args={"connect_timeout": 5}
        )
        report = migrate(
            engine,
            apply=args.apply,
            schema=schema,
            archive_schema=args.archive_schema,
            expect_database=args.expect_database,
        )
    except (OSError, ValueError, RuntimeError, SQLAlchemyError) as error:
        print(json.dumps({"applied": False, "error": str(error)}, ensure_ascii=False, indent=2))
        return 2
    finally:
        if engine is not None:
            engine.dispose()
    exit_code = 0 if report["ready"] else 2
    if args.report is not None:
        try:
            with args.report.open("x", encoding="utf-8") as stream:
                stream.write(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
        except OSError as error:
            report["report_file_error"] = str(error)
            exit_code = 3 if report["applied"] else 2
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
