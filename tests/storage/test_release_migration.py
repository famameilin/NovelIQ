"""0.1.0 → 0.1.1 升级登记的数据库安全边界"""

from __future__ import annotations

from uuid import uuid4

import pytest
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import make_url

from scripts.migrations.migrate_0_1_0_to_0_1_1 import migrate


def test_release_migration_preserves_legacy_data_and_is_idempotent(test_database_url: str) -> None:
    """运行任务阻断登记；完成后只写一次 ledger，历史证据与标签原值保留"""
    schema = f"release011_{uuid4().hex[:12]}"
    database = make_url(test_database_url).database
    assert database is not None
    engine = create_engine(test_database_url, connect_args={"connect_timeout": 5})
    definitions = (
        "CREATE TABLE analysis_runs (run_id text, status text)",
        "CREATE TABLE chapter_annotations (annotation_id text, run_id text, chapter_id integer, payload jsonb)",
        "CREATE TABLE chapters (chapter_id integer, run_id text, text text)",
        "CREATE TABLE cloud_analysis (id integer, run_id text, topic_labels text)",
        "CREATE TABLE event_edges (edge_id text, run_id text)",
        "CREATE TABLE event_nodes "
        "(event_id text, run_id text, annotation_id text, tree_id text, anchor_paragraph_ids jsonb)",
        "CREATE TABLE paragraphs (run_id text, paragraph_id integer, chapter_id integer)",
        "CREATE TABLE paragraph_topics (run_id text, paragraph_id integer, topic_id integer)",
        "CREATE TABLE topic_model_runs (run_id text, num_topics integer)",
    )
    try:
        with engine.begin() as connection:
            connection.execute(text(f'CREATE SCHEMA "{schema}"'))
            connection.execute(text(f'SET LOCAL search_path TO "{schema}"'))
            for definition in definitions:
                connection.execute(text(definition))
            connection.execute(text("INSERT INTO analysis_runs VALUES ('run-test', 'running')"))
            connection.execute(
                text("INSERT INTO chapter_annotations VALUES ('ann-test', 'run-test', 1, CAST(:payload AS jsonb))"),
                {"payload": '{"metrics":{},"events":[{"node_id":"evt-test"}]}'},
            )
            connection.execute(
                text(
                    "INSERT INTO event_nodes "
                    "VALUES ('evt-test','run-test','ann-test','tree-test',CAST('[1,2]' AS jsonb))"
                )
            )
            connection.execute(text("INSERT INTO cloud_analysis VALUES (1,'run-test','[\"旧标签\"]')"))

        dry_run = migrate(database_env="TEST_DATABASE", schema=schema, apply=False, expect_database=None)
        assert dry_run["active_run_ids"] == ["run-test"]
        assert dry_run["legacy_topic_label_run_ids"] == ["run-test"]
        assert dry_run["chapter_evidence_event_count"] == 1
        with pytest.raises(RuntimeError, match="运行中的分析任务"):
            migrate(database_env="TEST_DATABASE", schema=schema, apply=True, expect_database=database)
        with engine.begin() as connection:
            assert "noveliq_release_migrations" not in inspect(connection).get_table_names(schema=schema)
            connection.execute(text(f'UPDATE "{schema}".analysis_runs SET status = :status'), {"status": "completed"})

        first = migrate(database_env="TEST_DATABASE", schema=schema, apply=True, expect_database=database)
        second = migrate(database_env="TEST_DATABASE", schema=schema, apply=True, expect_database=database)
        assert first["applied_now"] is True
        assert second["already_applied"] is True
        assert second["applied_now"] is False
        with engine.connect() as connection:
            connection.execute(text(f'SET LOCAL search_path TO "{schema}"'))
            assert connection.execute(text("SELECT count(*) FROM noveliq_release_migrations")).scalar_one() == 1
            assert connection.execute(text("SELECT topic_labels FROM cloud_analysis")).scalar_one() == '["旧标签"]'
            assert connection.execute(text("SELECT anchor_paragraph_ids FROM event_nodes")).scalar_one() == [1, 2]
    finally:
        with engine.begin() as connection:
            connection.execute(text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
        engine.dispose()
