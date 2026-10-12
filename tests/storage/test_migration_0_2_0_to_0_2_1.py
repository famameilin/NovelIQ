"""从真实 0.2.0 ORM 快照演练完整升级，不借当前 ORM 反推旧结构"""

from __future__ import annotations

import json
import sys
from collections.abc import Generator
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import inspect, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from scripts.migrations.migrate_0_2_0_to_0_2_1 import RETIRED, main, migrate
from src.fact_graph.graph import FactGraph, mention_uuid
from src.storage.models import AnalysisOutput, EventNode
from src.work.annotation_work import annotation_work_id
from tests.conftest import _build_test_engine


@pytest.fixture
def old_release_engine(db_session: Session) -> Generator[Engine, None, None]:
    schema = "release020_" + uuid4().hex[:12]
    parent = db_session.get_bind()
    with parent.begin() as connection:
        connection.execute(text(f'CREATE SCHEMA "{schema}"'))
    engine = _build_test_engine(parent.url.render_as_string(hide_password=False), schema)
    try:
        ddl = (Path(__file__).parents[1] / "fixtures/migrations/schema_0_2_0.sql").read_text(encoding="utf-8")
        with engine.begin() as connection:
            connection.exec_driver_sql(ddl)
        yield engine
    finally:
        engine.dispose()
        with parent.begin() as connection:
            for name in (schema,):
                connection.execute(text(f'DROP SCHEMA IF EXISTS "{name}" CASCADE'))


def _schema(engine: Engine) -> str:
    with engine.connect() as connection:
        return str(connection.execute(text("SELECT current_schema()")).scalar_one())


def _seed(engine: Engine) -> tuple[str, str, dict[str, object]]:
    run_id, annotation_id = str(uuid4()), str(uuid4())
    body = "甲与乙出门。"
    payload: dict[str, object] = {
        "metrics": {"summary": "二人出门", "emotional_valence": 0, "narrative_function": "铺垫"},
        "character_observations": [],
        "dialogues": [],
        "events": [],
        "paragraph_labels": [],
        "coverage_warnings": [],
    }
    with engine.begin() as connection:
        connection.execute(
            text("INSERT INTO novels (novel_id, filename, file_path) VALUES ('book020','a.txt','a.txt')")
        )
        connection.execute(
            text(
                "INSERT INTO analysis_runs (run_id, novel_id, status, progress, current, total, task_kind, "
                "cancel_requested, cancellation_epoch) "
                "VALUES (:run, 'book020', 'completed', 1, 1, 1, 'analysis', false, 0)"
            ),
            {"run": run_id},
        )
        connection.execute(
            text(
                "INSERT INTO chapters (run_id, chapter_id, sequence, title, display_title, "
                "level, start_pos, end_pos, text) "
                "VALUES (:run, 1, 1, '首章', '首章', 'chapter', 0, :size, :body)"
            ),
            {"run": run_id, "size": len(body), "body": body},
        )
        connection.execute(
            text(
                "INSERT INTO paragraphs (run_id, paragraph_id, chapter_id, paragraph_index, source_paragraph_index, "
                "fragment_index, local_start_char, local_end_char, global_start_char, global_end_char, char_count, "
                "token_count, text, created_at) "
                "VALUES (:run, 1, 1, 0, 0, 0, 0, :size, 0, :size, :size, 1, :body, now())"
            ),
            {"run": run_id, "size": len(body), "body": body},
        )
        connection.execute(
            text(
                "INSERT INTO chapter_annotations (annotation_id, run_id, chapter_id, payload, created_at) "
                "VALUES (:annotation, :run, 1, CAST(:payload AS jsonb), TIMESTAMPTZ '2026-10-01 20:00:00+08')"
            ),
            {"annotation": annotation_id, "run": run_id, "payload": json.dumps(payload, ensure_ascii=False)},
        )
    return run_id, annotation_id, payload


def _apply(engine: Engine) -> dict[str, object]:
    return migrate(engine, apply=True, schema=_schema(engine), expect_database=engine.url.database)


