from unittest.mock import MagicMock, patch

from sqlalchemy import text

from src.storage.db import _ensure_runtime_schema, get_session_factory, init_db
from src.storage.models import Base


def test_continuity_schema_uses_direct_graph_persistence_contract() -> None:
    """2026-08-06 用于验证 ORM 只保留图节点目标和直接图来源结构"""
    assert "continuity_facts" not in Base.metadata.tables
    assert "graph_fact_versions" not in Base.metadata.tables

    mapping_columns = Base.metadata.tables["case_resolution_mappings"].columns
    source_columns = Base.metadata.tables["graph_fact_sources"].columns
    entity_columns = Base.metadata.tables["graph_entities"].columns
    assert "target_graph_node_id" in mapping_columns
    assert "target_fact_id" not in mapping_columns
    assert "continuity_fact_id" not in source_columns
    assert "is_representative" in entity_columns


def test_init_db_excludes_level3_tables_by_default() -> None:
    with (
        patch("src.storage.db.get_engine", return_value=object()),
        patch("src.storage.models.Base.metadata.create_all") as mock_create_all,
        patch("src.storage.db._ensure_runtime_schema") as mock_ensure_runtime_schema,
    ):
        init_db()

    table_names = [table.name for table in mock_create_all.call_args.kwargs["tables"]]
    assert "chunk_embeddings" not in table_names
    assert "paragraph_embeddings" not in table_names
    mock_ensure_runtime_schema.assert_called_once()


def test_init_db_can_include_level3_tables() -> None:
    with (
        patch("src.storage.db.get_engine", return_value=object()),
        patch("src.storage.models.Base.metadata.create_all") as mock_create_all,
        patch("src.storage.db._ensure_runtime_schema") as mock_ensure_runtime_schema,
    ):
        init_db(include_level3_tables=True)

    table_names = [table.name for table in mock_create_all.call_args.kwargs["tables"]]
    assert "chunk_embeddings" in table_names
    assert "paragraph_embeddings" in table_names
    mock_ensure_runtime_schema.assert_called_once()


def test_init_db_runs_focus_contract_guard_after_runtime_schema() -> None:
    """
    验证 init_db() 主链路会在 create_all 和 runtime schema 之后执行 focus-contract fail-closed 校验。

    创建时间: 2026-04-27
    任务: fix-focus-contract-runtime-schema-conflict
    说明: 这条测试专门覆盖 init_db() 的真实调用顺序，避免后续再把 focus-contract 校验从主链路上绕开。
    """
    fake_engine = object()
    with (
        patch("src.storage.db.get_engine", return_value=fake_engine),
        patch("src.storage.models.Base.metadata.create_all"),
        patch("src.storage.db._ensure_runtime_schema") as mock_ensure_runtime_schema,
        patch("src.storage.db._assert_focus_contract_schema") as mock_assert_focus_contract_schema,
    ):
        init_db()

    mock_ensure_runtime_schema.assert_called_once_with(fake_engine)
    mock_assert_focus_contract_schema.assert_called_once_with(fake_engine)


def test_runtime_schema_does_not_backfill_legacy_focus_contract_columns() -> None:
    """
    验证 PostgreSQL runtime schema 不会再补旧 protagonist-contract 列。

    创建时间: 2026-04-27
    任务: fix-focus-contract-runtime-schema-conflict
    说明: 当前主线以 focus-contract fail-closed 为准；
          若 runtime schema 仍偷偷补 `protagonist/main_characters/core_cast/theme_color`，就会和启动校验自相矛盾。
    """
    fake_engine = MagicMock()
    fake_engine.dialect.name = "postgresql"
    fake_conn = MagicMock()
    fake_engine.begin.return_value.__enter__.return_value = fake_conn

    with (
        patch("src.storage.db._table_exists", return_value=False),
        patch("src.storage.db._ensure_analysis_related_foreign_keys"),
    ):
        _ensure_runtime_schema(fake_engine)

    executed_sql = [str(call.args[0]) for call in fake_conn.execute.call_args_list]

    expected_foreshadow_sql = "ALTER TABLE cloud_analysis ADD COLUMN IF NOT EXISTS foreshadow_expectation"
    expected_thread_confidence_sql = "ALTER TABLE foreshadowing_threads ADD COLUMN IF NOT EXISTS confidence"
    expected_representative_sql = "ALTER TABLE graph_entities ADD COLUMN IF NOT EXISTS is_representative"

    assert any(expected_foreshadow_sql in sql for sql in executed_sql)
    assert any(expected_thread_confidence_sql in sql for sql in executed_sql)
    assert any(expected_representative_sql in sql for sql in executed_sql)
    assert not any("ALTER TABLE cloud_analysis ADD COLUMN IF NOT EXISTS protagonist" in sql for sql in executed_sql)
    assert not any("ALTER TABLE cloud_analysis ADD COLUMN IF NOT EXISTS main_characters" in sql for sql in executed_sql)
    assert not any("ALTER TABLE cloud_analysis ADD COLUMN IF NOT EXISTS core_cast" in sql for sql in executed_sql)
    assert not any("ALTER TABLE cloud_analysis ADD COLUMN IF NOT EXISTS theme_color" in sql for sql in executed_sql)


