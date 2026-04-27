from __future__ import annotations

import os
import sys
from pathlib import Path

from dotenv import load_dotenv
from sqlalchemy import Connection, create_engine, text

project_root = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(project_root))

from src.storage.models import Base  # noqa: E402


def _constraint_exists(connection: Connection, table_name: str, constraint_name: str) -> bool:
    return bool(
        connection.execute(
            text(
                """
                SELECT 1
                FROM information_schema.table_constraints
                WHERE table_schema = current_schema()
                  AND table_name = :table_name
                  AND constraint_name = :constraint_name
                LIMIT 1
                """
            ),
            {"table_name": table_name, "constraint_name": constraint_name},
        ).scalar_one_or_none()
    )


def _drop_constraint_if_exists(connection: Connection, table_name: str, constraint_name: str) -> None:
    if not _constraint_exists(connection, table_name, constraint_name):
        return
    connection.execute(text(f"ALTER TABLE {table_name} DROP CONSTRAINT {constraint_name}"))


def _ensure_analysis_related_foreign_keys(connection: Connection) -> None:
    constraint_specs = [
        {
            "table": "analysis_runs",
            "name": "analysis_runs_novel_id_fkey",
            "ddl": (
                "ALTER TABLE analysis_runs "
                "ADD CONSTRAINT analysis_runs_novel_id_fkey "
                "FOREIGN KEY (novel_id) REFERENCES novels(novel_id) ON DELETE RESTRICT"
            ),
        },
        {
            "table": "disambig_checkpoint",
            "name": "disambig_checkpoint_run_id_fkey",
            "ddl": (
                "ALTER TABLE disambig_checkpoint "
                "ADD CONSTRAINT disambig_checkpoint_run_id_fkey "
                "FOREIGN KEY (run_id) REFERENCES analysis_runs(run_id) ON DELETE CASCADE"
            ),
        },
        {
            "table": "chunk_locations",
            "name": "chunk_locations_chunk_id_run_id_fkey",
            "ddl": (
                "ALTER TABLE chunk_locations "
                "ADD CONSTRAINT chunk_locations_chunk_id_run_id_fkey "
                "FOREIGN KEY (chunk_id, run_id) REFERENCES chunks(chunk_id, run_id) ON DELETE CASCADE"
            ),
        },
        {
            "table": "chunk_locations",
            "name": "chunk_locations_novel_id_fkey",
            "ddl": (
                "ALTER TABLE chunk_locations "
                "ADD CONSTRAINT chunk_locations_novel_id_fkey "
                "FOREIGN KEY (novel_id) REFERENCES novels(novel_id) ON DELETE RESTRICT"
            ),
        },
        {
            "table": "cloud_analysis",
            "name": "cloud_analysis_novel_id_fkey",
            "ddl": (
                "ALTER TABLE cloud_analysis "
                "ADD CONSTRAINT cloud_analysis_novel_id_fkey "
                "FOREIGN KEY (novel_id) REFERENCES novels(novel_id) ON DELETE RESTRICT"
            ),
        },
        {
            "table": "global_context",
            "name": "global_context_novel_id_fkey",
            "ddl": (
                "ALTER TABLE global_context "
                "ADD CONSTRAINT global_context_novel_id_fkey "
                "FOREIGN KEY (novel_id) REFERENCES novels(novel_id) ON DELETE RESTRICT"
            ),
        },
        {
            "table": "graph_relation_events",
            "name": "graph_relation_events_chunk_id_run_id_fkey",
            "ddl": (
                "ALTER TABLE graph_relation_events "
                "ADD CONSTRAINT graph_relation_events_chunk_id_run_id_fkey "
                "FOREIGN KEY (chunk_id, run_id) REFERENCES chunks(chunk_id, run_id) ON DELETE CASCADE"
            ),
        },
        {
            "table": "token_usage",
            "name": "token_usage_novel_id_fkey",
            "ddl": (
                "ALTER TABLE token_usage "
                "ADD CONSTRAINT token_usage_novel_id_fkey "
                "FOREIGN KEY (novel_id) REFERENCES novels(novel_id) ON DELETE RESTRICT"
            ),
        },
    ]

    for spec in constraint_specs:
        if _constraint_exists(connection, spec["table"], spec["name"]):
            continue
        connection.execute(text(spec["ddl"]))


def _ensure_graph_projection_contract_schema(connection: Connection) -> None:
    connection.execute(
        text(
            "ALTER TABLE analysis_runs "
            "ADD COLUMN IF NOT EXISTS graph_projection_version INTEGER NOT NULL DEFAULT 1"
        )
    )
    connection.execute(
        text(
            "ALTER TABLE analysis_runs "
            "ADD COLUMN IF NOT EXISTS timeline_contract_version INTEGER NOT NULL DEFAULT 1"
        )
    )
    connection.execute(text("ALTER TABLE analysis_runs ALTER COLUMN graph_projection_version SET DEFAULT 2"))
    connection.execute(text("ALTER TABLE analysis_runs ALTER COLUMN timeline_contract_version SET DEFAULT 2"))
    connection.execute(
        text(
            """
            UPDATE graph_relation_events
            SET change_type = CASE
                WHEN change_type = '无变化' THEN '强化'
                WHEN change_type = '波动' THEN '强化'
                ELSE change_type
            END
            WHERE change_type IN ('无变化', '波动')
            """
        )
    )
    _drop_constraint_if_exists(connection, "graph_relation_events", "ck_graph_relation_events_change_type")
    _drop_constraint_if_exists(connection, "graph_relation_events", "ck_graph_relation_events_change_type_v2")
    connection.execute(
        text(
            "ALTER TABLE graph_relation_events "
            "ADD CONSTRAINT ck_graph_relation_events_change_type_v2 "
            "CHECK (change_type IN ('新建', '强化', '弱化', '断裂'))"
        )
    )


def _apply_schema_upgrade(database_url: str) -> None:
    engine = create_engine(database_url)
    print(f"\n=== Upgrading schema: {database_url} ===")
    Base.metadata.create_all(bind=engine)

    statements = [
        "ALTER TABLE chunk_relations ADD COLUMN IF NOT EXISTS evidence TEXT",
        "ALTER TABLE chunk_relations ADD COLUMN IF NOT EXISTS confidence DOUBLE PRECISION",
        "ALTER TABLE chunk_relations ADD COLUMN IF NOT EXISTS source_model VARCHAR(100)",
        "ALTER TABLE chunk_relations ADD COLUMN IF NOT EXISTS projection_status VARCHAR(20)",
        "ALTER TABLE chunk_relations ADD COLUMN IF NOT EXISTS projected_at TIMESTAMP",
        "ALTER TABLE chunk_relations ADD COLUMN IF NOT EXISTS projection_error TEXT",
        (
            "CREATE INDEX IF NOT EXISTS idx_chunk_relations_projection_status "
            "ON chunk_relations (run_id, projection_status)"
        ),
    ]

    with engine.begin() as conn:
        for sql in statements:
            conn.execute(text(sql))
        _ensure_analysis_related_foreign_keys(conn)
        _ensure_graph_projection_contract_schema(conn)

    print("Graph projection schema upgrade completed.")


def main() -> None:
    load_dotenv(project_root / ".env")
    db_urls = []
    for name in ("DATABASE_URL", "TEST_DATABASE_URL"):
        value = os.getenv(name)
        if value:
            db_urls.append(value)

    if not db_urls:
        raise RuntimeError("DATABASE_URL or TEST_DATABASE_URL must be set")

    for url in db_urls:
        _apply_schema_upgrade(url)


if __name__ == "__main__":
    main()
