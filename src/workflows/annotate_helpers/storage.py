"""
标注辅助函数模块 - 结果存储

创建时间: 2026-03-13
创建者: TraeAI
任务: 项目文件结构整理与拆解

修改历史:
- 2026-03-14: 从 cli.annotate_helpers 迁移，解决循环依赖
- 2026-03-14: 添加 run_id 参数，使用 Repository 模式
- 2026-03-15: 移除向后兼容代码，只使用 Repository 模式
- 2026-03-17: 添加 foreshadowing 参数，存储独立的 foreshadowing 分析结果

说明: 本模块包含结果存储相关的函数。
"""

from __future__ import annotations


def _store_annotation_results(
    conn,
    chunk_id: int,
    annotation,
    chunk_text: str,
    use_context_enhancement: bool,
    run_id: str,
    foreshadowing=None,
) -> None:
    """存储标注结果"""
    from src.storage.repositories import AnnotationRepository, StatsRepository

    ann_repo = AnnotationRepository(conn)
    stats_repo = StatsRepository(conn)

    ann_repo.insert_chunk_annotation(run_id, chunk_id, annotation)

    if annotation.characters:
        ann_repo.insert_chunk_characters(run_id, chunk_id, annotation.characters)
        if use_context_enhancement:
            from src.context import update_entity_registry
            from src.storage.repositories import EntityRepository

            entity_repo = EntityRepository(conn)
            update_entity_registry(entity_repo, run_id, chunk_id, annotation.characters)

    if annotation.relations:
        ann_repo.insert_chunk_relations(run_id, chunk_id, annotation.relations)

    if annotation.dialogues:
        # 使用标注结果中的content字段计算对话长度
        # 创建(说话人, 长度)的列表
        dialogue_lengths = []
        for dialogue in annotation.dialogues:
            # 如果content字段存在，使用其长度；否则为0
            content_length = len(dialogue.content) if hasattr(dialogue, "content") and dialogue.content else 0
            dialogue_lengths.append(content_length)
        ann_repo.insert_chunk_dialogues(run_id, chunk_id, annotation.dialogues, dialogue_lengths)

    if annotation.chunk_summary:
        stats_repo.insert_chunk_summary(run_id, chunk_id, annotation.chunk_summary)

    if annotation.character_appearances:
        stats_repo.insert_character_appearances(run_id, chunk_id, annotation.character_appearances)

    # 存储独立的foreshadowing分析结果
    if foreshadowing is not None:
        ann_repo.insert_foreshadowing(run_id, chunk_id, foreshadowing)
