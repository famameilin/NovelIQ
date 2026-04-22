from unittest.mock import patch

from src.storage.db import init_db


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
