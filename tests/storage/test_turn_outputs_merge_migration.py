"""隔离 PostgreSQL schema 演练审计/产物六表合并迁移（只读检查、完整迁移、重复执行拒绝）"""

from __future__ import annotations

import sys
from uuid import uuid4

import pytest
from sqlalchemy import inspect, text
from sqlalchemy.engine import Engine, make_url

from scripts.migrations.check_0_2_1 import inspect_current_schema
from scripts.migrations.migrate_turn_outputs_merge import apply_migration, main, migration_plan
from tests.conftest import _build_test_engine, _create_all_orm_tables


@pytest.fixture
def pre_merge_engine(db_session):
    """DDL 演练独占 schema：还原已完成角色 work 转换、尚未合并审计表的中间结构"""
    schema = "test_migration_" + uuid4().hex[:12]
    parent = db_session.get_bind()
    with parent.begin() as connection:
        connection.execute(text(f'CREATE SCHEMA "{schema}"'))
    engine = _build_test_engine(str(parent.url.render_as_string(hide_password=False)), schema)
    _create_all_orm_tables(engine)
    with engine.begin() as connection:
        # 回退到合并前形状：删新表，重建旧四表/旧两表/旧 book_cases
        for constraint in connection.execute(
            text(
                "SELECT conrelid::regclass::text AS table, conname FROM pg_constraint "
                "WHERE contype = 'f' AND confrelid = 'analysis_outputs'::regclass"
            )
        ).all():
            connection.execute(text(f'ALTER TABLE {constraint.table} DROP CONSTRAINT "{constraint.conname}"'))
        connection.execute(text("DROP TABLE agent_tool_calls"))
        connection.execute(text("DROP TABLE model_turns"))
        connection.execute(text("DROP TABLE analysis_outputs"))
        connection.execute(text("ALTER TABLE book_cases DROP COLUMN state"))
        connection.execute(text("ALTER TABLE book_cases DROP COLUMN contributions"))
        connection.execute(
            text(
                """
                CREATE TABLE agent_invocations (
                    id SERIAL PRIMARY KEY,
                    run_id VARCHAR(36) NOT NULL REFERENCES analysis_runs (run_id) ON DELETE CASCADE,
                    task_type VARCHAR(20) NOT NULL,
                    chapter_id INTEGER,
                    work_id VARCHAR(64),
                    role VARCHAR(20),
                    execution_id VARCHAR(64) UNIQUE,
                    attempt_number INTEGER NOT NULL,
                    model_name VARCHAR(100),
                    status VARCHAR(20) NOT NULL,
                    final_error TEXT,
                    started_at TIMESTAMP NOT NULL,
                    finished_at TIMESTAMP
                )
                """
            )
        )
        connection.execute(
            text(
                """
                CREATE TABLE agent_turns (
                    id SERIAL PRIMARY KEY,
                    invocation_id INTEGER NOT NULL REFERENCES agent_invocations (id) ON DELETE CASCADE,
                    turn_index INTEGER NOT NULL,
                    status VARCHAR(20) NOT NULL,
                    error TEXT,
                    raw_response JSONB NOT NULL,
                    context_summary JSONB NOT NULL,
                    request_messages JSONB NOT NULL DEFAULT '[]',
                    timing_notes JSONB NOT NULL DEFAULT '[]',
                    ttft_ms INTEGER,
                    first_visible_ms INTEGER,
                    reasoning_ms INTEGER,
                    model_ms INTEGER,
                    tool_wall_ms INTEGER,
                    turn_ms INTEGER,
                    started_at TIMESTAMP NOT NULL,
                    finished_at TIMESTAMP
                )
                """
            )
        )
        connection.execute(
            text(
                """
                CREATE TABLE agent_tool_calls (
                    id SERIAL PRIMARY KEY,
                    turn_id INTEGER NOT NULL REFERENCES agent_turns (id) ON DELETE CASCADE,
                    tool_name VARCHAR(100) NOT NULL,
                    call_index INTEGER NOT NULL,
                    request_args JSONB NOT NULL,
                    raw_args TEXT,
                    response JSONB,
                    receipt JSONB,
                    status VARCHAR(20) NOT NULL,
                    error TEXT,
                    tool_duration_ms INTEGER,
                    started_at TIMESTAMP NOT NULL
                )
                """
            )
        )
        connection.execute(
            text(
                """
                CREATE TABLE token_usage (
                    id SERIAL PRIMARY KEY,
                    novel_id VARCHAR(255) NOT NULL REFERENCES novels (novel_id),
                    chapter_id INTEGER,
                    task_type VARCHAR(100) NOT NULL,
                    call_type VARCHAR(50) NOT NULL,
                    model VARCHAR(100) NOT NULL,
                    prompt_tokens INTEGER NOT NULL,
                    completion_tokens INTEGER,
                    total_tokens INTEGER NOT NULL,
                    cache_read_tokens INTEGER,
                    reasoning_tokens INTEGER,
                    cost FLOAT,
                    accounting_source VARCHAR(20) NOT NULL DEFAULT 'reported',
                    created_at TIMESTAMP NOT NULL,
                    run_id VARCHAR(36) REFERENCES analysis_runs (run_id) ON DELETE CASCADE,
                    agent_turn_id INTEGER UNIQUE REFERENCES agent_turns (id) ON DELETE CASCADE
                )
                """
            )
        )
        connection.execute(
            text(
                """
                CREATE TABLE audit_messages (
                    message_id VARCHAR(128) PRIMARY KEY,
                    execution_id VARCHAR(64) NOT NULL,
                    method VARCHAR(50) NOT NULL,
                    local_id INTEGER NOT NULL,
                    result_id INTEGER
                )
                """
            )
        )
        connection.execute(
            text(
                """
                CREATE TABLE chapter_annotations (
                    annotation_id VARCHAR(36) PRIMARY KEY,
                    run_id VARCHAR(36) NOT NULL REFERENCES analysis_runs (run_id) ON DELETE CASCADE,
                    chapter_id INTEGER NOT NULL,
                    payload JSONB NOT NULL,
                    role VARCHAR(20) NOT NULL DEFAULT 'solo',
                    actual_input JSONB NOT NULL DEFAULT '{}',
                    invocation_id VARCHAR(64),
                    work_id VARCHAR(64) UNIQUE,
                    created_at TIMESTAMP NOT NULL DEFAULT now()
                )
                """
            )
        )
        connection.execute(
            text(
                """
                CREATE TABLE cloud_analysis (
                    id SERIAL PRIMARY KEY,
                    novel_id VARCHAR(255) REFERENCES novels (novel_id),
                    foreshadow_expectation FLOAT,
                    arc_scores TEXT,
                    genre_labels TEXT,
                    style_labels TEXT,
                    topic_labels TEXT,
                    diagnosis TEXT,
                    value_logic_type VARCHAR(50),
                    value_logic_reason TEXT,
                    power_stance_score INTEGER,
                    power_stance_reason TEXT,
                    common_people_dignity INTEGER,
                    dignity_reason TEXT,
                    cultural_depth_score INTEGER,
                    cultural_depth_reason TEXT,
                    narrative_arc_type VARCHAR(50),
                    focus_structure VARCHAR(20),
                    focus_characters TEXT,
                    main_characters TEXT,
                    core_cast TEXT,
                    theme_color VARCHAR(20),
                    run_id VARCHAR(36) REFERENCES analysis_runs (run_id) ON DELETE CASCADE
                )
                """
            )
        )
        connection.execute(
            text(
                """
                CREATE TABLE book_case_states (
                    case_id VARCHAR(64) PRIMARY KEY REFERENCES book_cases (case_id) ON DELETE CASCADE,
                    state VARCHAR(20) NOT NULL,
                    contributions JSONB NOT NULL
                )
                """
            )
        )
        for table in ("graph_facts", "event_nodes", "event_edges"):
            connection.execute(
                text(
                    f"ALTER TABLE {table} ADD CONSTRAINT fk_{table}_annotation_legacy "
                    f"FOREIGN KEY (annotation_id) REFERENCES chapter_annotations (annotation_id) ON DELETE CASCADE"
                )
            )
    try:
        yield engine
    finally:
        engine.dispose()
        with parent.begin() as connection:
            connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
            connection.execute(text(f'DROP SCHEMA IF EXISTS "{schema}_turn_outputs_archive" CASCADE'))