def test_analysis_related_foreign_keys_exist_in_runtime_schema() -> None:
    """
    2026-08-05 用于验证测试库已具备章节标注连续性与数据库图主链外键
    """
    expected_constraints = {
        "analysis_runs_novel_id_fkey",
        "chapter_annotations_run_id_fkey",
        "case_pool_cases_run_id_fkey",
        "graph_facts_run_id_fkey",
        "graph_fact_sources_graph_fact_id_fkey",
        "cloud_analysis_novel_id_fkey",
        "global_context_novel_id_fkey",
        "graph_relation_events_chunk_id_run_id_fkey",
        "token_usage_novel_id_fkey",
    }

    with get_session_factory()() as session:
        rows = session.execute(
            text(
                """
                SELECT constraint_name
                FROM information_schema.table_constraints
                WHERE table_schema = current_schema()
                  AND constraint_type = 'FOREIGN KEY'
                  AND constraint_name = ANY(:constraint_names)
                """
            ),
            {"constraint_names": list(expected_constraints)},
        ).scalars().all()

    assert set(rows) == expected_constraints


def test_timeline_contract_runtime_schema_no_longer_creates_version_columns() -> None:
    """
    验证 pytest fresh schema 不再创建 timeline / graph projection 版本列。

    创建时间: 2026-04-28
    任务: remove-timeline-version-columns
    说明: 当前主线不再依赖 run-level version 标签 gate；
          fresh schema 下若还出现这两个列，说明旧兼容层又被带回来了。
    """

    with get_session_factory()() as session:
        column_rows = session.execute(
            text(
                """
                SELECT table_name, column_name
                FROM information_schema.columns
                WHERE table_schema = current_schema()
                  AND table_name = 'analysis_runs'
                  AND column_name IN ('graph_projection_version', 'timeline_contract_version')
                """
            )
        ).all()
        constraints = session.execute(
            text(
                """
                SELECT constraint_name
                FROM information_schema.table_constraints
                WHERE table_schema = current_schema()
                  AND table_name = 'graph_relation_events'
                  AND constraint_name = 'ck_graph_relation_events_change_type_v2'
                """
            )
        ).scalars().all()

    assert column_rows == []
    assert constraints == ["ck_graph_relation_events_change_type_v2"]


def test_stage_summaries_metadata_has_single_run_id_foreign_key() -> None:
    """
    创建时间: 2026-04-27
    任务: fix-stage-summary-orm-duplicate-fk
    说明: StageSummary.run_id 只应在 ORM 元数据里声明一次外键；
          否则 schema diff 会持续把同义 FK 误报成元数据漂移。
    """
    stage_summaries = Base.metadata.tables["stage_summaries"]
    foreign_keys = sorted(
        (
            tuple(column.name for column in constraint.columns),
            tuple(element.column.table.name for element in constraint.elements),
            tuple(element.column.name for element in constraint.elements),
            constraint.ondelete,
        )
        for constraint in stage_summaries.foreign_key_constraints
    )

    assert foreign_keys == [
        (("run_id",), ("analysis_runs",), ("run_id",), "CASCADE"),
    ]
