"""
修复开发库与测试库的关键 schema 漂移。

设计原则:
- 开发库只做原地、可验证的定点修复。
- 测试库允许重建 public schema，因为它应是可抛弃环境。
- 运行时兜底只保留非破坏性修复；删除旧列、重建测试库这类动作只在显式脚本里执行。
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from dotenv import load_dotenv
from loguru import logger
from sqlalchemy import Engine, create_engine, inspect, text

project_root = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(project_root))

env_path = project_root / ".env"
load_dotenv(env_path)

from src.storage import db as db_module  # noqa: E402


EXPECTED_RUNTIME_INDEXES: list[tuple[str, str]] = [
    ("idx_chunk_curves_run_id", "CREATE INDEX IF NOT EXISTS idx_chunk_curves_run_id ON chunk_curves (run_id)"),
    ("idx_chunk_embeddings_run_id", "CREATE INDEX IF NOT EXISTS idx_chunk_embeddings_run_id ON chunk_embeddings (run_id)"),
]

REDUNDANT_INDEXES: list[str] = [
    "ix_analysis_runs_novel_id",
    "ix_analysis_runs_status",
    "ix_character_appearances_chunk_id",
    "ix_character_appearances_raw_name",
    "ix_character_appearances_run_id",
    "ix_chunk_annotation_run_id",
    "ix_chunk_characters_chunk_id",
    "ix_chunk_characters_name",
    "ix_chunk_characters_run_id",
    "ix_chunk_dialogues_chunk_id",
    "ix_chunk_dialogues_run_id",
    "ix_chunk_foreshadowing_run_id",
    "ix_chunk_locations_chunk_id",
    "ix_chunk_locations_novel_id",
    "ix_chunk_locations_run_id",
    "ix_chunk_relations_chunk_id",
    "ix_chunk_relations_run_id",
    "ix_chunk_style_run_id",
    "ix_chunk_summaries_run_id",
    "ix_chunk_topics_chunk_id",
    "ix_chunk_topics_run_id",
    "ix_chunk_topics_topic_id",
    "ix_chunks_run_id",
    "ix_cloud_analysis_novel_id",
    "ix_cloud_analysis_run_id",
    "ix_global_context_run_id",
    "ix_model_interactions_interaction_type",
    "ix_model_interactions_run_id",
    "ix_stage_summaries_run_id",
    "ix_token_usage_novel_id",
    "ix_token_usage_run_id",
]

LEGACY_CONSTRAINTS_TO_DROP: list[tuple[str, str]] = [
    ("chunk_curves", "fk_chunk_curves_chunks"),
    ("chunk_curves", "fk_chunk_curves_runs"),
]

EXPECTED_FOREIGN_KEYS: list[dict[str, str]] = [
    {
        "table": "character_appearances",
        "name": "character_appearances_chunk_id_run_id_fkey",
        "sql": (
            "ALTER TABLE character_appearances "
            "ADD CONSTRAINT character_appearances_chunk_id_run_id_fkey "
            "FOREIGN KEY (chunk_id, run_id) REFERENCES chunks(chunk_id, run_id) ON DELETE CASCADE"
        ),
        "orphan_sql": (
            "SELECT COUNT(*) FROM character_appearances ca "
            "LEFT JOIN chunks c ON c.chunk_id = ca.chunk_id AND c.run_id = ca.run_id "
            "WHERE c.chunk_id IS NULL"
        ),
    },
    {
        "table": "chunk_curves",
        "name": "chunk_curves_chunk_id_run_id_fkey",
        "sql": (
            "ALTER TABLE chunk_curves "
            "ADD CONSTRAINT chunk_curves_chunk_id_run_id_fkey "
            "FOREIGN KEY (chunk_id, run_id) REFERENCES chunks(chunk_id, run_id) ON DELETE CASCADE"
        ),
        "orphan_sql": (
            "SELECT COUNT(*) FROM chunk_curves cc "
            "LEFT JOIN chunks c ON c.chunk_id = cc.chunk_id AND c.run_id = cc.run_id "
            "WHERE c.chunk_id IS NULL"
        ),
    },
    {
        "table": "chunk_curves",
        "name": "chunk_curves_run_id_fkey",
        "sql": (
            "ALTER TABLE chunk_curves "
            "ADD CONSTRAINT chunk_curves_run_id_fkey "
            "FOREIGN KEY (run_id) REFERENCES analysis_runs(run_id) ON DELETE CASCADE"
        ),
        "orphan_sql": (
            "SELECT COUNT(*) FROM chunk_curves cc "
            "LEFT JOIN analysis_runs ar ON ar.run_id = cc.run_id "
            "WHERE ar.run_id IS NULL"
        ),
    },
    {
        "table": "chunk_dialogues",
        "name": "chunk_dialogues_chunk_id_run_id_fkey",
        "sql": (
            "ALTER TABLE chunk_dialogues "
            "ADD CONSTRAINT chunk_dialogues_chunk_id_run_id_fkey "
            "FOREIGN KEY (chunk_id, run_id) REFERENCES chunks(chunk_id, run_id) ON DELETE CASCADE"
        ),
        "orphan_sql": (
            "SELECT COUNT(*) FROM chunk_dialogues cd "
            "LEFT JOIN chunks c ON c.chunk_id = cd.chunk_id AND c.run_id = cd.run_id "
            "WHERE c.chunk_id IS NULL"
        ),
    },
    {
        "table": "chunk_foreshadowing",
        "name": "chunk_foreshadowing_chunk_id_run_id_fkey",
        "sql": (
            "ALTER TABLE chunk_foreshadowing "
            "ADD CONSTRAINT chunk_foreshadowing_chunk_id_run_id_fkey "
            "FOREIGN KEY (chunk_id, run_id) REFERENCES chunks(chunk_id, run_id) ON DELETE CASCADE"
        ),
        "orphan_sql": (
            "SELECT COUNT(*) FROM chunk_foreshadowing cf "
            "LEFT JOIN chunks c ON c.chunk_id = cf.chunk_id AND c.run_id = cf.run_id "
            "WHERE c.chunk_id IS NULL"
        ),
    },
    {
        "table": "chunk_foreshadowing",
        "name": "chunk_foreshadowing_run_id_fkey",
        "sql": (
            "ALTER TABLE chunk_foreshadowing "
            "ADD CONSTRAINT chunk_foreshadowing_run_id_fkey "
            "FOREIGN KEY (run_id) REFERENCES analysis_runs(run_id) ON DELETE CASCADE"
        ),
        "orphan_sql": (
            "SELECT COUNT(*) FROM chunk_foreshadowing cf "
            "LEFT JOIN analysis_runs ar ON ar.run_id = cf.run_id "
            "WHERE cf.run_id IS NOT NULL AND ar.run_id IS NULL"
        ),
    },
    {
        "table": "chunk_relations",
        "name": "chunk_relations_chunk_id_run_id_fkey",
        "sql": (
            "ALTER TABLE chunk_relations "
            "ADD CONSTRAINT chunk_relations_chunk_id_run_id_fkey "
            "FOREIGN KEY (chunk_id, run_id) REFERENCES chunks(chunk_id, run_id) ON DELETE CASCADE"
        ),
        "orphan_sql": (
            "SELECT COUNT(*) FROM chunk_relations cr "
            "LEFT JOIN chunks c ON c.chunk_id = cr.chunk_id AND c.run_id = cr.run_id "
            "WHERE c.chunk_id IS NULL"
        ),
    },
    {
        "table": "chunk_style",
        "name": "chunk_style_chunk_id_run_id_fkey",
        "sql": (
            "ALTER TABLE chunk_style "
            "ADD CONSTRAINT chunk_style_chunk_id_run_id_fkey "
            "FOREIGN KEY (chunk_id, run_id) REFERENCES chunks(chunk_id, run_id) ON DELETE CASCADE"
        ),
        "orphan_sql": (
            "SELECT COUNT(*) FROM chunk_style cs "
            "LEFT JOIN chunks c ON c.chunk_id = cs.chunk_id AND c.run_id = cs.run_id "
            "WHERE c.chunk_id IS NULL"
        ),
    },
    {
        "table": "chunk_topics",
        "name": "chunk_topics_chunk_id_run_id_fkey",
        "sql": (
            "ALTER TABLE chunk_topics "
            "ADD CONSTRAINT chunk_topics_chunk_id_run_id_fkey "
            "FOREIGN KEY (chunk_id, run_id) REFERENCES chunks(chunk_id, run_id) ON DELETE CASCADE"
        ),
        "orphan_sql": (
            "SELECT COUNT(*) FROM chunk_topics ct "
            "LEFT JOIN chunks c ON c.chunk_id = ct.chunk_id AND c.run_id = ct.run_id "
            "WHERE c.chunk_id IS NULL"
        ),
    },
    {
        "table": "model_interactions",
        "name": "model_interactions_chunk_id_run_id_fkey",
        "sql": (
            "ALTER TABLE model_interactions "
            "ADD CONSTRAINT model_interactions_chunk_id_run_id_fkey "
            "FOREIGN KEY (chunk_id, run_id) REFERENCES chunks(chunk_id, run_id) ON DELETE CASCADE"
        ),
        "orphan_sql": (
            "SELECT COUNT(*) FROM model_interactions mi "
            "LEFT JOIN chunks c ON c.chunk_id = mi.chunk_id AND c.run_id = mi.run_id "
            "WHERE mi.chunk_id IS NOT NULL AND c.chunk_id IS NULL"
        ),
    },
    {
        "table": "model_interactions",
        "name": "model_interactions_run_id_fkey",
        "sql": (
            "ALTER TABLE model_interactions "
            "ADD CONSTRAINT model_interactions_run_id_fkey "
            "FOREIGN KEY (run_id) REFERENCES analysis_runs(run_id) ON DELETE CASCADE"
        ),
        "orphan_sql": (
            "SELECT COUNT(*) FROM model_interactions mi "
            "LEFT JOIN analysis_runs ar ON ar.run_id = mi.run_id "
            "WHERE ar.run_id IS NULL"
        ),
    },
    {
        "table": "stage_summaries",
        "name": "stage_summaries_run_id_fkey",
        "sql": (
            "ALTER TABLE stage_summaries "
            "ADD CONSTRAINT stage_summaries_run_id_fkey "
            "FOREIGN KEY (run_id) REFERENCES analysis_runs(run_id) ON DELETE CASCADE"
        ),
        "orphan_sql": (
            "SELECT COUNT(*) FROM stage_summaries ss "
            "LEFT JOIN analysis_runs ar ON ar.run_id = ss.run_id "
            "WHERE ar.run_id IS NULL"
        ),
    },
]


def load_database_url(target: str) -> str:
    """读取目标数据库连接串，避免脚本里硬编码真实地址。"""
    env_key = "DATABASE_URL" if target == "dev" else "TEST_DATABASE_URL"
    database_url = os.environ.get(env_key)
    if not database_url:
        raise RuntimeError(f"{env_key} 未配置，无法执行 schema 修复")
    return database_url


def build_engine(database_url: str) -> Engine:
    """为独立 schema 修复脚本创建短生命周期引擎。"""
    return create_engine(database_url, future=True)


def constraint_exists(conn, table_name: str, constraint_name: str) -> bool:
    """按表名和约束名检查 PostgreSQL 约束是否存在。"""
    result = conn.execute(
        text(
            """
            SELECT 1
            FROM pg_constraint
            WHERE conname = :constraint_name
              AND conrelid = to_regclass(:table_name)
            """
        ),
        {"constraint_name": constraint_name, "table_name": table_name},
    )
    return result.scalar_one_or_none() is not None


def column_exists(conn, table_name: str, column_name: str) -> bool:
    """检查指定表列是否存在，用于决定是否补列或删旧列。"""
    result = conn.execute(
        text(
            """
            SELECT 1
            FROM information_schema.columns
            WHERE table_schema = 'public'
              AND table_name = :table_name
              AND column_name = :column_name
            """
        ),
        {"table_name": table_name, "column_name": column_name},
    )
    return result.scalar_one_or_none() is not None


def index_exists(conn, index_name: str) -> bool:
    """检查索引是否存在，避免重复创建同名索引。"""
    result = conn.execute(text("SELECT to_regclass(:index_name)"), {"index_name": index_name})
    return result.scalar_one_or_none() is not None


def scalar_count(conn, sql: str) -> int:
    """统一执行计数 SQL，便于在补约束前先做孤儿数据守卫。"""
    return int(conn.execute(text(sql)).scalar_one())


def ensure_model_interaction_columns(conn) -> list[str]:
    """为 model_interactions 补齐 observability 新增列。"""
    applied: list[str] = []
    if not column_exists(conn, "model_interactions", "reasoning_tokens"):
        conn.execute(text("ALTER TABLE model_interactions ADD COLUMN reasoning_tokens INTEGER"))
        applied.append("model_interactions.reasoning_tokens")
    if not column_exists(conn, "model_interactions", "thinking_state"):
        conn.execute(
            text(
                "ALTER TABLE model_interactions "
                "ADD COLUMN thinking_state VARCHAR(20) NOT NULL DEFAULT 'unknown'"
            )
        )
        applied.append("model_interactions.thinking_state")
    return applied


def ensure_runtime_indexes(conn) -> list[str]:
    """补齐按 run_id 过滤常用表的关键索引。"""
    applied: list[str] = []
    for index_name, sql in EXPECTED_RUNTIME_INDEXES:
        if index_exists(conn, index_name):
            continue
        conn.execute(text(sql))
        applied.append(index_name)
    return applied


def drop_redundant_indexes(conn) -> list[str]:
    """删除重复生成的 ix_* 索引，避免同义索引长期共存。"""
    dropped: list[str] = []
    for index_name in REDUNDANT_INDEXES:
        if not index_exists(conn, index_name):
            continue
        conn.execute(text(f"DROP INDEX IF EXISTS {index_name}"))
        dropped.append(index_name)
    return dropped


def drop_legacy_constraints(conn) -> list[str]:
    """删除已被当前命名规范替代的旧约束。"""
    dropped: list[str] = []
    for table_name, constraint_name in LEGACY_CONSTRAINTS_TO_DROP:
        if not constraint_exists(conn, table_name, constraint_name):
            continue
        conn.execute(text(f"ALTER TABLE {table_name} DROP CONSTRAINT {constraint_name}"))
        dropped.append(constraint_name)
    return dropped


def ensure_foreign_keys(conn) -> list[str]:
    """只在孤儿数据计数为 0 时补外键。"""
    applied: list[str] = []
    for item in EXPECTED_FOREIGN_KEYS:
        if constraint_exists(conn, item["table"], item["name"]):
            continue
        orphan_count = scalar_count(conn, item["orphan_sql"])
        if orphan_count != 0:
            raise RuntimeError(
                f"无法为 {item['table']} 添加约束 {item['name']}：检测到 {orphan_count} 条孤儿数据"
            )
        conn.execute(text(item["sql"]))
        applied.append(item["name"])
    return applied


def drop_legacy_chunk_style_column(conn) -> bool:
    """删除已从代码与仓储层完全移除的 cultural_density 残留列。"""
    if not column_exists(conn, "chunk_style", "cultural_density"):
        return False
    conn.execute(text("ALTER TABLE chunk_style DROP COLUMN cultural_density"))
    return True


def repair_development_database(database_url: str) -> list[str]:
    """对开发库做原地修复。"""
    engine = build_engine(database_url)
    applied: list[str] = []
    try:
        with engine.begin() as conn:
            applied.extend(drop_legacy_constraints(conn))
            applied.extend(ensure_model_interaction_columns(conn))
            applied.extend(ensure_runtime_indexes(conn))
            applied.extend(ensure_foreign_keys(conn))
            applied.extend(drop_redundant_indexes(conn))
            if drop_legacy_chunk_style_column(conn):
                applied.append("chunk_style.cultural_density")
    finally:
        engine.dispose()
    return applied


def rebuild_test_database(database_url: str) -> None:
    """重建测试库 public schema。"""
    engine = build_engine(database_url)
    try:
        with engine.begin() as conn:
            conn.execute(text("DROP SCHEMA IF EXISTS public CASCADE"))
            conn.execute(text("CREATE SCHEMA public"))
            conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
    finally:
        engine.dispose()

    original_database_url = os.environ.get("DATABASE_URL")
    os.environ["DATABASE_URL"] = database_url
    db_module.dispose_engine()
    try:
        db_module.init_db(include_level3_tables=True)
    finally:
        db_module.dispose_engine()
        if original_database_url is None:
            os.environ.pop("DATABASE_URL", None)
        else:
            os.environ["DATABASE_URL"] = original_database_url


def collect_schema_report(database_url: str) -> dict[str, object]:
    """收集修复后需要核对的关键结构状态。"""
    engine = build_engine(database_url)
    inspector = inspect(engine)
    try:
        with engine.connect() as conn:
            report = {
                "model_interactions_missing_columns": [
                    column
                    for column in ("reasoning_tokens", "thinking_state")
                    if not column_exists(conn, "model_interactions", column)
                ],
                "chunk_style_has_legacy_cultural_density": column_exists(conn, "chunk_style", "cultural_density"),
                "missing_runtime_indexes": [
                    index_name
                    for index_name, _ in EXPECTED_RUNTIME_INDEXES
                    if not index_exists(conn, index_name)
                ],
                "redundant_indexes_still_present": [
                    index_name for index_name in REDUNDANT_INDEXES if index_exists(conn, index_name)
                ],
                "missing_foreign_keys": [
                    item["name"]
                    for item in EXPECTED_FOREIGN_KEYS
                    if item["table"] in inspector.get_table_names()
                    and not constraint_exists(conn, item["table"], item["name"])
                ],
                "chunk_foreshadowing_pk": tuple(
                    inspector.get_pk_constraint("chunk_foreshadowing").get("constrained_columns") or []
                ),
                "chunk_foreshadowing_run_id_nullable": next(
                    (
                        bool(column["nullable"])
                        for column in inspector.get_columns("chunk_foreshadowing")
                        if column["name"] == "run_id"
                    ),
                    None,
                ),
            }
    finally:
        engine.dispose()
    return report


def parse_args() -> argparse.Namespace:
    """解析脚本参数，区分开发库修复与测试库重建。"""
    parser = argparse.ArgumentParser(description="修复 novel_analysis 数据库 schema 漂移")
    parser.add_argument("--target", choices=["dev", "test"], required=True, help="修复目标数据库")
    parser.add_argument(
        "--rebuild-test",
        action="store_true",
        help="仅对测试库生效：重建 public schema，再按当前 ORM 重新建表",
    )
    return parser.parse_args()


def main() -> int:
    """执行修复并打印最终核对结果。"""
    args = parse_args()
    database_url = load_database_url(args.target)

    logger.info("开始修复 {} 数据库 schema: {}", args.target, database_url)
    if args.target == "test":
        if not args.rebuild_test:
            raise RuntimeError("测试库检测到需要重建时，请显式传入 --rebuild-test")
        rebuild_test_database(database_url)
        logger.info("测试库 public schema 已重建")
    else:
        applied = repair_development_database(database_url)
        if applied:
            logger.info("开发库已应用修复项: {}", ", ".join(applied))
        else:
            logger.info("开发库未发现需要落地的新修复项")

    report = collect_schema_report(database_url)
    logger.info("schema 核对结果: {}", report)

    if report["model_interactions_missing_columns"]:
        return 1
    if report["chunk_style_has_legacy_cultural_density"]:
        return 1
    if report["missing_runtime_indexes"]:
        return 1
    if report["redundant_indexes_still_present"]:
        return 1
    if report["missing_foreign_keys"]:
        return 1
    if report["chunk_foreshadowing_pk"] != ("chunk_id", "run_id"):
        return 1
    if report["chunk_foreshadowing_run_id_nullable"] is not False:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
