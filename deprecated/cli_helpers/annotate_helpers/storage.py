"""
创建时间: 2026-03-13
创建者: TraeAI
任务: 项目文件结构整理与拆解 - 标注辅助函数模块

本模块包含结果存储相关的函数。
"""

from __future__ import annotations


def _store_annotation_results(
    conn,
    chunk_id: int,
    annotation,
    chunk_text: str,
    use_context_enhancement: bool,
) -> None:
    """
    存储标注结果

    创建时间: 2026-03-13
    创建者: TraeAI
    任务: refactor-analysis-layer-functions
    说明: 从 run_annotate 中提取，负责存储单个chunk的标注结果
    """
    from deprecated.storage.operations.annotation_ops import (
        insert_chunk_annotation,
        insert_chunk_characters,
        insert_chunk_dialogues,
        insert_chunk_relations,
    )
    from deprecated.storage.operations.stats_ops import insert_character_appearances, insert_chunk_summary

    insert_chunk_annotation(conn, chunk_id, annotation)

    if annotation.characters:
        insert_chunk_characters(conn, chunk_id, annotation.characters)
        if use_context_enhancement:
            from src.context import update_entity_registry

            update_entity_registry(conn, chunk_id, annotation.characters)

    if annotation.relations:
        insert_chunk_relations(conn, chunk_id, annotation.relations)

    if annotation.dialogues:
        from src.cli.annotate import compute_dialogue_lengths

        speakers = [d.speaker for d in annotation.dialogues]
        dialogue_lengths = compute_dialogue_lengths(chunk_text, speakers)
        insert_chunk_dialogues(conn, chunk_id, annotation.dialogues, dialogue_lengths)

    if annotation.chunk_summary:
        insert_chunk_summary(conn, chunk_id, annotation.chunk_summary)

    if annotation.character_appearances:
        insert_character_appearances(conn, chunk_id, annotation.character_appearances)
