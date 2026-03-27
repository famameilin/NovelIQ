from __future__ import annotations

from typing import Any

from loguru import logger
from sqlalchemy import text
from sqlalchemy.orm import Session

from src.config import settings

"""
创建时间: 2025-03-11
创建者: TraeAI
任务: 构建诊断payload

修改时间: 2026-03-11
修改者: TraeAI
修改内容: 添加云端相关日志，提升为info等级

修改时间: 2026-03-15
修改者: TraeAI
任务: postgresql-migration
修改内容: 使用 SQLAlchemy text() 包装 SQL 语句

修改时间: 2026-03-27
修改者: TraeAI
任务: 简化 diagnosis payload
修改内容: 移除 common_character_names 字段，只保留 alias_map

修改时间: 2026-03-27
修改者: TraeAI
任务: disambiguation-state-three-layer
修改内容: 将 alias_map 改为 known_characters 和 alias_merges 两项
"""


def build_diagnosis_payload(conn: Session, novel_id: str | None = None, run_id: str | None = None) -> dict:
    """
    构建诊断payload

    修改时间: 2026-03-19
    修改者: TraeAI
    任务: 修复run_id过滤BUG
    修改内容: 添加run_id参数，确保只获取当前运行的数据
    
    修改时间: 2026-03-27
    修改者: TraeAI
    任务: disambiguation-state-three-layer
    修改内容: 将 alias_map 改为 known_characters 和 alias_merges 两项
    """
    logger.info(
        "[云端模型] 构建诊断payload开始: novel_id=%s run_id=%s",
        novel_id,
        run_id,
    )

    effective_run_id = run_id or ""

    pivot_blocks = []
    for row in _fetch_pivot_blocks(conn, effective_run_id, limit=settings.diagnosis.pivot_blocks_limit):
        chunk_id, chunk_text, event_type = row
        pivot_blocks.append(
            {
                "chunk_id": chunk_id,
                "text": chunk_text[: settings.diagnosis.text_limits.pivot_block] if chunk_text else "",
                "event_type": event_type,
            }
        )
    logger.info("[云端模型] 获取pivot_blocks: count=%d", len(pivot_blocks))

    pivot_moments = []
    for row in _fetch_pivot_moments(conn, effective_run_id, limit=settings.diagnosis.pivot_moments_limit):
        chunk_id, chunk_text = row
        pivot_moments.append(
            {
                "chunk_id": chunk_id,
                "text": chunk_text[: settings.diagnosis.text_limits.pivot_moment] if chunk_text else "",
            }
        )
    logger.info("[云端模型] 获取pivot_moments: count=%d", len(pivot_moments))

    high_tension = []
    for row in _fetch_high_tension_chunks(conn, effective_run_id, limit=settings.diagnosis.high_tension_limit):
        chunk_id, chunk_text, tension = row
        high_tension.append(
            {
                "chunk_id": chunk_id,
                "text": chunk_text[: settings.diagnosis.text_limits.high_tension] if chunk_text else "",
                "tension": round(tension, 4),
            }
        )
    logger.info("[云端模型] 获取high_tension: count=%d", len(high_tension))

    relations = []
    for row in _fetch_relation_changes(conn, effective_run_id, limit=settings.diagnosis.relation_changes_limit):
        chunk_id, from_char, to_char, rel_type, change = row
        relations.append(
            {
                "chunk_id": chunk_id,
                "from": from_char,
                "to": to_char,
                "type": rel_type,
                "change": change,
            }
        )
    logger.info("[云端模型] 获取relation_changes: count=%d", len(relations))

    foreshadowing = []
    for row in _fetch_foreshadowing_chunks(conn, effective_run_id, limit=settings.diagnosis.foreshadowing_limit):
        chunk_id, chunk_text, fs_type, fs_desc = row
        foreshadowing.append(
            {
                "chunk_id": chunk_id,
                "text": chunk_text[: settings.diagnosis.text_limits.foreshadowing] if chunk_text else "",
                "type": fs_type,
                "description": fs_desc,
            }
        )
    logger.info("[云端模型] 获取foreshadowing: count=%d", len(foreshadowing))

    first_summary, last_summary = _fetch_first_last_chunk_summary(
        conn, effective_run_id, max_chars=settings.diagnosis.first_last_max_chars
    )
    logger.info("[云端模型] 获取首尾摘要: first_len=%d last_len=%d", len(first_summary), len(last_summary))

    topic_words = _fetch_topic_words(conn, effective_run_id, top_n=settings.diagnosis.topic_words_top_n)
    logger.info("[云端模型] 获取topic_words: count=%d", len(topic_words))

    known_characters, alias_merges = _fetch_character_disambig_data(conn, effective_run_id)

    payload = {
        "novel_id": novel_id,
        "pivot_blocks": pivot_blocks,
        "pivot_moments": pivot_moments,
        "high_tension_paragraphs": high_tension,
        "character_relations": relations,
        "foreshadowing_list": foreshadowing,
        "first_chapter_summary": first_summary,
        "last_chapter_summary": last_summary,
        "topic_words": topic_words,
        "known_characters": known_characters,
        "alias_merges": alias_merges,
    }

    logger.info(
        "[云端模型] 诊断payload构建完成: pivot_blocks=%d pivot_moments=%d high_tension=%d relations=%d foreshadowing=%d topic_words=%d known_characters=%d alias_merges=%d",
        len(pivot_blocks),
        len(pivot_moments),
        len(high_tension),
        len(relations),
        len(foreshadowing),
        len(topic_words),
        len(known_characters),
        len(alias_merges),
    )

    return payload


