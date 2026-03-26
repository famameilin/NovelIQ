from __future__ import annotations

import sqlite3
import warnings
from pathlib import Path


def connect_db(path: Path) -> sqlite3.Connection:
    """
    创建数据库连接

    .. deprecated::
        此函数已废弃，请使用 `src.storage.session.DatabaseSession` 或 `SessionFactory` 代替。
        将在未来版本中移除。

    修改时间: 2026-03-14
    修改者: TraeAI
    任务: 修复SQLite线程安全问题
    修改内容: 添加 check_same_thread=False 参数，允许跨线程共享连接

    修改时间: 2026-03-15
    修改者: TraeAI
    任务: storage-layer-decoupling
    修改内容: 标记为废弃，添加 deprecation warning
    """
    warnings.warn(
        "connect_db is deprecated, use DatabaseSession or SessionFactory instead",
        DeprecationWarning,
        stacklevel=2,
    )
    conn = sqlite3.connect(path, timeout=30.0, check_same_thread=False)
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    return conn


def _create_analysis_runs_table(conn: sqlite3.Connection) -> None:
    """
    创建时间: 2026-03-14
    创建者: TraeAI
    任务: 添加 analysis_runs 表和 run_id 字段
    说明: 创建分析运行记录表，用于追踪每次分析任务的状态
    """
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS analysis_runs (
            run_id TEXT PRIMARY KEY,
            novel_id TEXT NOT NULL,
            source_path TEXT,
            title TEXT,
            status TEXT DEFAULT 'pending',
            created_at TEXT,
            updated_at TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_analysis_runs_novel ON analysis_runs(novel_id);
        CREATE INDEX IF NOT EXISTS idx_analysis_runs_status ON analysis_runs(status);
        """
    )


def _create_chunks_tables(conn: sqlite3.Connection) -> None:
    """
    创建时间: 2026-03-13
    创建者: TraeAI
    任务: refactor-core-data-layer-functions
    说明: 创建 chunks 和 chunk_style 表

    修改时间: 2026-03-14
    修改者: TraeAI
    任务: 添加 analysis_runs 表和 run_id 字段
    修改内容: 为 chunks 和 chunk_style 表添加 run_id 字段
    """
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS chunks (
            chunk_id INTEGER PRIMARY KEY,
            chapter_id INTEGER,
            char_offset INTEGER,
            text TEXT NOT NULL,
            run_id TEXT
        );
        CREATE TABLE IF NOT EXISTS chunk_style (
            chunk_id INTEGER PRIMARY KEY,
            mtld REAL,
            ttr REAL,
            avg_sent_len REAL,
            sent_len_std REAL,
            d_value REAL,
            pause_density REAL,
            fight_density REAL,
            exclaim_density REAL,
            dialogue_ratio REAL,
            question_density REAL,
            sensory_density REAL,
            metaphor_density REAL,
            cultural_density REAL,
            function_word_vector TEXT,
            category_density_combat REAL,
            category_density_body REAL,
            category_density_relation REAL,
            category_density_faction REAL,
            category_density_command REAL,
            category_density_action REAL,
            category_density_psychology REAL,
            category_density_measure REAL,
            category_density_emotion REAL,
            category_density_color REAL,
            run_id TEXT,
            FOREIGN KEY(chunk_id) REFERENCES chunks(chunk_id)
        );
        """
    )


