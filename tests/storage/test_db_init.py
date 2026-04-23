from unittest.mock import patch

from sqlalchemy import text

from src.storage.db import init_db
from src.storage.db import get_session_factory


def test_init_db_excludes_level3_tables_by_default() -> None:
    with (
        patch("src.storage.db.get_engine", return_value=object()),
        patch("src.storage.models.Base.metadata.create_all") as mock_create_all,
        patch("src.storage.db._ensure_runtime_schema") as mock_ensure_runtime_schema,
    ):
        init_db()

    table_names = [table.name for table in mock_create_all.call_args.kwargs["tables"]]
    assert "chunk_embeddings" not in table_names
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
    mock_ensure_runtime_schema.assert_called_once()


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