def test_upgrade_preserves_outputs_usage_and_is_idempotent(old_release_engine: Engine) -> None:
    engine = old_release_engine
    run_id, annotation_id, payload = _seed(engine)
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO cloud_analysis (novel_id, run_id, diagnosis) "
                "VALUES ('book020', :run, '旧诊断'), ('book020', :run, '最新诊断')"
            ),
            {"run": run_id},
        )
        connection.execute(
            text(
                "INSERT INTO agent_invocations (run_id, task_type, chapter_id, attempt_number, model_name, status, "
                "started_at, finished_at) VALUES (:run, 'annotation', 1, 1, 'test-model', 'success', now(), now())"
            ),
            {"run": run_id},
        )
        connection.execute(
            text(
                "INSERT INTO agent_turns (invocation_id, turn_index, status, raw_response, "
                "context_summary, started_at) "
                "VALUES (1, 1, 'success', '{}', '{}', now())"
            )
        )
        connection.execute(
            text(
                "INSERT INTO agent_tool_calls (turn_id, tool_name, call_index, request_args, status, started_at) "
                "VALUES (1, 'write_metrics', 0, '{}', 'success', now())"
            )
        )
        connection.execute(
            text(
                "INSERT INTO token_usage (novel_id, task_type, call_type, model, prompt_tokens, total_tokens, "
                "created_at, run_id, agent_turn_id) VALUES ('book020', 'annotation', 'agent', 'test-model', 10, 12, "
                "'2026-10-01T12:00:00', :run, 1), ('book020', 'embedding', 'local', 'embed', 5, 5, "
                "'2026-10-01T13:00:00', :run, NULL)"
            ),
            {"run": run_id},
        )
        connection.execute(
            text(
                "INSERT INTO continuity_cases (case_id, run_id, case_key, issue_kind, description, search_keys, "
                "target_ref, source_evidence, originating_annotation_id, originating_chapter_id, created_at) "
                "VALUES ('old-case', :run, 'key', 'identity', '  身份待查  ', "
                "'[]', '{}', '[{}]', :annotation, 1, now())"
            ),
            {"run": run_id, "annotation": annotation_id},
        )
    before = migrate(engine, schema=_schema(engine))
    assert before["blocking_issues"] == [], before
    assert not inspect(engine).has_table("analysis_outputs")
    result = _apply(engine)
    assert result["applied"] is True and result["converted_chapters"] == 1
    assert result["target_schema"]["ready"] is True
    with engine.connect() as connection:
        output = (
            connection.execute(text("SELECT * FROM analysis_outputs WHERE output_id=:id"), {"id": annotation_id})
            .mappings()
            .one()
        )
        assert output["payload"] == payload
        assert output["actual_input"]["chapter_text"] == "甲与乙出门。"
        assert output["work_id"] == annotation_work_id(run_id, 1, "solo")
        assert output["invocation_id"] == "audit:1"
        assert output["created_at"].isoformat() == "2026-10-01T12:00:00"
        diagnosis = (
            connection.execute(text("SELECT payload, created_at FROM analysis_outputs WHERE kind='agent_analysis'"))
            .mappings()
            .one()
        )
        assert diagnosis["payload"]["diagnosis"] == "最新诊断"
        assert connection.execute(text("SELECT sum(total_tokens) FROM model_turns")).scalar_one() == 17
        assert connection.execute(text("SELECT turn_id FROM agent_tool_calls")).scalar_one() == 1
        usage = connection.execute(text("SELECT started_at FROM model_turns WHERE row_kind='usage'")).scalar_one()
        assert usage.isoformat() == "2026-10-01T13:00:00"
        case = connection.execute(text("SELECT * FROM book_cases")).mappings().one()
        assert case["description"] == "身份待查" and case["state"] == "pending"
        assert output["work_id"] in case["contributions"]
        assert (
            connection.execute(
                text("SELECT count(*) FROM noveliq_release_migrations WHERE version='0.2.1'")
            ).scalar_one()
            == 1
        )
        assert (
            connection.execute(
                text("SELECT payload FROM analysis_outputs WHERE output_id=:id"),
                {"id": annotation_id},
            ).scalar_one()
            == payload
        )
    inspector = inspect(engine)
    for table in RETIRED:
        assert not inspector.has_table(table)
    with engine.begin() as connection:
        connection.execute(text("UPDATE analysis_runs SET status='running' WHERE run_id=:run"), {"run": run_id})
    again = _apply(engine)
    assert again["already_migrated"] is True and again["applied"] is False
    assert again["active_run_ids"] == [run_id]
    with engine.begin() as connection:
        connection.execute(text("DELETE FROM analysis_runs WHERE run_id=:run"), {"run": run_id})
        assert connection.execute(text("SELECT count(*) FROM analysis_outputs")).scalar_one() == 0


