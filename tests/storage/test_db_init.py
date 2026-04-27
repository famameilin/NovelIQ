from unittest.mock import MagicMock, patch

from sqlalchemy import text

from src.storage.db import _ensure_runtime_schema, get_session_factory, init_db
from src.storage.models import Base


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
    创建者: Codex
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
    创建者: Codex
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

    assert any(expected_foreshadow_sql in sql for sql in executed_sql)
    assert not any("ALTER TABLE cloud_analysis ADD COLUMN IF NOT EXISTS protagonist" in sql for sql in executed_sql)
    assert not any("ALTER TABLE cloud_analysis ADD COLUMN IF NOT EXISTS main_characters" in sql for sql in executed_sql)
    assert not any("ALTER TABLE cloud_analysis ADD COLUMN IF NOT EXISTS core_cast" in sql for sql in executed_sql)
    assert not any("ALTER TABLE cloud_analysis ADD COLUMN IF NOT EXISTS theme_color" in sql for sql in executed_sql)


def test_analysis_related_foreign_keys_exist_in_runtime_schema() -> None:
    """
    验证测试库初始化后已具备新增的分析链路外键。

    创建时间: 2026-04-22
    创建者: Codex
    任务: fix-analysis-related-foreign-keys
    说明: 这里直接查当前测试 schema 的 pg 元数据，确保缺失的 8 条外键已经真正落到数据库。
    """
    expected_constraints = {
        "analysis_runs_novel_id_fkey",
        "disambig_checkpoint_run_id_fkey",
        "chunk_locations_chunk_id_run_id_fkey",
        "chunk_locations_novel_id_fkey",
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


def test_timeline_contract_runtime_schema_columns_and_constraints_exist() -> None:
    """
    验证 pytest fresh schema 已具备时间轴合同重构所需的版本列与 change_type 约束。

    创建时间: 2026-04-27
    修改者: Codex
    任务: timeline-contract-db-migration
    说明: 当前主线不再兼容旧库 runtime/migration 收口；
          这里验证的是 pytest 会话下 freshly created 的测试 schema，必须与新 timeline contract 保持一致。
    """

    expected_columns = {
        ("analysis_runs", "graph_projection_version"),
        ("analysis_runs", "timeline_contract_version"),
    }

    with get_session_factory()() as session:
        column_rows = session.execute(
            text(
                """
                SELECT table_name, column_name
                FROM information_schema.columns
                WHERE table_schema = current_schema()
                  AND (
                    (
                        table_name = 'analysis_runs'
                        AND column_name IN ('graph_projection_version', 'timeline_contract_version')
                    )
                  )
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

    assert {(row.table_name, row.column_name) for row in column_rows} == expected_columns
    assert constraints == ["ck_graph_relation_events_change_type_v2"]


def test_timeline_contract_version_columns_have_server_defaults() -> None:
    """
    验证 analysis_runs 的 timeline 重构版本列在数据库层具有默认值。

    创建时间: 2026-04-27
    修改者: Codex
    任务: timeline-contract-db-migration
    说明: 仅有 ORM 的 Python default 还不够；测试里有原生 SQL 直接写 analysis_runs，
          若数据库列没有 server default，就会在未显式带版本字段时触发 NOT NULL 错误。
    """

    with get_session_factory()() as session:
        rows = session.execute(
            text(
                """
                SELECT column_name, column_default
                FROM information_schema.columns
                WHERE table_schema = current_schema()
                  AND table_name = 'analysis_runs'
                  AND column_name IN ('graph_projection_version', 'timeline_contract_version')
                ORDER BY column_name
                """
            )
        ).all()

    defaults = {row.column_name: str(row.column_default or "") for row in rows}
    assert "2" in defaults["graph_projection_version"]
    assert "2" in defaults["timeline_contract_version"]


def test_stage_summaries_metadata_has_single_run_id_foreign_key() -> None:
    """
    创建时间: 2026-04-27
    创建者: Codex
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
