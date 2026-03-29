from __future__ import annotations

import os
import sys
from pathlib import Path

from dotenv import load_dotenv
from sqlalchemy import create_engine, text

project_root = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(project_root))

from src.storage.models import Base  # noqa: E402


def _apply_schema_upgrade(database_url: str) -> None:
    engine = create_engine(database_url)
    print(f"\n=== Upgrading schema: {database_url} ===")
    Base.metadata.create_all(bind=engine)

    statements = [
        "ALTER TABLE disambig_checkpoint ADD COLUMN IF NOT EXISTS last_annotated_chunk INTEGER",
        "ALTER TABLE disambig_checkpoint ADD COLUMN IF NOT EXISTS last_projected_chunk INTEGER",
        "ALTER TABLE disambig_checkpoint ADD COLUMN IF NOT EXISTS projection_interval INTEGER",
        "ALTER TABLE chunk_relations ADD COLUMN IF NOT EXISTS evidence TEXT",
        "ALTER TABLE chunk_relations ADD COLUMN IF NOT EXISTS confidence DOUBLE PRECISION",
        "ALTER TABLE chunk_relations ADD COLUMN IF NOT EXISTS source_model VARCHAR(100)",
        "ALTER TABLE chunk_relations ADD COLUMN IF NOT EXISTS projection_status VARCHAR(20)",
        "ALTER TABLE chunk_relations ADD COLUMN IF NOT EXISTS projected_at TIMESTAMP",
        "ALTER TABLE chunk_relations ADD COLUMN IF NOT EXISTS projection_error TEXT",
        "CREATE INDEX IF NOT EXISTS idx_chunk_relations_projection_status ON chunk_relations (run_id, projection_status)",
    ]

    with engine.begin() as conn:
        for sql in statements:
            conn.execute(text(sql))

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
