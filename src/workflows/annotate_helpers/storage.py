"""
创建时间: 2026-03-13
创建者: TraeAI
任务: 项目文件结构整理与拆解 - 标注辅助函数模块
修改时间: 2026-03-14
修改者: TraeAI
修改内容: 从 cli.annotate_helpers 迁移到 workflows.annotate_helpers，解决循环依赖

说明: 本模块从 src.cli.annotate_helpers 迁移而来，用于解决 workflows 与 cli 之间的循环依赖问题。
      导入路径已更新: from src.cli.annotate import -> from src.workflows.annotate import

修改时间: 2026-03-14
修改者: TraeAI
任务: workflows 使用 Repository 模式重构
修改内容: 添加 run_id 参数支持，使用 AnnotationRepository/StatsRepository 替代直接调用 operations 函数

修改时间: 2026-03-15
修改者: TraeAI
任务: storage-layer-decoupling
修改内容: 移除向后兼容代码，只使用 Repository 模式

本模块包含结果存储相关的函数。
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
    """
    存储标注结果

    创建时间: 2026-03-13
    创建者: TraeAI
    任务: refactor-analysis-layer-functions
    说明: 从 run_annotate 中提取，负责存储单个chunk的标注结果

    修改时间: 2026-03-14
    修改者: TraeAI
    任务: workflows 使用 Repository 模式重构
    修改内容: 添加 run_id 参数，支持 Repository 模式

    修改时间: 2026-03-15
    修改者: TraeAI
    任务: storage-layer-decoupling
    修改内容: 移除向后兼容代码，run_id 改为必需参数

    修改时间: 2026-03-17
    修改者: TraeAI
    任务: 修复foreshadowing数据丢失问题
    修改内容: 添加foreshadowing参数，存储独立的foreshadowing分析结果
    """
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
