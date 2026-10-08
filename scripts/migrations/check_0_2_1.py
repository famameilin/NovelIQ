"""0.2.1 发布前只读结构检查，不建表、不改写历史记录"""

from __future__ import annotations

import argparse
import json
import os
import re
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import Connection, Engine

from src.storage.database_url import resolve_database_url_from_env
from src.storage.models import Base


def inspect_current_schema(engine: Engine | Connection, *, schema: str = "public") -> dict[str, Any]:
    """核对当前 ORM 必需的字段与外键，动态向量表继续由专用入口管理"""
    inspector = inspect(engine)
    existing = set(inspector.get_table_names(schema=schema))
    required = {table.name: table for table in Base.metadata.sorted_tables if table.name != "paragraph_embeddings"}
    missing_tables = sorted(required.keys() - existing)
    missing_columns: dict[str, list[str]] = {}
    missing_foreign_keys: dict[str, list[str]] = {}
    for name, table in required.items():
        if name not in existing:
            continue
        columns = {column["name"] for column in inspector.get_columns(name, schema=schema)}
        missing = sorted(set(table.columns.keys()) - columns)
        if missing:
            missing_columns[name] = missing
        actual = {
            (
                tuple(fk["constrained_columns"]),
                fk.get("referred_schema") or schema,
                fk["referred_table"],
                tuple(fk["referred_columns"]),
            )
            for fk in inspector.get_foreign_keys(name, schema=schema)
        }
        for fk in table.foreign_key_constraints:
            expected = (
                tuple(element.parent.name for element in fk.elements),
                fk.referred_table.schema or schema,
                fk.referred_table.name,
                tuple(element.column.name for element in fk.elements),
            )
            if expected not in actual:
                missing_foreign_keys.setdefault(name, []).append(
                    f"{','.join(expected[0])} -> {expected[1]}.{expected[2]}({','.join(expected[3])})"
                )
    return {
        "ready": not missing_tables and not missing_columns and not missing_foreign_keys,
        "missing_tables": missing_tables,
        "missing_columns": missing_columns,
        "missing_foreign_keys": missing_foreign_keys,
    }


def main() -> int:
    load_dotenv(Path(__file__).resolve().parents[2] / ".env")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database-env", choices=("DATABASE", "TEST_DATABASE"), default="DATABASE")
    parser.add_argument("--schema", default=os.environ.get("DATABASE_SCHEMA", "public"))
    args = parser.parse_args()
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", args.schema):
        raise ValueError("非法 schema 名称")
    engine = create_engine(resolve_database_url_from_env(args.database_env), connect_args={"connect_timeout": 5})
    try:
        with engine.connect() as connection:
            connection.execute(text("SET TRANSACTION READ ONLY"))
            connection.execute(text("SET LOCAL statement_timeout='10s'"))
            result = inspect_current_schema(connection, schema=args.schema)
            print(json.dumps({"version": "0.2.1", "schema": args.schema, **result}, ensure_ascii=False, indent=2))
            return 0 if result["ready"] else 2
    finally:
        engine.dispose()


if __name__ == "__main__":
    raise SystemExit(main())
