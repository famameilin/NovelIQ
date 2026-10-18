"""所属领域的字段契约与结果处理"""

from __future__ import annotations

from typing import Any

from loguru import logger

from src.fact_graph.character_reference_policy import decide_character_reference
from src.fact_graph.read import ExportGraphAuthorityView, KnowledgeGraphAuthorityService
from src.storage import Storage


def build_name_resolution(
    annotation_repo: Storage,
    run_id: str,
    preferred_names: list[str] | None = None,
) -> dict[str, str]:
    """2026-08-09 用于把别名角色名归一到代表角色名"""
    authority_service = KnowledgeGraphAuthorityService.from_session(annotation_repo)
    entities = authority_service.build_export_view(run_id).canonical_entities
    preferred = set(preferred_names or [])
    name_resolution: dict[str, str] = {}
    for entity in entities:
        aliases = [alias for alias in entity.aliases if alias and alias != entity.name]
        representative = entity.name
        if preferred:
            chosen = next((alias for alias in aliases if alias in preferred), None)
            if chosen is not None:
                representative = chosen
        for alias in aliases:
            name_resolution[alias] = representative
        if representative != entity.name:
            name_resolution[entity.name] = representative
    return name_resolution


def partition_chapter_characters(
    rows: Any,
    *,
    valid_character_names: set[str] | None = None,
) -> dict[int, list[dict[str, Any]]]:
    """按章归组角色提及，丢弃未解析的局部引用与悬空引用（可见面契约）"""
    grouped: dict[int, list[dict[str, Any]]] = {}
    for character_row in rows:
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
        grouped.setdefault(chapter_id, []).append(
            {
                "name": character_name,
                "surface_name": raw_name,
                "reference_kind": getattr(character_row, "reference_kind", None) or decision.reference_kind,
                "reference_slot": getattr(character_row, "reference_slot", None) or decision.reference_slot,
                "resolved_global_name": character_name,
                "global_skip_reason": decision.global_skip_reason,
                "role_function": str(character_row.role_function) if character_row.role_function else None,
                "action": str(character_row.action) if character_row.action else None,
                "emotion_score": str(character_row.emotion_score) if character_row.emotion_score else None,
            }
        )
    return grouped


def partition_chapter_relations(
    export_graph_view: ExportGraphAuthorityView,
    *,
    valid_character_names: set[str] | None = None,
) -> dict[int, list[dict[str, Any]]]:
    """按章归组关系变化（只取 change_kind == relation）"""
    grouped: dict[int, list[dict[str, Any]]] = {}
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
        grouped.setdefault(chapter_id, []).append(
            {
                "from_char": from_char,
                "to_char": to_char,
                "from_reference_kind": None,
                "to_reference_kind": None,
                "resolved_from_global_name": from_char,
                "resolved_to_global_name": to_char,
                "reference_skip_reason": None,
                "type": graph_change.relation_type or "",
                # 2026-08-13 P2：changes 为空时兜底，避免隐式不变量破坏后 IndexError
                "change": str(graph_change.changes[0].get("change_kind") or "refine")
                if graph_change.changes
                else "refine",
            }
        )
    return grouped


def partition_chapter_dialogues(
    rows: Any,
    *,
    valid_character_names: set[str] | None = None,
) -> dict[int, list[dict[str, Any]]]:
    """按章归组对话，未解析/悬空 speaker 置空后整段无有效说话人则丢弃"""
    grouped: dict[int, list[dict[str, Any]]] = {}
    for dialogue_row in rows:
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
        grouped.setdefault(chapter_id, []).append(
            {
                "speaker": valid_speakers,
                "speaker_references": speaker_references,
                "length": int(dialogue_row.length) if dialogue_row.length is not None else None,
            }
        )
    return grouped
