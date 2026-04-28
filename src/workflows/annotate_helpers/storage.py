"""
标注辅助函数模块 - 结果存储







本模块包含结果存储相关的函数
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
    将 Phase2 伏笔结果合并回 ChunkAnnotation 视图


    """
    return merge_annotation_foreshadowing(annotation, foreshadowing)


def _build_dialogue_snapshots(
    dialogues: list[tuple[int, str]] | None,
    dialogue_speakers: dict[int, list[str]] | None = None,
    dialogue_tones: dict[int, str] | None = None,
    dialogue_identity_clues: dict[int, str | None] | None = None,
) -> tuple[list[DialogueSnapshot], list[int]]:
    """
    将 Phase3 结果转换为可落库的 DialogueSnapshot 列表


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
    执行 annotation/stats repository 写入

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