def _seed_novel_and_run(engine) -> str:
    novel_id, run_id = uuid4().hex[:8], str(uuid4())
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO novels (novel_id, filename, file_path, file_size, title) "
                "VALUES (:novel_id, 'n.txt', 'tests/n.txt', 10, '合并演练')"
            ),
            {"novel_id": novel_id},
        )
        connection.execute(
            text(
                "INSERT INTO analysis_runs (run_id, novel_id, source_path, title, status, progress, current, "
                "total, task_kind, cancel_requested) "
                "VALUES (:run_id, :novel_id, 'test', '合并演练', 'completed', 0.0, 0, 100, 'analysis', false)"
            ),
            {"run_id": run_id, "novel_id": novel_id},
        )
    return run_id


def test_merge_migration_archives_sources_and_merges_rows(pre_merge_engine):
    engine = pre_merge_engine
    run_id = _seed_novel_and_run(engine)
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO agent_invocations (run_id, task_type, chapter_id, work_id, role, execution_id, "
                "attempt_number, model_name, status, started_at, finished_at) "
                "VALUES (:run_id, 'annotation', 1, 'work-1', 'solo', 'exec-ok', 1, 'test-model', "
                "'success', now(), now())"
            ),
            {"run_id": run_id},
        )
        connection.execute(
            text(
                "INSERT INTO agent_invocations (run_id, task_type, chapter_id, attempt_number, model_name, "
                "status, final_error, started_at, finished_at) "
                "VALUES (:run_id, 'diagnosis', NULL, 1, 'test-model', 'error', 'dispatch failed', "
                "now(), now())"
            ),
            {"run_id": run_id},
        )
        connection.execute(
            text(
                "INSERT INTO agent_turns (invocation_id, turn_index, status, raw_response, context_summary, "
                "request_messages, timing_notes, model_ms, started_at, finished_at) "
                "VALUES (1, 1, 'success', '{}', '{}', "
                '\'[{"role":"user","content":"问"}]\', \'[]\', 120, now(), now())'
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
                "accounting_source, created_at, run_id, agent_turn_id) "
                "SELECT novel_id, 'annotation', 'agent', 'test-model', 9, 12, 'reported', now(), :run_id, id "
                "FROM agent_invocations, novels WHERE agent_invocations.execution_id = 'exec-ok' LIMIT 1"
            ),
            {"run_id": run_id},
        )
        connection.execute(
            text(
                "INSERT INTO token_usage (novel_id, task_type, call_type, model, prompt_tokens, total_tokens, "
                "accounting_source, created_at, run_id) "
                "SELECT novel_id, 'embedding', 'local', 'test-embed', 5, 5, 'reported', now(), :run_id "
                "FROM novels LIMIT 1"
            ),
            {"run_id": run_id},
        )
        connection.execute(
            text(
                "INSERT INTO chapter_annotations (annotation_id, run_id, chapter_id, payload, "
                "role, invocation_id, work_id) "
                "VALUES ('ann-1', :run_id, 1, "
                "'{\"metrics\": {\"summary\": \"出门\"}}', 'solo', 'exec-ok', 'work-1')"
            ),
            {"run_id": run_id},
        )
        connection.execute(
            text(
                "INSERT INTO cloud_analysis (novel_id, genre_labels, focus_structure, focus_characters, run_id) "
                "SELECT novel_id, '[\"旧标签\"]', 'dual', '[\"旧角色\"]', :run_id FROM novels"
            ),
            {"run_id": run_id},
        )
        connection.execute(
            text(
                "INSERT INTO cloud_analysis (novel_id, genre_labels, focus_structure, focus_characters, run_id) "
                "SELECT novel_id, '[\"新标签\"]', 'dual', '[\"新角色\"]', :run_id FROM novels"
            ),
            {"run_id": run_id},
        )
        connection.execute(
            text(
                "INSERT INTO book_cases (case_id, run_id, description, created_at) "
                "VALUES ('case-1', :run_id, '旧信用途', now())"
            ),
            {"run_id": run_id},
        )
        connection.execute(
            text(
                "INSERT INTO book_case_states (case_id, state, contributions) "
                'VALUES (\'case-1\', \'resolved\', \'{"work-1": {"invocation_id": "exec-ok", "deliveries": []}}\')'
            )
        )

    with engine.connect() as connection:
        plan = migration_plan(connection)
    assert plan["already_migrated"] is False
    with engine.begin() as connection:
        counts = apply_migration(connection)

    inspector = inspect(engine)
    assert counts["model_turns"] == {"agent_turn": 1, "usage": 1, "attempt_error": 1}
    assert counts["analysis_outputs"] == {"chapter_annotation": 1, "agent_analysis": 1}
    for table in (
        "agent_invocations",
        "agent_turns",
        "token_usage",
        "audit_messages",
        "chapter_annotations",
        "cloud_analysis",
        "book_case_states",
    ):
        assert not inspector.has_table(table), table
    assert inspector.has_table("agent_tool_calls")
    archive = plan["archive_schema"]
    assert inspector.has_table("agent_turns", schema=archive)
    assert inspector.has_table("chapter_annotations", schema=archive)

    with engine.connect() as connection:
        turn = connection.execute(
            text(
                "SELECT row_kind, task_type, call_type, model, execution_id, turn_index, total_tokens, "
                "accounting_source, prompt_tokens FROM model_turns WHERE id = 1"
            )
        ).one()
        assert turn.row_kind == "agent_turn"
        assert turn.call_type == "agent"
        assert turn.execution_id == "exec-ok"
        assert turn.total_tokens == 12 and turn.prompt_tokens == 9
        usage = connection.execute(text("SELECT task_type, model FROM model_turns WHERE row_kind = 'usage'")).one()
        assert usage.task_type == "embedding"
        attempt = connection.execute(
            text("SELECT task_type, status, error FROM model_turns WHERE row_kind = 'attempt_error'")
        ).one()
        assert attempt.status == "error" and attempt.error == "dispatch failed"
        tool = connection.execute(text("SELECT count(*) FROM agent_tool_calls")).scalar_one()
        assert tool == 1
        outputs = connection.execute(text("SELECT kind, output_id, payload FROM analysis_outputs ORDER BY kind")).all()
        chapter_row = next(row for row in outputs if row.kind == "chapter_annotation")
        assert chapter_row.output_id == "ann-1"
        agent_row = next(row for row in outputs if row.kind == "agent_analysis")
        assert agent_row.payload["genre_labels"] == ["新标签"]
        case = connection.execute(text("SELECT state, contributions FROM book_cases WHERE case_id = 'case-1'")).one()
        assert case.state == "resolved" and case.contributions["work-1"]["invocation_id"] == "exec-ok"


