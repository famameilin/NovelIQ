from __future__ import annotations

from typing import Any, List

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
修改内容: 使用 SQLAlchemy text() 包装 SQL 语句，"""


def build_diagnosis_payload(conn: Session, novel_id: str | None = None) -> dict:
    logger.info(
        "[云端模型] 构建诊断payload开始: novel_id=%s",
        novel_id,
    )

    pivot_blocks = []
    for row in _fetch_pivot_blocks(conn, limit=settings.diagnosis.pivot_blocks_limit):
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
    for row in _fetch_pivot_moments(conn, limit=settings.diagnosis.pivot_moments_limit):
        chunk_id, chunk_text = row
        pivot_moments.append(
            {
                "chunk_id": chunk_id,
                "text": chunk_text[: settings.diagnosis.text_limits.pivot_moment] if chunk_text else "",
            }
        )
    logger.info("[云端模型] 获取pivot_moments: count=%d", len(pivot_moments))

    high_tension = []
    for row in _fetch_high_tension_chunks(conn, limit=settings.diagnosis.high_tension_limit):
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
    for row in _fetch_relation_changes(conn, limit=settings.diagnosis.relation_changes_limit):
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
    for row in _fetch_foreshadowing_chunks(conn, limit=settings.diagnosis.foreshadowing_limit):
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
        conn, max_chars=settings.diagnosis.first_last_max_chars
    )
    logger.info("[云端模型] 获取首尾摘要: first_len=%d last_len=%d", len(first_summary), len(last_summary))

    topic_words = _fetch_topic_words(conn, top_n=settings.diagnosis.topic_words_top_n)
    logger.info("[云端模型] 获取topic_words: count=%d", len(topic_words))

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
    }

    logger.info(
        "[云端模型] 诊断payload构建完成: pivot_blocks=%d pivot_moments=%d high_tension=%d relations=%d foreshadowing=%d topic_words=%d",
        len(pivot_blocks),
        len(pivot_moments),
        len(high_tension),
        len(relations),
        len(foreshadowing),
        len(topic_words),
    )

    return payload


def _fetch_pivot_blocks(conn: Session, limit: int = 20) -> List[Any]:
    result = conn.execute(
        text(
            """
            SELECT c.chunk_id, c.text, a.event_type
            FROM chunks c
            JOIN chunk_annotation a ON c.chunk_id = a.chunk_id
            WHERE a.pivot_moment = 1
            ORDER BY c.chunk_id
            LIMIT :limit
            """
        ),
        {"limit": limit},
    )
    return list(result.fetchall())


def _fetch_pivot_moments(conn: Session, limit: int = 10) -> List[Any]:
    result = conn.execute(
        text(
            """
            SELECT c.chunk_id, c.text
            FROM chunks c
            JOIN chunk_annotation a ON c.chunk_id = a.chunk_id
            WHERE a.event_type = '高潮'
            ORDER BY c.chunk_id
            LIMIT :limit
            """
        ),
        {"limit": limit},
    )
    return list(result.fetchall())


def _fetch_high_tension_chunks(conn: Session, limit: int = 10) -> List[Any]:
    result = conn.execute(
        text(
            """
            SELECT c.chunk_id, c.text, ABS(e.net_density) as tension
            FROM chunks c
            JOIN emotion_curve e ON c.chunk_id = e.chunk_id
            WHERE ABS(e.net_density) > 0.01
            ORDER BY tension DESC
            LIMIT :limit
            """
        ),
        {"limit": limit},
    )
    return list(result.fetchall())


def _fetch_relation_changes(conn: Session, limit: int = 50) -> List[Any]:
    result = conn.execute(
        text(
            """
            SELECT chunk_id, from_char, to_char, type, change
            FROM chunk_relations
            ORDER BY chunk_id
            LIMIT :limit
            """
        ),
        {"limit": limit},
    )
    return list(result.fetchall())


def _fetch_foreshadowing_chunks(conn: Session, limit: int = 30) -> List[Any]:
    result = conn.execute(
        text(
            """
            SELECT c.chunk_id, c.text, a.foreshadowing_type, a.foreshadowing_desc
            FROM chunks c
            JOIN chunk_annotation a ON c.chunk_id = a.chunk_id
            WHERE a.has_foreshadowing = 1
            ORDER BY c.chunk_id
            LIMIT :limit
            """
        ),
        {"limit": limit},
    )
    return list(result.fetchall())


def _fetch_first_last_chunk_summary(conn: Session, max_chars: int = 500) -> tuple:
    result = conn.execute(text("SELECT chunk_id, text FROM chunks ORDER BY chunk_id"))
    chunks = result.fetchall()
    if not chunks:
        return "", ""
    first_text = chunks[0][1][:max_chars] if chunks[0][1] else ""
    last_text = chunks[-1][1][:max_chars] if chunks[-1][1] else ""
    return first_text, last_text


def _fetch_topic_words(conn: Session, top_n: int = 10) -> List[dict]:
    result = conn.execute(
        text(
            """
            SELECT topic_id, SUM(topic_weight) as total_weight
            FROM chunk_topics
            GROUP BY topic_id
            ORDER BY total_weight DESC
            """
        )
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