@pytest.mark.parametrize("status", ["pending", "running", "cancelling"])
def test_upgrade_refuses_active_tasks_before_ddl(old_release_engine: Engine, status: str) -> None:
    run_id, _, _ = _seed(old_release_engine)
    with old_release_engine.begin() as connection:
        connection.execute(
            text("UPDATE analysis_runs SET status=:status WHERE run_id=:run"), {"run": run_id, "status": status}
        )
    plan = migrate(old_release_engine, schema=_schema(old_release_engine))
    assert plan["active_run_ids"] == [run_id]
    with pytest.raises(ValueError, match="任务尚未收口"):
        _apply(old_release_engine)
    assert inspect(old_release_engine).has_table("work_items")


def test_upgrade_rolls_back_both_stages_on_orphan_usage(old_release_engine: Engine) -> None:
    _seed(old_release_engine)
    with old_release_engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO token_usage (novel_id, task_type, call_type, model, prompt_tokens, "
                "total_tokens, created_at) "
                "VALUES ('book020', 'embedding', 'local', 'embed', 5, 5, '2026-10-01T13:00:00')"
            )
        )
    with pytest.raises(ValueError, match="无 run 归属"):
        _apply(old_release_engine)
    inspector = inspect(old_release_engine)
    assert not inspector.has_table("analysis_outputs")
    assert inspector.has_table("chapter_annotations") and inspector.has_table("work_items")
    assert "role" not in {row["name"] for row in inspector.get_columns("chapter_annotations")}


def _seed_identity(engine: Engine, *, kind: str) -> tuple[str, str, dict[str, str]]:
    run_id, annotation_id, _ = _seed(engine)
    identities = {"left": str(uuid4()), "right": str(uuid4())}
    identity = {"canonical_entity_id": identities["right"], "identity_kind": "same", "reason": "原身份事实"}
    with engine.begin() as connection:
        for side, name in (("left", "甲"), ("right", "乙")):
            attributes = (
                {
                    "canonical_entity_id": identities["right"],
                    "identity_status": "same",
                    "referenced_entity_ids": [identities["right"]],
                }
                if side == "left"
                else {}
            )
            connection.execute(
                text(
                    "INSERT INTO graph_entities (entity_id, run_id, canonical_name, entity_type, tags, attributes, "
                    "first_seen_chapter, last_seen_chapter, created_at, updated_at) "
                    "VALUES (:id, :run, :name, :kind, '[]', CAST(:attributes AS jsonb), 1, 1, now(), now())"
                ),
                {
                    "id": identities[side],
                    "run": run_id,
                    "name": name,
                    "kind": kind,
                    "attributes": json.dumps(attributes),
                },
            )
        connection.execute(
            text(
                "INSERT INTO graph_facts (run_id, chapter_id, fact_id, fact_type, subject_entity_id, predicate, value, "
                "participants, scope, assertion, confidence, content, "
                "effective_chapter_id, source_kind, annotation_id, "
                "payload_path, evidence, created_at) VALUES (:run, 1, 'identity-legacy', 'identity', :id, 'identity', "
                "CAST(:identity AS jsonb), '[]', 'book', 'asserted', 'high', CAST(:identity AS jsonb), "
                "1, 'annotation', :annotation, 'identity/legacy', '[{}]', now())"
            ),
            {"run": run_id, "id": identities["left"], "identity": json.dumps(identity), "annotation": annotation_id},
        )
    return run_id, annotation_id, identities


def test_upgrade_preserves_identity_fact_and_restores_saved_graph(old_release_engine: Engine) -> None:
    run_id, annotation_id, identifiers = _seed_identity(old_release_engine, kind="character")
    result = _apply(old_release_engine)
    assert result["converted_identity_decisions"] == 1
    with Session(old_release_engine) as session:
        record = session.get(AnalysisOutput, annotation_id)
        assert record is not None
        graph = FactGraph(run_scope=run_id)
        graph.restore_storage(session, [record])
        assert graph.active_relations
        fact = session.execute(text("SELECT value, content FROM graph_facts WHERE fact_id='identity-legacy'"))
        legacy = fact.mappings().one()
        assert "operation_order" not in legacy["content"]
        assert legacy["value"]["canonical_entity_id"] == mention_uuid(run_id, 1, "乙")
        assert identifiers["right"] not in json.dumps(legacy, default=dict)
        attributes = session.execute(
            text("SELECT attributes FROM graph_entities WHERE entity_id=:id"),
            {"id": mention_uuid(run_id, 1, "甲")},
        ).scalar_one()
        assert attributes["referenced_entity_ids"] == [mention_uuid(run_id, 1, "乙")]