def test_merge_migration_refuses_rerun_and_unmigrated_orphan_usage(pre_merge_engine):
    engine = pre_merge_engine
    _seed_novel_and_run(engine)
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO token_usage (novel_id, task_type, call_type, model, prompt_tokens, total_tokens, "
                "accounting_source, created_at, run_id) "
                "SELECT novel_id, 'embedding', 'local', 'test-embed', 5, 5, 'reported', now(), NULL FROM novels LIMIT 1"
            ),
        )
    with pytest.raises(ValueError, match="无 run 归属"):
        with engine.begin() as connection:
            # 异常必须穿透事务边界才能回滚建表，pytest.raises 需包在事务外层
            apply_migration(connection)

    with engine.begin() as connection:
        connection.execute(text("DELETE FROM token_usage WHERE run_id IS NULL"))

    with engine.begin() as connection:
        apply_migration(connection)
    with engine.connect() as connection:
        plan = migration_plan(connection)
    assert plan["already_migrated"] is True
    with pytest.raises(ValueError, match="无需重复迁移"):
        with engine.begin() as connection:
            apply_migration(connection)


@pytest.mark.parametrize("status", ["pending", "running", "cancelling"])
def test_merge_migration_refuses_active_runs_before_ddl(pre_merge_engine: Engine, status: str) -> None:
    run_id = _seed_novel_and_run(pre_merge_engine)
    with pre_merge_engine.begin() as connection:
        connection.execute(
            text("UPDATE analysis_runs SET status = :status WHERE run_id = :run_id"),
            {"status": status, "run_id": run_id},
        )
    with pytest.raises(ValueError, match="分析任务"):
        with pre_merge_engine.begin() as connection:
            apply_migration(connection)
    inspector = inspect(pre_merge_engine)
    assert not inspector.has_table("model_turns")
    with pre_merge_engine.connect() as connection:
        plan = migration_plan(connection)
    assert plan["active_run_ids"] == [run_id]
    assert not inspector.has_schema(plan["archive_schema"])