def _create_annotation_tables(conn: sqlite3.Connection) -> None:
    """
    创建时间: 2026-03-13
    创建者: TraeAI
    任务: refactor-core-data-layer-functions
    说明: 创建标注相关表（chunk_annotation, chunk_characters, chunk_relations, chunk_dialogues, chunk_topics）

    修改时间: 2026-03-14
    修改者: TraeAI
    任务: 添加 analysis_runs 表和 run_id 字段
    修改内容: 为标注相关表添加 run_id 字段
    """
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS chunk_annotation (
            chunk_id INTEGER PRIMARY KEY,
            emotional_valence TEXT,
            pivot_moment INTEGER,
            event_type TEXT,
            cliffhanger INTEGER,
            has_foreshadowing INTEGER,
            foreshadowing_type TEXT,
            foreshadowing_desc TEXT,
            run_id TEXT,
            FOREIGN KEY(chunk_id) REFERENCES chunks(chunk_id)
        );
        CREATE TABLE IF NOT EXISTS chunk_characters (
            chunk_id INTEGER,
            name TEXT,
            role_function TEXT,
            action TEXT,
            action_type TEXT,
            emotion_score TEXT,
            run_id TEXT,
            FOREIGN KEY(chunk_id) REFERENCES chunks(chunk_id)
        );
        CREATE TABLE IF NOT EXISTS chunk_relations (
            chunk_id INTEGER,
            from_char TEXT,
            to_char TEXT,
            type TEXT,
            change TEXT,
            run_id TEXT,
            FOREIGN KEY(chunk_id) REFERENCES chunks(chunk_id)
        );
        CREATE TABLE IF NOT EXISTS chunk_dialogues (
            chunk_id INTEGER,
            speaker TEXT,
            length INTEGER,
            run_id TEXT,
            FOREIGN KEY(chunk_id) REFERENCES chunks(chunk_id)
        );
        CREATE TABLE IF NOT EXISTS chunk_topics (
            chunk_id INTEGER,
            topic_id INTEGER,
            topic_weight REAL,
            run_id TEXT,
            FOREIGN KEY(chunk_id) REFERENCES chunks(chunk_id)
        );
        """
    )


def _create_entity_tables(conn: sqlite3.Connection) -> None:
    """
    创建时间: 2026-03-13
    创建者: TraeAI
    任务: refactor-core-data-layer-functions
    说明: 创建实体相关表（entities, entity_aliases, entity_relations, entity_snapshots, entity_registry）

    修改时间: 2026-03-14
    修改者: TraeAI
    任务: 添加 analysis_runs 表和 run_id 字段
    修改内容: 为实体相关表添加 run_id 字段
    """
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS entity_registry (
            entity_id INTEGER PRIMARY KEY AUTOINCREMENT,
            chunk_id INTEGER,
            name TEXT,
            role TEXT,
            last_action TEXT,
            last_emotion TEXT,
            emotion_score INTEGER,
            updated_at TEXT,
            run_id TEXT,
            FOREIGN KEY(chunk_id) REFERENCES chunks(chunk_id)
        );
        CREATE TABLE IF NOT EXISTS entities (
            entity_id    INTEGER PRIMARY KEY AUTOINCREMENT,
            novel_id     TEXT    NOT NULL,
            canonical    TEXT    NOT NULL,
            entity_type  TEXT    NOT NULL,
            first_chunk  INTEGER,
            last_chunk   INTEGER,
            description  TEXT,
            embedding    BLOB,
            confidence   REAL DEFAULT 1.0,
            run_id       TEXT,
            UNIQUE(novel_id, canonical)
        );
        CREATE TABLE IF NOT EXISTS entity_aliases (
            alias_id     INTEGER PRIMARY KEY AUTOINCREMENT,
            entity_id    INTEGER NOT NULL REFERENCES entities(entity_id),
            alias        TEXT    NOT NULL,
            alias_type   TEXT,
            source_chunk INTEGER,
            confirm_count INTEGER DEFAULT 1,
            run_id       TEXT,
            UNIQUE(entity_id, alias)
        );
        CREATE INDEX IF NOT EXISTS idx_aliases_lookup ON entity_aliases(alias);
        CREATE TABLE IF NOT EXISTS entity_relations (
            rel_id       INTEGER PRIMARY KEY AUTOINCREMENT,
            novel_id     TEXT    NOT NULL,
            from_entity  INTEGER NOT NULL REFERENCES entities(entity_id),
            to_entity    INTEGER NOT NULL REFERENCES entities(entity_id),
            rel_type     TEXT    NOT NULL,
            first_chunk  INTEGER,
            last_chunk   INTEGER,
            tension      REAL DEFAULT 0.0,
            is_active    INTEGER DEFAULT 1,
            run_id       TEXT,
            UNIQUE(novel_id, from_entity, to_entity, rel_type)
        );
        CREATE TABLE IF NOT EXISTS entity_snapshots (
            snap_id      INTEGER PRIMARY KEY AUTOINCREMENT,
            novel_id     TEXT    NOT NULL,
            entity_id    INTEGER NOT NULL REFERENCES entities(entity_id),
            chunk_id     INTEGER NOT NULL,
            state_json   TEXT,
            run_id       TEXT,
            UNIQUE(novel_id, entity_id, chunk_id)
        );
        CREATE INDEX IF NOT EXISTS idx_snapshots_recent ON entity_snapshots(novel_id, chunk_id DESC);
        """
    )


