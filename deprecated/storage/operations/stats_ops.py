"""
创建时间: 2026-03-12
创建者: TraeAI
任务: 项目文件结构整理与拆分 - 从 operations.py 拆分统计相关操作

本模块包含统计和全局数据相关的数据库操作函数。

修改时间: 2026-03-12
修改者: TraeAI
任务: fix-annotation-disambiguation-issues
修改内容: 添加 insert_chunk_summary 和 insert_character_appearances 函数
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from src.models.cloud.schema import CloudAnalysis


def insert_chunk_summary(conn: sqlite3.Connection, chunk_id: int, summary: str) -> None:
    """
    插入 chunk 摘要

    创建时间: 2026-03-12
    创建者: TraeAI
    任务: fix-annotation-disambiguation-issues
    """
    now = datetime.now().isoformat()
    conn.execute(
        "INSERT OR REPLACE INTO chunk_summaries (chunk_id, summary, created_at) VALUES (?, ?, ?)",
        (chunk_id, summary, now),
    )
    conn.commit()


def insert_character_appearances(conn: sqlite3.Connection, chunk_id: int, appearances: Sequence[Any]) -> None:
    """
    插入角色出场信息

    创建时间: 2026-03-12
    创建者: TraeAI
    任务: fix-annotation-disambiguation-issues
    """
    now = datetime.now().isoformat()
    rows = [(chunk_id, a.raw_name, a.identity_clue, a.clue_type, now) for a in appearances]
    if not rows:
        return
    conn.executemany(
        "INSERT INTO character_appearances (chunk_id, raw_name, identity_clue, clue_type, created_at) VALUES (?, ?, ?, ?, ?)",
        rows,
    )
    conn.commit()


def insert_emotion_curve(
    conn: sqlite3.Connection,
    rows: Iterable[Tuple[int, float, float, float, float]],
) -> None:
    conn.executemany(
        """
        INSERT INTO emotion_curve (chunk_id, pos_density, neg_density, net_density, smoothed_density)
        VALUES (?, ?, ?, ?, ?)
        """,
        list(rows),
    )
    conn.commit()


def insert_rhythm_curve(
    conn: sqlite3.Connection,
    rows: Iterable[Tuple[int, float, float]],
) -> None:
    conn.executemany(
        """
        INSERT INTO rhythm_curve (chunk_id, tension_proxy, tension_composite)
        VALUES (?, ?, ?)
        """,
        list(rows),
    )
    conn.commit()


def insert_global_stats(
    conn: sqlite3.Connection,
    stats: Iterable[Tuple[str, float]],
) -> None:
    conn.executemany(
        """
        INSERT OR REPLACE INTO global_stats (stat_name, stat_value)
        VALUES (?, ?)
        """,
        list(stats),
    )
    conn.commit()


def insert_cloud_analysis(conn: sqlite3.Connection, analysis: CloudAnalysis) -> None:
    arc_scores_json: str
    if isinstance(analysis.arc_scores, dict):
        arc_scores_json = json.dumps(analysis.arc_scores, ensure_ascii=False)
    else:
        arc_scores_json = json.dumps(list(analysis.arc_scores), ensure_ascii=False)

    conn.execute(
        """
        INSERT INTO cloud_analysis (
            novel_id, foreshadow_rate, arc_scores, narrative_type, topic_labels,
            diagnosis, value_logic_type, value_logic_reason,
            power_stance_score, power_stance_reason, common_people_dignity, dignity_reason,
            cultural_depth_score, cultural_depth_reason, emotion_curve_type
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            analysis.novel_id,
            analysis.foreshadow_rate,
            arc_scores_json,
            analysis.narrative_type,
            json.dumps(list(analysis.topic_labels), ensure_ascii=False),
            analysis.diagnosis,
            analysis.value_logic_type,
            analysis.value_logic_reason,
            analysis.power_stance_score,
            analysis.power_stance_reason,
            analysis.common_people_dignity,
            analysis.dignity_reason,
            analysis.cultural_depth_score,
            analysis.cultural_depth_reason,
            analysis.emotion_curve_type,
        ),
    )
    conn.commit()


def insert_global_context(
    conn: sqlite3.Connection,
    novel_id: str,
    core_characters: str,
    world_setting: str,
    novel_title: Optional[str] = None,
) -> None:
    now = datetime.now().isoformat()
    conn.execute(
        """
        INSERT OR REPLACE INTO global_context (novel_id, novel_title, core_characters, world_setting, updated_at)
        VALUES (?, ?, ?, ?, ?)
        """,
        (novel_id, novel_title, core_characters, world_setting, now),
    )
    conn.commit()


def fetch_global_context(
    conn: sqlite3.Connection,
    novel_id: str,
) -> Optional[Tuple[str, str, str, str]]:
    cursor = conn.execute(
        "SELECT novel_title, core_characters, world_setting, updated_at FROM global_context WHERE novel_id = ?",
        (novel_id,),
    )
    row = cursor.fetchone()
    if row is None:
        return None
    return (row[0], row[1], row[2], row[3])


