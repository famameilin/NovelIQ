"""
创建时间: 2026-03-12
创建者: TraeAI
任务: 项目文件结构整理与拆解 - 从 operations.py 拆分完整性检查函数

本模块包含数据库完整性检查相关的函数，用于断点续传判断各阶段是否完成。
"""

from __future__ import annotations

import sqlite3


def has_chunks(conn: sqlite3.Connection) -> bool:
    cursor = conn.execute("SELECT COUNT(*) FROM chunks")
    count = cursor.fetchone()[0]
    return count > 0


def has_annotations(conn: sqlite3.Connection) -> bool:
    cursor = conn.execute("SELECT COUNT(*) FROM chunk_annotation")
    count = cursor.fetchone()[0]
    return count > 0


def has_aggregated_data(conn: sqlite3.Connection) -> bool:
    emotion_count = conn.execute("SELECT COUNT(*) FROM emotion_curve").fetchone()[0]
    rhythm_count = conn.execute("SELECT COUNT(*) FROM rhythm_curve").fetchone()[0]
    return emotion_count > 0 and rhythm_count > 0


def has_topic_data(conn: sqlite3.Connection) -> bool:
    cursor = conn.execute("SELECT COUNT(*) FROM chunk_topics")
    count = cursor.fetchone()[0]
    return count > 0


def has_diagnosis_data(conn: sqlite3.Connection) -> bool:
    """
    2026-03-11: Claude创建，用于断点续传判断诊断阶段是否完成
    检查cloud_analysis表是否有数据
    """
    cursor = conn.execute("SELECT COUNT(*) FROM cloud_analysis")
    count = cursor.fetchone()[0]
    return count > 0


def is_preprocess_complete(conn: sqlite3.Connection) -> bool:
    """
    2026-03-11: Claude创建，检查预处理阶段是否完成
    chunks表有数据即视为完成
    """
    cursor = conn.execute("SELECT COUNT(*) FROM chunks")
    count = cursor.fetchone()[0]
    return count > 0


def is_annotate_complete(conn: sqlite3.Connection) -> bool:
    """
    2026-03-11: Claude创建，检查标注阶段是否完成
    annotations数量应该等于chunks数量
    """
    chunks_count = conn.execute("SELECT COUNT(*) FROM chunks").fetchone()[0]
    annotations_count = conn.execute("SELECT COUNT(*) FROM chunk_annotation").fetchone()[0]
    return chunks_count > 0 and annotations_count >= chunks_count


def is_aggregate_complete(conn: sqlite3.Connection) -> bool:
    """
    2026-03-11: Claude创建，检查聚合阶段是否完成
    emotion_curve和rhythm_curve数量应该等于chunks数量
    """
    chunks_count = conn.execute("SELECT COUNT(*) FROM chunks").fetchone()[0]
    emotion_count = conn.execute("SELECT COUNT(*) FROM emotion_curve").fetchone()[0]
    rhythm_count = conn.execute("SELECT COUNT(*) FROM rhythm_curve").fetchone()[0]
    return chunks_count > 0 and emotion_count >= chunks_count and rhythm_count >= chunks_count


def is_topic_model_complete(conn: sqlite3.Connection) -> bool:
    """
    2026-03-11: Claude创建，检查主题建模阶段是否完成
    chunk_topics表有数据即视为完成
    """
    cursor = conn.execute("SELECT COUNT(*) FROM chunk_topics")
    count = cursor.fetchone()[0]
    return count > 0


def is_diagnose_complete(conn: sqlite3.Connection) -> bool:
    """
    2026-03-11: Claude创建，检查诊断阶段是否完成
    cloud_analysis表有数据即视为完成
    """
    cursor = conn.execute("SELECT COUNT(*) FROM cloud_analysis")
    count = cursor.fetchone()[0]
    return count > 0