def _create_analysis_tables(conn: sqlite3.Connection) -> None:
    """
    创建时间: 2026-03-13
    创建者: TraeAI
    任务: refactor-core-data-layer-functions
    说明: 创建分析结果相关表（cloud_analysis, chunk_culture, emotion_curve, rhythm_curve, global_stats, global_context）

    修改时间: 2026-03-14
    修改者: TraeAI
    任务: 添加 analysis_runs 表和 run_id 字段
    修改内容: 为分析结果相关表添加 run_id 字段
    """
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS cloud_analysis (
            novel_id TEXT,
            foreshadow_rate REAL,
            arc_scores TEXT,
            narrative_type TEXT,
            topic_labels TEXT,
            diagnosis TEXT,
            value_logic_type TEXT,
            value_logic_reason TEXT,
            power_stance_score INTEGER,
            power_stance_reason TEXT,
            common_people_dignity INTEGER,
            dignity_reason TEXT,
            cultural_depth_score INTEGER,
            cultural_depth_reason TEXT,
            emotion_curve_type TEXT,
            run_id TEXT
        );
        CREATE TABLE IF NOT EXISTS chunk_culture (
            chunk_id INTEGER PRIMARY KEY,
            confucian_density REAL,
            taoist_density REAL,
            buddhist_density REAL,
            folk_density REAL,
            allusion_density REAL,
            imagery_density REAL,
            run_id TEXT,
            FOREIGN KEY(chunk_id) REFERENCES chunks(chunk_id)
        );
        CREATE TABLE IF NOT EXISTS emotion_curve (
            chunk_id INTEGER PRIMARY KEY,
            pos_density REAL,
            neg_density REAL,
            net_density REAL,
            smoothed_density REAL,
            run_id TEXT,
            FOREIGN KEY(chunk_id) REFERENCES chunks(chunk_id)
        );
        CREATE TABLE IF NOT EXISTS rhythm_curve (
            chunk_id INTEGER PRIMARY KEY,
            tension_proxy REAL,
            tension_composite REAL,
            run_id TEXT,
            FOREIGN KEY(chunk_id) REFERENCES chunks(chunk_id)
        );
        CREATE TABLE IF NOT EXISTS global_stats (
            stat_name TEXT PRIMARY KEY,
            stat_value REAL,
            run_id TEXT
        );
        CREATE TABLE IF NOT EXISTS global_context (
            novel_id TEXT PRIMARY KEY,
            novel_title TEXT,
            core_characters TEXT,
            world_setting TEXT,
            updated_at TEXT,
            run_id TEXT
        );
        """
    )


def _create_token_tables(conn: sqlite3.Connection) -> None:
    """
    创建时间: 2026-03-13
    创建者: TraeAI
    任务: refactor-core-data-layer-functions
    说明: 创建 token 使用统计和嵌入相关表（token_usage, chunk_embeddings, chunk_summaries, character_appearances）

    修改时间: 2026-03-12
    修改者: TraeAI
    任务: fix-annotation-disambiguation-issues
    修改内容: 新增 chunk_summaries 和 character_appearances 表

    修改时间: 2026-03-14
    修改者: TraeAI
    任务: 添加 analysis_runs 表和 run_id 字段
    修改内容: 为 token 相关表添加 run_id 字段
    """
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS chunk_embeddings (
            chunk_id INTEGER PRIMARY KEY,
            embedding BLOB,
            created_at TEXT,
            run_id TEXT,
            FOREIGN KEY(chunk_id) REFERENCES chunks(chunk_id)
        );
        CREATE TABLE IF NOT EXISTS token_usage (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            novel_id TEXT NOT NULL,
            chunk_id INTEGER,
            task_type TEXT NOT NULL,
            call_type TEXT NOT NULL,
            model TEXT NOT NULL,
            prompt_tokens INTEGER NOT NULL,
            completion_tokens INTEGER,
            total_tokens INTEGER NOT NULL,
            created_at TEXT NOT NULL,
            run_id TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_token_usage_novel ON token_usage(novel_id);
        CREATE INDEX IF NOT EXISTS idx_token_usage_task ON token_usage(novel_id, task_type);
        CREATE TABLE IF NOT EXISTS chunk_summaries (
            chunk_id INTEGER PRIMARY KEY,
            summary TEXT,
            created_at TIMESTAMP,
            run_id TEXT,
            FOREIGN KEY(chunk_id) REFERENCES chunks(chunk_id)
        );
        CREATE TABLE IF NOT EXISTS character_appearances (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            chunk_id INTEGER,
            raw_name TEXT,
            identity_clue TEXT,
            clue_type TEXT,
            created_at TIMESTAMP,
            run_id TEXT,
            FOREIGN KEY(chunk_id) REFERENCES chunks(chunk_id)
        );
        CREATE INDEX IF NOT EXISTS idx_character_appearances_chunk ON character_appearances(chunk_id);
        CREATE INDEX IF NOT EXISTS idx_character_appearances_name ON character_appearances(raw_name);
        CREATE TABLE IF NOT EXISTS chunk_foreshadowing (
            chunk_id INTEGER PRIMARY KEY,
            foreshadowing_type TEXT,
            anchor_text TEXT,
            anchor_reason TEXT,
            confidence TEXT,
            created_at TIMESTAMP,
            run_id TEXT,
            FOREIGN KEY(chunk_id) REFERENCES chunks(chunk_id)
        );
        """
    )


