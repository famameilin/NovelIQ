"""Query DB snapshot for a run.

2026-05-02: restored as a standalone helper for resource monitoring.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from dotenv import load_dotenv
from sqlalchemy import text

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.storage.db import get_engine  # noqa: E402


def main() -> int:
    if len(sys.argv) != 2:
        print("usage: query_run_db_snapshot.py <run_id>", file=sys.stderr)
        return 2

    run_id = sys.argv[1]
    load_dotenv(REPO_ROOT / ".env")

    engine = get_engine()
    with engine.connect() as connection:
        database_size = connection.execute(text("SELECT pg_database_size(current_database())")).scalar_one()
        row = connection.execute(
            text(
                """
                SELECT status, stage, sub_stage, current, total, message
                FROM analysis_runs
                WHERE run_id = :run_id
                """
            ),
            {"run_id": run_id},
        ).mappings().first()

    payload: dict[str, object] = {
        "database_size_bytes": int(database_size),
        "status": None,
        "stage": None,
        "sub_stage": None,
        "current": None,
        "total": None,
        "message": None,
    }
    if row is not None:
        payload.update(
            {
                "status": row["status"],
                "stage": row["stage"],
                "sub_stage": row["sub_stage"],
                "current": row["current"],
                "total": row["total"],
                "message": row["message"],
            }
        )

    print(json.dumps(payload, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
