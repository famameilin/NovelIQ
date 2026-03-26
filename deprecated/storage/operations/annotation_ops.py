"""
创建时间: 2026-03-12
创建者: TraeAI
任务: 项目文件结构整理与拆解 - 从 operations.py 拆分标注相关操作

本模块包含标注相关的数据库操作函数。

修改时间: 2026-03-14
修改者: TraeAI
任务: Chunk 双次调用分析拆分
修改内容: 添加 insert_foreshadowing 函数
"""

from __future__ import annotations

import sqlite3
from datetime import datetime
from typing import Dict, List, Sequence, Set, Tuple

from src.models.local.schema import (
    ChunkAnnotation,
    CharacterSnapshot,
    DialogueSnapshot,
    RelationChangeSnapshot,
    ForeshadowingResult,
)


def insert_chunk_annotation(conn: sqlite3.Connection, chunk_id: int, annotation: ChunkAnnotation) -> None:
    conn.execute(
        """
        INSERT INTO chunk_annotation (
            chunk_id, emotional_valence, pivot_moment, event_type, cliffhanger,
            has_foreshadowing, foreshadowing_type, foreshadowing_desc
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            chunk_id,
            annotation.emotional_valence,
            int(annotation.pivot_moment),
            annotation.event_type,
            int(annotation.cliffhanger),
            int(annotation.has_foreshadowing),
            annotation.foreshadowing_type,
            annotation.foreshadowing_desc,
        ),
    )
    conn.commit()


def insert_chunk_characters(conn: sqlite3.Connection, chunk_id: int, characters: Sequence[CharacterSnapshot]) -> None:
    rows = [(chunk_id, c.name, c.role_function, c.action, c.action_type, c.emotion_score) for c in characters]
    conn.executemany(
        "INSERT INTO chunk_characters (chunk_id, name, role_function, action, action_type, emotion_score) VALUES (?, ?, ?, ?, ?, ?)",
        rows,
    )
    conn.commit()


def insert_chunk_relations(
    conn: sqlite3.Connection, chunk_id: int, relations: Sequence[RelationChangeSnapshot]
) -> None:
    rows = [(chunk_id, r.from_name, r.to_name, r.type, r.change) for r in relations if r.from_name != r.to_name]
    if not rows:
        return
    conn.executemany(
        "INSERT INTO chunk_relations (chunk_id, from_char, to_char, type, change) VALUES (?, ?, ?, ?, ?)",
        rows,
    )
    conn.commit()


def insert_chunk_dialogues(
    conn: sqlite3.Connection, chunk_id: int, dialogues: Sequence[DialogueSnapshot], lengths: Sequence[int] | None = None
) -> None:
    rows: List[Tuple[int, str, int | None]] = []
    for idx, dialogue in enumerate(dialogues):
        length = lengths[idx] if lengths is not None and idx < len(lengths) else None
        rows.append((chunk_id, dialogue.speaker, length))
    conn.executemany(
        "INSERT INTO chunk_dialogues (chunk_id, speaker, length) VALUES (?, ?, ?)",
        rows,
    )
    conn.commit()


def fetch_chunk_annotations(conn: sqlite3.Connection) -> List[Tuple[int, str, int]]:
    cursor = conn.execute("SELECT chunk_id, event_type, cliffhanger FROM chunk_annotation ORDER BY chunk_id")
    return cursor.fetchall()


def fetch_annotated_chunk_ids(conn: sqlite3.Connection) -> Set[int]:
    cursor = conn.execute("SELECT chunk_id FROM chunk_annotation")
    return {row[0] for row in cursor.fetchall()}


def fetch_all_character_names(conn: sqlite3.Connection) -> List[Dict[str, str | int]]:
    """
    获取所有角色名及其出现频次

    修改时间: 2026-03-12
    修改者: TraeAI
    修改内容: 返回带频次的数据 [{"name": "伯安", "count": 312}, ...]

    修改时间: 2026-03-12
    修改者: TraeAI
    任务: fix-annotation-disambiguation-issues
    修改内容: 同时从 chunk_characters 和 character_appearances 表获取名字，确保外貌描述性称呼也能参与消歧
    """
    cursor = conn.execute("""
        SELECT name, COUNT(*) as count 
        FROM chunk_characters 
        GROUP BY name 
        UNION ALL
        SELECT raw_name as name, COUNT(*) as count 
        FROM character_appearances 
        GROUP BY raw_name
    """)
    name_counts: dict[str, int] = {}
    for row in cursor.fetchall():
        name = row[0]
        count = row[1]
        if name:
            name_counts[name] = name_counts.get(name, 0) + count
    return [{"name": name, "count": count} for name, count in sorted(name_counts.items(), key=lambda x: -x[1])]


def _update_character_names_in_tables(conn: sqlite3.Connection, alias: str, canonical: str) -> None:
    """
    创建时间: 2026-03-13
    创建者: TraeAI
    任务: refactor-core-data-layer-functions
    功能: 更新多个表中的角色名（从别名更新为规范名）
    """
    conn.execute("UPDATE chunk_characters SET name = ? WHERE name = ?", (canonical, alias))
    conn.execute("UPDATE chunk_relations SET from_char = ? WHERE from_char = ?", (canonical, alias))
    conn.execute("UPDATE chunk_relations SET to_char = ? WHERE to_char = ?", (canonical, alias))
    conn.execute("UPDATE chunk_dialogues SET speaker = ? WHERE speaker = ?", (canonical, alias))


def _ensure_entity_exists(
    conn: sqlite3.Connection, novel_id: str, canonical: str, canonical_to_entity_id: dict[str, int]
) -> int | None:
    """
    创建时间: 2026-03-13
    创建者: TraeAI
    任务: refactor-core-data-layer-functions
    功能: 确保实体存在，返回实体ID
    """
    if canonical in canonical_to_entity_id:
        return canonical_to_entity_id[canonical]
    cursor = conn.execute(
        "SELECT entity_id FROM entities WHERE novel_id = ? AND canonical = ?",
        (novel_id, canonical),
    )
    row = cursor.fetchone()
    if row:
        canonical_to_entity_id[canonical] = row[0]
        return row[0]
    cursor = conn.execute(
        """INSERT INTO entities (novel_id, canonical, entity_type, first_chunk, last_chunk, description, confidence)
           VALUES (?, ?, 'character', NULL, NULL, NULL, 1.0)""",
        (novel_id, canonical),
    )
    if cursor.lastrowid is not None:
        canonical_to_entity_id[canonical] = cursor.lastrowid
        return cursor.lastrowid
    return None


def _create_alias_mapping(conn: sqlite3.Connection, entity_id: int, alias: str, canonical: str) -> None:
    """
    创建时间: 2026-03-13
    创建者: TraeAI
    任务: refactor-core-data-layer-functions
    功能: 创建别名映射记录
    """
    alias_type = "disambiguation" if alias != canonical else "canonical"
    alias_value = alias if alias != canonical else canonical
    conn.execute(
        """INSERT OR IGNORE INTO entity_aliases (entity_id, alias, alias_type, source_chunk, confirm_count)
           VALUES (?, ?, ?, NULL, 1)""",
        (entity_id, alias_value, alias_type),
    )


def update_character_names(conn: sqlite3.Connection, alias_map: dict[str, str], novel_id: str = "default") -> None:
    """
    修改时间: 2026-03-13
    修改者: TraeAI
    任务: refactor-core-data-layer-functions
    修改内容: 重构函数，提取辅助函数以降低复杂度
    """
    canonical_to_entity_id: dict[str, int] = {}
    for alias, canonical in alias_map.items():
        if alias != canonical:
            _update_character_names_in_tables(conn, alias, canonical)
        entity_id = _ensure_entity_exists(conn, novel_id, canonical, canonical_to_entity_id)
        if entity_id is not None:
            _create_alias_mapping(conn, entity_id, alias, canonical)
    conn.execute("DELETE FROM chunk_relations WHERE from_char = to_char")
    conn.commit()


def insert_foreshadowing(
    conn: sqlite3.Connection,
    chunk_id: int,
    result: ForeshadowingResult,
) -> None:
    """
    插入伏笔分析结果

    创建时间: 2026-03-14
    创建者: TraeAI
    任务: Chunk 双次调用分析拆分
    """
    if not result.has_foreshadowing:
        return
    conn.execute(
        """
        INSERT INTO chunk_foreshadowing (
            chunk_id, foreshadowing_type, anchor_text, anchor_reason, confidence, created_at
        ) VALUES (?, ?, ?, ?, ?, ?)
        """,
        (
            chunk_id,
            result.foreshadowing_type,
            result.anchor_text,
            result.anchor_reason,
            result.confidence,
            datetime.now().isoformat(),
        ),
    )
    conn.commit()