def _create_graph_storage_table(conn: sqlite3.Connection) -> None:
    """
    创建图谱存储表

    修改时间: 2026-03-15
    修改者: TraeAI
    任务: storage-layer-decoupling
    修改内容: 新增 graph_storage 表用于存储知识图谱
    """
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS graph_storage (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            graph_name TEXT NOT NULL,
            graph_json TEXT NOT NULL,
            created_at TEXT,
            updated_at TEXT,
            run_id TEXT,
            UNIQUE(graph_name, run_id)
        );
        """
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_graph_storage_run ON graph_storage(run_id);")


def create_tables(conn: sqlite3.Connection) -> None:
    """
    创建数据库表结构

    .. deprecated::
        此函数已废弃，请使用 `src.storage.session.DatabaseSession` 的 `init_tables=True` 参数代替。
        将在未来版本中移除。

    创建时间: 2025-03-11
    创建者: TraeAI
    任务: 数据库操作模块入口

    修改时间: 2026-03-12
    修改者: TraeAI
    修改内容: 项目文件结构整理与拆解 - 新增 chunk_summaries 和 character_appearances 表

    修改时间: 2026-03-13
    修改者: TraeAI
    任务: refactor-core-data-layer-functions
    修改内容: 将表创建语句按功能模块拆分为多个子函数，提高可维护性

    修改时间: 2026-03-14
    修改者: TraeAI
    任务: 添加 analysis_runs 表和 run_id 字段
    修改内容: 新增 _create_analysis_runs_table 调用，创建分析运行记录表

    修改时间: 2026-03-15
    修改者: TraeAI
    任务: storage-layer-decoupling
    修改内容: 标记为废弃，添加 deprecation warning
    """
    warnings.warn(
        "create_tables is deprecated, use DatabaseSession with init_tables=True instead",
        DeprecationWarning,
        stacklevel=2,
    )
    _create_analysis_runs_table(conn)
    _create_chunks_tables(conn)
    _create_annotation_tables(conn)
    _create_entity_tables(conn)
    _create_analysis_tables(conn)
    _create_token_tables(conn)
    _create_graph_storage_table(conn)
    conn.commit()