def test_upgrade_refuses_non_character_identity_without_rewriting_data(old_release_engine: Engine) -> None:
    _, _, identities = _seed_identity(old_release_engine, kind="item")
    plan = migrate(old_release_engine, schema=_schema(old_release_engine))
    assert plan["identity_preflight"]["issues"][0]["entity_id"] == identities["left"]
    with pytest.raises(ValueError, match="端点不是人物"):
        _apply(old_release_engine)
    with old_release_engine.connect() as connection:
        assert (
            connection.execute(text("SELECT count(*) FROM graph_entities WHERE entity_type='item'")).scalar_one() == 2
        )


def test_upgrade_refuses_wrong_database_and_missing_schema(old_release_engine: Engine) -> None:
    with pytest.raises(ValueError, match="匹配"):
        migrate(
            old_release_engine, apply=True, expect_database="different_database", schema=_schema(old_release_engine)
        )
    with pytest.raises(ValueError, match="schema 不存在"):
        migrate(old_release_engine, schema="not_existing_release_schema")


def test_upgrade_refuses_mixed_saved_work_before_ddl(old_release_engine: Engine) -> None:
    _, annotation_id, _ = _seed(old_release_engine)
    with old_release_engine.begin() as connection:
        connection.execute(text("ALTER TABLE chapter_annotations ADD COLUMN actual_input jsonb"))
        connection.execute(text("ALTER TABLE chapter_annotations ADD COLUMN invocation_id varchar(64)"))
        connection.execute(text("ALTER TABLE chapter_annotations DROP CONSTRAINT uq_chapter_annotations_run_chapter"))
        connection.execute(
            text(
                "INSERT INTO chapter_annotations (annotation_id, run_id, chapter_id, payload, created_at, "
                "actual_input, invocation_id) SELECT :id, run_id, chapter_id, payload, created_at, "
                "CAST(:input AS jsonb), 'saved-invocation' FROM chapter_annotations WHERE annotation_id=:source"
            ),
            {"id": str(uuid4()), "source": annotation_id, "input": json.dumps({"chapter_sequence": 1})},
        )
    plan = migrate(old_release_engine, schema=_schema(old_release_engine))
    issue = next(item for item in plan["blocking_issues"] if "混存" in item["reason"])
    assert issue["annotation_ids"] == [annotation_id]
    with pytest.raises(ValueError, match="混存"):
        _apply(old_release_engine)
    assert not inspect(old_release_engine).has_table("analysis_outputs")
    assert plan["identity_preflight"]["issues"] == []


@pytest.mark.parametrize("conflict", ["partial", "missing_column"])
def test_upgrade_refuses_unsafe_source_shapes(old_release_engine: Engine, conflict: str) -> None:
    _seed(old_release_engine)
    schema = _schema(old_release_engine)
    with old_release_engine.begin() as connection:
        if conflict == "partial":
            connection.execute(text("CREATE TABLE model_turns (id int)"))
        else:
            connection.execute(text("ALTER TABLE chapters DROP COLUMN text"))
    plan = migrate(old_release_engine, schema=schema)
    assert plan["blocking_issues"]
    with pytest.raises(ValueError):
        _apply(old_release_engine)
    assert inspect(old_release_engine).has_table("work_items")


