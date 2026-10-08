"""本领域的独立只读投影，不返回 HTTP 模型"""

from __future__ import annotations

from sqlalchemy.orm import Session

from src.fact_graph.character_reference_policy import is_global_character_surface_name
from src.storage.repositories.annotation.repository import AnnotationRepository
from src.storage.repositories.annotation.rows import (
    CharacterFactRow,
    DialogueFactRow,
)


def fetch_chapter_characters_full(session: Session, run_id: str) -> list[CharacterFactRow]:
    """2026-08-05 用于从数据库图人物事实展开 章节人物记录"""
    rows: list[CharacterFactRow] = []
    for fact in AnnotationRepository(session).fetch_graph_facts(run_id, content_kind="character_observation"):
        content = dict(fact.content)
        entity = content.get("entity")
        if not isinstance(entity, dict):
            continue
        name = str(entity.get("name") or "").strip()
        if entity.get("entity_type") != "character" or not is_global_character_surface_name(name):
            continue
        rows.append(
            CharacterFactRow(
                chapter_id=int(content["chapter_id"]),
                name=name,
                surface_name=name,
                reference_kind="global_character",
                reference_slot=None,
                resolved_global_name=name,
                global_skip_reason=None,
                role_function=str(content["role_function"]),
                action=str(content["action"]),
                emotion_score=content["emotion"],
            )
        )
    return rows


def fetch_character_emotion_sequence(session: Session, run_id: str) -> list[CharacterFactRow]:
    """2026-08-05 用于按章节顺序读取人物情绪事实序列"""
    sequence_map = AnnotationRepository(session).fetch_chapter_sequence_map(run_id)
    return sorted(
        fetch_chapter_characters_full(session, run_id),
        key=lambda row: (sequence_map.get(row.chapter_id, row.chapter_id), row.chapter_id),
    )


def fetch_chapter_dialogues_full(session: Session, run_id: str) -> list[DialogueFactRow]:
    """2026-08-11 用于从对话记录表展开 章节对话记录

    2026-09-17 说话人存图实体 id：这里按 id 取实体名（不再按名字形态判断是否存在），
    并保留两道过滤——实体必须是 character、名字必须是可作全局角色名的形态
    （代词/泛指/引用位名不算说话人）。
    """
    rows: list[DialogueFactRow] = []
    entities_by_id = AnnotationRepository(session).fetch_entities_by_id(run_id)
    for record in AnnotationRepository(session).fetch_dialogue_records(run_id):
        speaker_id = record.speaker
        speaker_entity = entities_by_id.get(str(speaker_id)) if speaker_id is not None else None
        valid_speaker: str | None = None
        if speaker_entity is not None:
            speaker_name = str(speaker_entity.canonical_name).strip()
            if (
                speaker_name
                and str(speaker_entity.entity_type) == "character"
                and is_global_character_surface_name(speaker_name)
            ):
                valid_speaker = speaker_name
        speaker_names = [valid_speaker] if valid_speaker else []
        speaker_references = (
            [
                {
                    "surface_name": valid_speaker,
                    "reference_kind": "global_character",
                    "reference_slot": None,
                    "resolved_global_name": valid_speaker,
                    "can_enter_global_character": True,
                    "global_skip_reason": None,
                }
            ]
            if valid_speaker
            else []
        )
        rows.append(
            DialogueFactRow(
                chapter_id=int(record.chapter_id),
                speaker=speaker_names,
                speaker_references=speaker_references,
                length=len(record.content),
                tone=record.tone,
            )
        )
    return rows