def _fetch_pivot_blocks(conn: Session, run_id: str, limit: int = 20) -> list[Any]:
    """
    获取转折点块

    修改时间: 2026-03-19
    修改者: TraeAI
    任务: 修复run_id过滤BUG
    修改内容: 添加run_id过滤条件
    """
    result = conn.execute(
        text(
            """
            SELECT c.chunk_id, c.text, a.event_type
            FROM chunks c
            JOIN chunk_annotation a ON c.chunk_id = a.chunk_id AND c.run_id = a.run_id
            WHERE a.pivot_moment = 1
              AND c.run_id = :run_id
              AND a.run_id = :run_id
            ORDER BY c.chunk_id
            LIMIT :limit
            """
        ),
        {"run_id": run_id, "limit": limit},
    )
    return list(result.fetchall())


def _fetch_pivot_moments(conn: Session, run_id: str, limit: int = 10) -> list[Any]:
    """
    获取高潮时刻

    修改时间: 2026-03-19
    修改者: TraeAI
    任务: 修复run_id过滤BUG
    修改内容: 添加run_id过滤条件
    """
    result = conn.execute(
        text(
            """
            SELECT c.chunk_id, c.text
            FROM chunks c
            JOIN chunk_annotation a ON c.chunk_id = a.chunk_id AND c.run_id = a.run_id
            WHERE a.event_type = '高潮'
              AND c.run_id = :run_id
              AND a.run_id = :run_id
            ORDER BY c.chunk_id
            LIMIT :limit
            """
        ),
        {"run_id": run_id, "limit": limit},
    )
    return list(result.fetchall())


def _fetch_high_tension_chunks(conn: Session, run_id: str, limit: int = 10) -> list[Any]:
    """
    获取高张力块

    修改时间: 2026-03-19
    修改者: TraeAI
    任务: 修复run_id过滤BUG
    修改内容: 添加run_id过滤条件
    """
    result = conn.execute(
        text(
            """
            SELECT c.chunk_id, c.text, ABS(e.net_density) as tension
            FROM chunks c
            JOIN emotion_curve e ON c.chunk_id = e.chunk_id AND c.run_id = e.run_id
            WHERE ABS(e.net_density) > 0.01
              AND c.run_id = :run_id
              AND e.run_id = :run_id
            ORDER BY tension DESC
            LIMIT :limit
            """
        ),
        {"run_id": run_id, "limit": limit},
    )
    return list(result.fetchall())


def _fetch_relation_changes(conn: Session, run_id: str, limit: int = 50) -> list[Any]:
    """
    获取关系变化

    修改时间: 2026-03-19
    修改者: TraeAI
    任务: 修复run_id过滤BUG
    修改内容: 添加run_id过滤条件
    """
    result = conn.execute(
        text(
            """
            SELECT chunk_id, from_char, to_char, type, change
            FROM chunk_relations
            WHERE run_id = :run_id
            ORDER BY chunk_id
            LIMIT :limit
            """
        ),
        {"run_id": run_id, "limit": limit},
    )
    return list(result.fetchall())


