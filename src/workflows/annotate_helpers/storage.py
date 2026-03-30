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
- 2026-03-20: 修复伏笔字段空值问题，在存储前合并 Phase2 伏笔结果到 ChunkAnnotation
- 2026-03-20: 修复对话长度全为0问题，使用 LLM 判断说话者

修改时间: 2026-03-21
修改者: TraeAI
任务: refactor-phase3-to-annotation-layer
修改内容: 将对话归属判断导入路径从 sentence.py 改为 models/local/annotation/phase3.py

修改时间: 2026-03-29
修改者: TraeAI
任务: remove-unused-annotation-fields
修改内容: 移除 relations、character_appearances、chunk_summary 存储逻辑

修改时间: 2026-03-30
修改者: TraeAI
任务: feature/chunk-summary-timeline-only
修改内容: 恢复 chunk_summary 存储逻辑，仅用于 Timeline 展示，不参与消歧证据链

说明: 本模块包含结果存储相关的函数。
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    pass


def _store_annotation_results(
    conn,
    chunk_id: int,
    annotation,
    chunk_text: str,
    use_context_enhancement: bool,
    run_id: str,
    foreshadowing=None,
    alias_map: dict[str, str] | None = None,
    dialogue_speakers: dict[int, str] | None = None,
    dialogues: list[tuple[int, str]] | None = None,
    dialogue_tones: dict[int, str] | None = None,
    dialogue_evidences: dict[int, str] | None = None,
    dialogue_identity_clues: dict[int, str | None] | None = None,
    relations=None,
) -> None:
    """存储标注结果

    创建时间: 2026-03-14
    创建者: TraeAI
    任务: 重构标注结果存储

    修改时间: 2026-03-20
    修改者: TraeAI
    任务: fix-entity-registry-alias-map
    修改内容: 添加 alias_map 参数，传递给 update_entity_registry 以正确映射别名

    修改时间: 2026-03-20
    修改者: TraeAI
    任务: analyze-dialogue-length-zero
    修改内容: 添加 client 参数，使用 compute_dialogue_lengths_v2 替代 compute_dialogue_lengths

    修改时间: 2026-03-21
    修改者: TraeAI
    任务: fix-phase3-not-called
    修改内容: 添加 dialogue_lengths 参数，由调用方（phase.py）计算后传入

    修改时间: 2026-03-22
    修改者: TraeAI
    任务: phase3-return-speaker-to-storage
    修改内容: 添加 dialogue_speakers 参数，使用 phase3 判断的说话者替代 phase1 的

    修改时间: 2026-03-22
    修改者: TraeAI
    任务: phase3-return-dialogues-to-storage
    修改内容: 添加 dialogues 参数，完全由 Phase3 构建对话列表，不再依赖 annotation.dialogues

    修改时间: 2026-03-25
    修改者: TraeAI
    任务: fix-tone-distribution-semantic-error
    修改内容: 添加 dialogue_tones 参数，传递对话语气类型

    修改时间: 2026-03-28
    修改者: TraeAI
    任务: fix-unknown-speaker-context
    修改内容: 添加 dialogue_evidences 参数，传递对话判断依据

    修改时间: 2026-03-29
    修改者: TraeAI
    任务: use-phase3-identity-clue-in-disambiguation
    修改内容: 添加 dialogue_identity_clues 参数，传递身份线索
    """
    from src.models.local.schema import DialogueSnapshot
    from src.storage.repositories import AnnotationRepository

    ann_repo = AnnotationRepository(conn)

    if foreshadowing is not None:
        from src.models.local.schema import ChunkAnnotation

        annotation = ChunkAnnotation(
            emotional_valence=annotation.emotional_valence,
            event_type=annotation.event_type,
            pivot_moment=annotation.pivot_moment,
            cliffhanger=annotation.cliffhanger,
            chunk_summary=annotation.chunk_summary,
            has_foreshadowing=foreshadowing.has_foreshadowing,
            foreshadowing_type=foreshadowing.foreshadowing_type,
            foreshadowing_desc=(
                f"{foreshadowing.anchor_text} - {foreshadowing.anchor_reason}"
                if foreshadowing.has_foreshadowing else ""
            ),
            characters=annotation.characters,
            dialogues=annotation.dialogues,
        )

    ann_repo.insert_chunk_annotation(run_id, chunk_id, annotation)

    if annotation.characters:
        ann_repo.insert_chunk_characters(run_id, chunk_id, annotation.characters)

    if dialogues:
        effective_dialogues = []
        for dialogue_idx, content in dialogues:
            speaker = dialogue_speakers.get(dialogue_idx) if dialogue_speakers else None
            tone = dialogue_tones.get(dialogue_idx) if dialogue_tones else None
            evidence = dialogue_evidences.get(dialogue_idx) if dialogue_evidences else None
            identity_clue = dialogue_identity_clues.get(dialogue_idx) if dialogue_identity_clues else None
            effective_dialogues.append(
                DialogueSnapshot(
                    speaker=speaker,
                    content=content,
                    tone=tone,
                    evidence=evidence or "",
                    identity_clue=identity_clue,
                )
            )
        lengths = [len(content) for _, content in dialogues]
        ann_repo.insert_chunk_dialogues(run_id, chunk_id, effective_dialogues, lengths)

    if relations:
        ann_repo.insert_chunk_relations(run_id, chunk_id, relations)

    if annotation.chunk_summary:
        from src.storage.repositories import StatsRepository
        stats_repo = StatsRepository(conn)
        stats_repo.insert_chunk_summary(run_id, chunk_id, annotation.chunk_summary)

    if foreshadowing is not None:
        ann_repo.insert_foreshadowing(run_id, chunk_id, foreshadowing)
