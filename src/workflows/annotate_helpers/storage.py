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

修改时间: 2026-04-23
修改者: Codex
任务: p2-store-annotation-results-split
修改内容: 拆分伏笔合并、对话快照转换与 repository 写入逻辑，降低存储主函数复杂度

修改时间: 2026-04-23
任务: annotation-projector-runtime-landing
修改内容: 伏笔合并与对话快照转换委托 annotation projectors，storage 只保留 repository 编排。

说明: 本模块包含结果存储相关的函数。
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import TYPE_CHECKING

from src.models.local.annotation.projectors.dialogue import build_dialogue_snapshots
from src.models.local.annotation.projectors.foreshadowing import merge_annotation_foreshadowing

if TYPE_CHECKING:
    from src.models.local.schema import DialogueSnapshot


def _merge_annotation_foreshadowing(annotation, foreshadowing):
    """
    将 Phase2 伏笔结果合并回 ChunkAnnotation 视图。

    创建时间: 2026-04-23
    任务: p2-store-annotation-results-split
    新建原因: 把伏笔字段拼装从存储主流程拆出，便于单独核对 annotation 结构变换。

    修改时间: 2026-04-23
    任务: annotation-projector-runtime-landing
    修改内容: 保留兼容入口，实际合并逻辑委托 foreshadowing projector。
    """
    return merge_annotation_foreshadowing(annotation, foreshadowing)


def _build_dialogue_snapshots(
    dialogues: list[tuple[int, str]] | None,
    dialogue_speakers: dict[int, list[str]] | None = None,
    dialogue_tones: dict[int, str] | None = None,
    dialogue_identity_clues: dict[int, str | None] | None = None,
) -> tuple[list[DialogueSnapshot], list[int]]:
    """
    将 Phase3 结果转换为可落库的 DialogueSnapshot 列表。

    创建时间: 2026-04-23
    任务: p2-store-annotation-results-split
    新建原因: 把对话快照组装从 repository 写入流程中拆开，避免存储时混入数据转换细节。

    修改时间: 2026-04-23
    任务: annotation-projector-runtime-landing
    修改内容: 保留兼容入口，实际快照转换委托 dialogue projector。
    """
    return build_dialogue_snapshots(
        dialogues,
        dialogue_speakers=dialogue_speakers,
        dialogue_tones=dialogue_tones,
        dialogue_identity_clues=dialogue_identity_clues,
    )


def _persist_annotation_repositories(
    conn,
    *,
    run_id: str,
    chunk_id: int,
    annotation,
    foreshadowing=None,
    dialogue_snapshots: Sequence[DialogueSnapshot] | None = None,
    dialogue_lengths: list[int] | None = None,
    relations=None,
) -> None:
    """
    执行 annotation/stats repository 写入。

    创建时间: 2026-04-23
    任务: p2-store-annotation-results-split
    新建原因: 将 repository 落库动作与前置数据变换分离，便于后续继续细化存储边界。
    """
    from src.storage.repositories import AnnotationRepository

    ann_repo = AnnotationRepository(conn)
    try:
        thread_projection = None
        if foreshadowing is not None and foreshadowing.has_foreshadowing:
            thread_projection = ann_repo.sync_foreshadowing_thread(
                run_id,
                chunk_id=chunk_id,
                result=foreshadowing,
            )

        merged_annotation = merge_annotation_foreshadowing(
            annotation,
            foreshadowing,
            resolved_setup_id=thread_projection.setup_id if thread_projection is not None else None,
            resolved_setup_summary=thread_projection.setup_summary if thread_projection is not None else None,
            resolved_payoff_likelihood=(
                thread_projection.payoff_likelihood if thread_projection is not None else None
            ),
        )
        ann_repo.insert_chunk_annotation(run_id, chunk_id, merged_annotation, commit=False)

        if merged_annotation.characters:
            ann_repo.insert_chunk_characters(run_id, chunk_id, merged_annotation.characters, commit=False)

        if dialogue_snapshots and dialogue_lengths:
            ann_repo.insert_chunk_dialogues(run_id, chunk_id, dialogue_snapshots, dialogue_lengths, commit=False)

        if relations:
            ann_repo.insert_chunk_relations(run_id, chunk_id, relations, commit=False)

        if merged_annotation.chunk_summary:
            from src.storage.repositories import StatsRepository

            stats_repo = StatsRepository(conn)
            stats_repo.insert_chunk_summary(run_id, chunk_id, merged_annotation.chunk_summary, commit=False)

        if foreshadowing is not None:
            ann_repo.insert_foreshadowing(run_id, chunk_id, foreshadowing, commit=False)

        conn.commit()
    except Exception:
        conn.rollback()
        raise


def _store_annotation_results(
    conn,
    chunk_id: int,
    annotation,
    chunk_text: str,
    use_context_enhancement: bool,
    run_id: str,
    foreshadowing=None,
    alias_map: dict[str, str] | None = None,
    dialogue_speakers: dict[int, list[str]] | None = None,
    dialogues: list[tuple[int, str]] | None = None,
    dialogue_tones: dict[int, str] | None = None,
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

    修改时间: 2026-04-08
    修改者: TraeAI
    任务: fix-multi-speaker-support
    修改内容: 删除 dialogue_evidences 参数，speaker 改为 list[str]

    修改时间: 2026-04-23
    修改者: Codex
    任务: p2-store-annotation-results-split
    修改内容: 改为编排 helper，主函数只负责组织伏笔合并、对话快照转换与 repository 写入。
    """
    dialogue_snapshots, dialogue_lengths = _build_dialogue_snapshots(
        dialogues,
        dialogue_speakers=dialogue_speakers,
        dialogue_tones=dialogue_tones,
        dialogue_identity_clues=dialogue_identity_clues,
    )
    _persist_annotation_repositories(
        conn,
        run_id=run_id,
        chunk_id=chunk_id,
        annotation=annotation,
        foreshadowing=foreshadowing,
        dialogue_snapshots=dialogue_snapshots,
        dialogue_lengths=dialogue_lengths,
        relations=relations,
    )