def _fetch_foreshadowing_chunks(conn: Session, run_id: str, limit: int = 30) -> list[Any]:
    """
    获取伏笔块

    修改时间: 2026-03-19
    修改者: TraeAI
    任务: 修复run_id过滤BUG
    修改内容: 添加run_id过滤条件
    """
    result = conn.execute(
        text(
            """
            SELECT c.chunk_id, c.text, a.foreshadowing_type, a.foreshadowing_desc
            FROM chunks c
            JOIN chunk_annotation a ON c.chunk_id = a.chunk_id AND c.run_id = a.run_id
            WHERE a.has_foreshadowing = 1
              AND c.run_id = :run_id
              AND a.run_id = :run_id
            ORDER BY c.chunk_id
            LIMIT :limit
            """
        ),
        {"run_id": run_id, "limit": limit},
    )
    return list(result.fetchall())


def _fetch_first_last_chunk_summary(conn: Session, run_id: str, max_chars: int = 500) -> tuple:
    """
    获取首尾块摘要

    修改时间: 2026-03-19
    修改者: TraeAI
    任务: 修复run_id过滤BUG
    修改内容: 添加run_id过滤条件
    """
    result = conn.execute(
        text("SELECT chunk_id, text FROM chunks WHERE run_id = :run_id ORDER BY chunk_id"), {"run_id": run_id}
    )
    chunks = result.fetchall()
    if not chunks:
        return "", ""
    first_text = chunks[0][1][:max_chars] if chunks[0][1] else ""
    last_text = chunks[-1][1][:max_chars] if chunks[-1][1] else ""
    return first_text, last_text


def _fetch_topic_words(conn: Session, run_id: str, top_n: int = 10) -> list[dict]:
    """
    获取主题词

    修改时间: 2026-03-19
    修改者: TraeAI
    任务: 修复run_id过滤BUG
    修改内容: 添加run_id过滤条件
    """
    result = conn.execute(
        text(
            """
            SELECT topic_id, SUM(topic_weight) as total_weight
            FROM chunk_topics
            WHERE run_id = :run_id
            GROUP BY topic_id
            ORDER BY total_weight DESC
            """
        ),
        {"run_id": run_id},
    )
    topic_weights = result.fetchall()
    if not topic_weights:
        return []

    result_list = []
    for topic_id, weight in topic_weights[:top_n]:
        result_list.append(
            {
                "topic_id": topic_id,
                "weight": round(weight, 4),
            }
        )
    return result_list


def _fetch_character_disambig_data(conn: Session, run_id: str) -> tuple[list[str], dict[str, str]]:
    """
    获取角色消歧数据（known_characters 和 alias_merges）
    
    创建时间: 2026-03-27
    创建者: TraeAI
    任务: disambiguation-state-three-layer
    说明: 分离获取 known_characters 和 alias_merges
    
    Returns:
        (known_characters, alias_merges):
            known_characters: 规范角色名列表
            alias_merges: 别名到规范名的映射（只包含 alias != canonical）
    """
    if not run_id:
        return [], {}
    
    result = conn.execute(
        text(
            """
            SELECT alias_map FROM disambig_checkpoint WHERE run_id = :run_id
            """
        ),
        {"run_id": run_id},
    ).fetchone()
    
    if not result or not result[0]:
        return [], {}
    
    import json

    raw_data = json.loads(result[0])
    if not isinstance(raw_data, dict):
        return [], {}

    known_canonical_names = raw_data.get("known_canonical_names")
    alias_merges_list = raw_data.get("alias_merges")
    if not isinstance(known_canonical_names, list) or not isinstance(alias_merges_list, list):
        return [], {}

    alias_merges_dict = {
        str(alias): str(canonical)
        for alias, canonical in alias_merges_list
        if isinstance(alias, str) and isinstance(canonical, str) and alias != canonical
    }
    return [str(name) for name in known_canonical_names if isinstance(name, str)], alias_merges_dict

    return [], {}
