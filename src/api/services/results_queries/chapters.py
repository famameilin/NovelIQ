"""
章节查询组装器

说明: 承载章节标注相关查询组装逻辑（M9a-2：chunk 命名下线，
仅保留章节标注展开，数据源为 chapter_annotations 表）。
"""

from __future__ import annotations

from collections import defaultdict
from typing import Any

from loguru import logger

from src.api.models.responses import (
    ChapterAnnotation,
    ChapterCharacter,
    ChapterDialogue,
    ChapterRelation,
)
from src.knowledge.authority import ExportGraphAuthorityView, KnowledgeGraphAuthorityService
from src.models.local.character_reference_policy import decide_character_reference
from src.storage.repositories import AnnotationRepository


def _fetch_chapter_annotations(
    run_id: str,
    annotation_repo: AnnotationRepository,
    valid_character_names: set[str] | None = None,
    export_graph_view: ExportGraphAuthorityView | None = None,
) -> list:
    """
    修改时间: 2026-04-29
    任务: 角色引用分层重构
    修改原因: chunk results 读取层需要过滤未解析代词引用，避免“我”等局部引用泄漏为全局角色。

    获取分块标注数据
    """
    annotations_raw = annotation_repo.fetch_chapter_annotations_full(run_id)
    characters_raw = annotation_repo.fetch_chapter_characters_full(run_id)
    dialogues_raw = annotation_repo.fetch_chapter_dialogues_full(run_id)

    if export_graph_view is None:
        authority_service = KnowledgeGraphAuthorityService.from_session(annotation_repo.session)
        export_graph_view = authority_service.build_export_view(run_id)

    characters_by_chunk: dict[int, list[ChapterCharacter]] = defaultdict(list)
    for character_row in characters_raw:
        chapter_id = character_row.chapter_id
        raw_name = str(getattr(character_row, "surface_name", None) or character_row.name)
        decision = decide_character_reference(
            raw_name,
            resolved_global_name=getattr(character_row, "resolved_global_name", None),
        )
        character_name = decision.resolved_global_name
        if character_name is None:
            logger.warning("跳过分块角色中的未解析局部引用: chapter_id={}, name={}", chapter_id, raw_name)
            continue
        if valid_character_names is not None and character_name not in valid_character_names:
            logger.warning("跳过分块角色中的悬空引用: chapter_id={}, name={}", chapter_id, character_name)
            continue
        characters_by_chunk[chapter_id].append(
            ChapterCharacter(
                name=character_name,
                surface_name=raw_name,
                reference_kind=getattr(character_row, "reference_kind", None) or decision.reference_kind,
                reference_slot=getattr(character_row, "reference_slot", None) or decision.reference_slot,
                resolved_global_name=character_name,
                global_skip_reason=decision.global_skip_reason,
                role_function=str(character_row.role_function) if character_row.role_function else None,
                action=str(character_row.action) if character_row.action else None,
                emotion_score=str(character_row.emotion_score) if character_row.emotion_score else None,
            )
        )

    relations_by_chunk: dict[int, list[ChapterRelation]] = defaultdict(list)
    for graph_change in export_graph_view.graph_changes:
        if graph_change.change_kind != "relation":
            continue
        chapter_id = graph_change.effective_chapter_id
        from_char = graph_change.from_name or ""
        to_char = graph_change.to_name or ""
        if valid_character_names is not None and (
            from_char not in valid_character_names or to_char not in valid_character_names
        ):
            logger.warning(
                "跳过分块关系中的悬空引用: chapter_id={}, from_char={}, to_char={}",
                chapter_id,
                from_char,
                to_char,
            )
            continue
        relations_by_chunk[chapter_id].append(
            ChapterRelation(
                from_char=from_char,
                to_char=to_char,
                from_reference_kind=None,
                to_reference_kind=None,
                resolved_from_global_name=from_char,
                resolved_to_global_name=to_char,
                reference_skip_reason=None,
                type=graph_change.relation_type or "",
                # 2026-08-13 P2：changes 为空时兜底，避免隐式不变量破坏后 IndexError
                change=str(graph_change.changes[0].get("change_kind") or "refine")
                if graph_change.changes
                else "refine",
            )
        )

    dialogues_by_chunk: dict[int, list[ChapterDialogue]] = defaultdict(list)
    for dialogue_row in dialogues_raw:
        chapter_id = dialogue_row.chapter_id
        speakers = dialogue_row.speaker or []
        if not speakers:
            continue
        valid_speakers = []
        speaker_reference_by_surface: dict[str, dict[str, Any]] = {}
        for item in getattr(dialogue_row, "speaker_references", None) or []:
            if not isinstance(item, dict):
                continue
            surface_name = str(item.get("surface_name") or "").strip()
            if surface_name:
                speaker_reference_by_surface[surface_name] = item
        speaker_references: list[dict[str, Any]] = []
        for speaker in speakers:
            reference_payload = speaker_reference_by_surface.get(str(speaker).strip(), {})
            decision = decide_character_reference(
                speaker,
                resolved_global_name=reference_payload.get("resolved_global_name"),
            )
            speaker_references.append(
                {
                    "surface_name": decision.surface_name,
                    "reference_kind": decision.reference_kind,
                    "reference_slot": reference_payload.get("reference_slot") or decision.reference_slot,
                    "resolved_global_name": decision.resolved_global_name,
                    "can_enter_global_character": decision.can_enter_global_character,
                    "global_skip_reason": decision.global_skip_reason,
                }
            )
            normalized_speaker = decision.resolved_global_name
            if normalized_speaker is None:
                logger.warning(
                    "将章节对话中的未解析局部 speaker 置空: chapter_id={}, speaker={}",
                    chapter_id,
                    speaker,
                )
                continue
            if (
                normalized_speaker
                and valid_character_names is not None
                and normalized_speaker not in valid_character_names
            ):
                logger.warning(
                    "将章节对话中的悬空 speaker 置空: chapter_id={}, speaker={}",
                    chapter_id,
                    normalized_speaker,
                )
                continue
            if normalized_speaker:
                valid_speakers.append(normalized_speaker)
        if not valid_speakers:
            continue
        dialogues_by_chunk[chapter_id].append(
            ChapterDialogue(
                speaker=valid_speakers,
                speaker_references=speaker_references,
                length=int(dialogue_row.length) if dialogue_row.length is not None else None,
            )
        )

    result: list[ChapterAnnotation] = []
    for annotation_row in annotations_raw:
        chapter_id = int(annotation_row.chapter_id)
        result.append(
            ChapterAnnotation(
                chapter_id=chapter_id,
                emotional_valence=(
                    str(annotation_row.emotional_valence) if annotation_row.emotional_valence else None
                ),
                event_type=str(annotation_row.event_type) if annotation_row.event_type else None,
                pivot_moment=(
                    bool(annotation_row.pivot_moment) if annotation_row.pivot_moment is not None else None
                ),
                cliffhanger=(
                    bool(annotation_row.cliffhanger) if annotation_row.cliffhanger is not None else None
                ),
                has_foreshadowing=(
                    bool(annotation_row.has_foreshadowing)
                    if annotation_row.has_foreshadowing is not None
                    else None
                ),
                is_strong_setup=(
                    bool(annotation_row.is_strong_setup)
                    if getattr(annotation_row, "is_strong_setup", None) is not None
                    else None
                ),
                foreshadowing_type=(
                    str(annotation_row.foreshadowing_type) if annotation_row.foreshadowing_type else None
                ),
                setup_kind=(
                    str(annotation_row.setup_kind) if getattr(annotation_row, "setup_kind", None) else None
                ),
                foreshadowing_desc=(
                    str(annotation_row.foreshadowing_desc) if annotation_row.foreshadowing_desc else None
                ),
                setup_summary=(
                    str(annotation_row.setup_summary)
                    if getattr(annotation_row, "setup_summary", None)
                    else None
                ),
                why_unresolved_now=(
                    str(annotation_row.why_unresolved_now)
                    if getattr(annotation_row, "why_unresolved_now", None)
                    else None
                ),
                expected_payoff_family=(
                    str(annotation_row.expected_payoff_family)
                    if getattr(annotation_row, "expected_payoff_family", None)
                    else None
                ),
                payoff_likelihood=(
                    str(annotation_row.payoff_likelihood)
                    if getattr(annotation_row, "payoff_likelihood", None)
                    else None
                ),
                linked_setup_id=(
                    str(annotation_row.linked_setup_id)
                    if getattr(annotation_row, "linked_setup_id", None)
                    else None
                ),
                characters=characters_by_chunk.get(chapter_id, []),
                relations=relations_by_chunk.get(chapter_id, []),
                dialogues=dialogues_by_chunk.get(chapter_id, []),
            )
        )

    return result