def test_upgrade_preserves_main_edges_and_cross_tree_causality(old_release_engine: Engine) -> None:
    run_id, annotation_id, payload = _seed(old_release_engine)
    events = [
        {
            "node_id": name,
            "tree_id": "tree-b" if name == "other" else "tree-a",
            "parent_node_id": "root" if name == "child" else None,
            "cause_role": "main" if name == "child" else "root",
            "description": name,
            "evidence_paragraph_id": 1,
            "participants": [],
            "is_foreshadow_setup": False,
            "payoff_likelihood": None,
        }
        for name in ("root", "child", "other")
    ]
    payload["events"] = events
    with old_release_engine.begin() as connection:
        connection.execute(
            text("UPDATE chapter_annotations SET payload=CAST(:payload AS jsonb) WHERE annotation_id=:id"),
            {"id": annotation_id, "payload": json.dumps(payload)},
        )
        for event in events:
            connection.execute(
                text(
                    "INSERT INTO event_nodes (event_id, run_id, chapter_id, chapter_order, description, participants, "
                    "anchor_paragraph_ids, char_start, char_end, evidence, causal_event_refs, tree_id, cause_role, "
                    "is_foreshadowing_root, annotation_id, source_kind, payload_path, created_at) "
                    "VALUES (:id, :run, 1, 1, :id, '[]', '[1]', 0, 6, '[{}]', '[]', :tree, :role, "
                    "false, :annotation, 'annotation', :id, now())"
                ),
                {
                    "id": event["node_id"],
                    "run": run_id,
                    "tree": event["tree_id"],
                    "role": event["cause_role"],
                    "annotation": annotation_id,
                },
            )
        for edge, target in (("main-edge", "child"), ("cross-edge", "other")):
            connection.execute(
                text(
                    "INSERT INTO event_edges (edge_id, run_id, edge_type, source_event_id, target_event_id, "
                    "source_chapter_id, target_chapter_id, is_active, evidence, annotation_id, "
                    "payload_path, created_at) "
                    "VALUES (:id, :run, 'causal', 'root', :target, 1, 1, true, '[{}]', :annotation, :id, now())"
                ),
                {"id": edge, "run": run_id, "target": target, "annotation": annotation_id},
            )
    _apply(old_release_engine)
    with Session(old_release_engine) as session:
        output = session.get(AnalysisOutput, annotation_id)
        assert output is not None and output.payload == payload
        # 验证历史迁移的持久化结果，不要求 0.2.1 库具有后续新增动作表
        assert session.get(EventNode, "child").parent_node_id == "root"
        assert session.get(EventNode, "other").parent_node_id is None
        assert session.get(EventNode, "other").tree_id == "tree-b"
        cross = (
            session.execute(
                text("SELECT edge_type, source_event_id, target_event_id FROM event_edges WHERE edge_id='cross-edge'")
            )
            .mappings()
            .one()
        )
        assert (
            cross["edge_type"] == "causal"
            and cross["source_event_id"] == "root"
            and cross["target_event_id"] == "other"
        )
        roles = {
            row["edge_id"]: row["cause_role"]
            for row in session.execute(text("SELECT edge_id, cause_role FROM event_edges")).mappings()
        }
        assert roles == {"main-edge": "main", "cross-edge": None}


def test_upgrade_cli_preflight_then_apply(
    old_release_engine: Engine, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _seed(old_release_engine)
    command = ["migrate_0_2_0_to_0_2_1", "--database-env", "TEST_DATABASE", "--schema", _schema(old_release_engine)]
    url = old_release_engine.url
    monkeypatch.setenv(
        "TEST_DATABASE_URL", url._replace(username=None, password=None).render_as_string(hide_password=False)
    )
    monkeypatch.setenv("TEST_DATABASE_USERNAME", url.username or "")
    monkeypatch.setenv("TEST_DATABASE_PASSWORD", url.password or "")
    monkeypatch.setattr(sys, "argv", command)
    assert main() == 0
    assert json.loads(capsys.readouterr().out)["applied"] is False
    assert not inspect(old_release_engine).has_table("analysis_outputs")
    monkeypatch.setattr(sys, "argv", [*command, "--apply", "--expect-database", old_release_engine.url.database])
    assert main() == 0
    assert json.loads(capsys.readouterr().out)["applied"] is True
    assert inspect(old_release_engine).has_table("analysis_outputs")


def test_upgrade_does_not_guess_producer_from_multiple_successful_attempts(old_release_engine: Engine) -> None:
    run_id, annotation_id, _ = _seed(old_release_engine)
    with old_release_engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO agent_invocations (run_id, task_type, chapter_id, attempt_number, model_name, status, "
                "started_at, finished_at) VALUES (:run, 'annotation', 1, 1, 'first', 'success', now(), now()), "
                "(:run, 'annotation', 1, 2, 'second', 'success', now(), now())"
            ),
            {"run": run_id},
        )
    _apply(old_release_engine)
    with old_release_engine.connect() as connection:
        assert connection.execute(text("SELECT invocation_id FROM analysis_outputs")).scalar_one() == annotation_id
        assert connection.execute(text("SELECT count(*) FROM model_turns")).scalar_one() == 0
        assert not inspect(connection).has_table("agent_invocations")