@pytest.mark.parametrize(
    ("change", "error"),
    [
        ("CREATE TABLE model_turns (id INTEGER)", "只有部分存在"),
        ("ALTER TABLE chapter_annotations DROP COLUMN actual_input", "源字段"),
        ("DROP TABLE audit_messages", "源表缺失"),
        ("DROP TABLE graph_facts", "源表缺失"),
        ("ALTER TABLE analysis_runs DROP COLUMN status", "源字段"),
    ],
)
def test_merge_migration_refuses_incompatible_shapes_before_ddl(
    pre_merge_engine: Engine, change: str, error: str
) -> None:
    with pre_merge_engine.begin() as connection:
        connection.execute(text(change))
    with pytest.raises(ValueError, match=error):
        with pre_merge_engine.begin() as connection:
            apply_migration(connection)
    with pre_merge_engine.connect() as connection:
        plan = migration_plan(connection)
    assert not inspect(pre_merge_engine).has_schema(plan["archive_schema"])
    assert not inspect(pre_merge_engine).has_table("analysis_outputs")


def test_merge_migration_refuses_existing_archive(pre_merge_engine: Engine) -> None:
    with pre_merge_engine.begin() as connection:
        plan = migration_plan(connection)
        archive = plan["archive_schema"]
        connection.execute(text(f'CREATE SCHEMA "{archive}"'))
        connection.execute(text(f'CREATE TABLE "{archive}".restore_evidence (id INTEGER)'))
    with pytest.raises(ValueError, match="拒绝覆盖"):
        with pre_merge_engine.begin() as connection:
            apply_migration(connection)
    inspector = inspect(pre_merge_engine)
    assert inspector.has_table("restore_evidence", schema=archive)
    assert not inspector.has_table("model_turns")


def test_merge_migration_cli_applies_one_transaction(
    pre_merge_engine: Engine,
    test_database_url: str,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _seed_novel_and_run(pre_merge_engine)
    with pre_merge_engine.connect() as connection:
        schema = connection.execute(text("SELECT current_schema()")).scalar_one()
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "migrate_turn_outputs_merge",
            "--database-env",
            "TEST_DATABASE",
            "--schema",
            schema,
            "--apply",
            "--expect-database",
            make_url(test_database_url).database,
        ],
    )
    main()
    assert '"applied": true' in capsys.readouterr().out
    assert inspect(pre_merge_engine).has_table("model_turns")
    assert inspect(pre_merge_engine).has_table("analysis_outputs")
    result = inspect_current_schema(pre_merge_engine, schema=schema)
    assert result["ready"] is True, result


def test_merge_migration_cli_refuses_wrong_database(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "argv", ["migrate_turn_outputs_merge", "--apply", "--expect-database", "wrong_database"])
    with pytest.raises(ValueError, match="匹配的数据库名"):
        main()