def update_global_context(
    conn: sqlite3.Connection,
    novel_id: str,
    **kwargs,
) -> None:
    allowed_fields = {"core_characters", "world_setting"}
    updates = []
    values = []
    for key, value in kwargs.items():
        if key in allowed_fields:
            updates.append(f"{key} = ?")
            values.append(value)
    if not updates:
        return
    now = datetime.now().isoformat()
    updates.append("updated_at = ?")
    values.extend([now, novel_id])
    conn.execute(
        f"UPDATE global_context SET {', '.join(updates)} WHERE novel_id = ?",
        values,
    )
    conn.commit()


def insert_token_usage(
    conn: sqlite3.Connection,
    novel_id: str,
    task_type: str,
    call_type: str,
    model: str,
    prompt_tokens: int,
    total_tokens: int,
    completion_tokens: Optional[int] = None,
    chunk_id: Optional[int] = None,
) -> int | None:
    now = datetime.now().isoformat()
    cursor = conn.execute(
        """
        INSERT INTO token_usage (
            novel_id, chunk_id, task_type, call_type, model,
            prompt_tokens, completion_tokens, total_tokens, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (novel_id, chunk_id, task_type, call_type, model, prompt_tokens, completion_tokens, total_tokens, now),
    )
    conn.commit()
    return cursor.lastrowid


def fetch_token_usage_by_novel(
    conn: sqlite3.Connection,
    novel_id: str,
) -> List[Dict]:
    cursor = conn.execute(
        """
        SELECT id, novel_id, chunk_id, task_type, call_type, model,
               prompt_tokens, completion_tokens, total_tokens, created_at
        FROM token_usage
        WHERE novel_id = ?
        ORDER BY created_at DESC
        """,
        (novel_id,),
    )
    rows = cursor.fetchall()
    return [
        {
            "id": row[0],
            "novel_id": row[1],
            "chunk_id": row[2],
            "task_type": row[3],
            "call_type": row[4],
            "model": row[5],
            "prompt_tokens": row[6],
            "completion_tokens": row[7],
            "total_tokens": row[8],
            "created_at": row[9],
        }
        for row in rows
    ]


def _fetch_usage_summary(conn: sqlite3.Connection, novel_id: str) -> Dict:
    """
    获取使用量摘要

    创建时间: 2026-03-13
    创建者: TraeAI
    任务: refactor-core-data-layer-functions
    """
    cursor = conn.execute(
        """
        SELECT
            COUNT(*) as call_count,
            SUM(prompt_tokens) as total_prompt_tokens,
            SUM(COALESCE(completion_tokens, 0)) as total_completion_tokens,
            SUM(total_tokens) as total_tokens
        FROM token_usage
        WHERE novel_id = ?
        """,
        (novel_id,),
    )
    row = cursor.fetchone()
    return {
        "call_count": row[0] or 0,
        "total_prompt_tokens": row[1] or 0,
        "total_completion_tokens": row[2] or 0,
        "total_tokens": row[3] or 0,
    }


def _fetch_usage_by_task(conn: sqlite3.Connection, novel_id: str) -> Dict:
    """
    按任务类型获取使用量

    创建时间: 2026-03-13
    创建者: TraeAI
    任务: refactor-core-data-layer-functions
    """
    cursor = conn.execute(
        """
        SELECT task_type, COUNT(*) as count, SUM(total_tokens) as total
        FROM token_usage
        WHERE novel_id = ?
        GROUP BY task_type
        """,
        (novel_id,),
    )
    return {row[0]: {"call_count": row[1], "total_tokens": row[2]} for row in cursor.fetchall()}


def _fetch_usage_by_model(conn: sqlite3.Connection, novel_id: str) -> Dict:
    """
    按模型获取使用量

    创建时间: 2026-03-13
    创建者: TraeAI
    任务: refactor-core-data-layer-functions
    """
    cursor = conn.execute(
        """
        SELECT model, COUNT(*) as count, SUM(total_tokens) as total
        FROM token_usage
        WHERE novel_id = ?
        GROUP BY model
        """,
        (novel_id,),
    )
    return {row[0]: {"call_count": row[1], "total_tokens": row[2]} for row in cursor.fetchall()}


def fetch_token_usage_stats(
    conn: sqlite3.Connection,
    novel_id: str,
) -> Dict:
    """
    获取 token 使用统计

    创建时间: 2026-03-12
    创建者: TraeAI
    任务: 项目文件结构整理与拆分

    修改时间: 2026-03-13
    修改者: TraeAI
    任务: refactor-core-data-layer-functions
    修改内容: 重构为调用辅助函数，优化代码结构
    """
    return {
        "summary": _fetch_usage_summary(conn, novel_id),
        "by_task": _fetch_usage_by_task(conn, novel_id),
        "by_model": _fetch_usage_by_model(conn, novel_id),
    }
