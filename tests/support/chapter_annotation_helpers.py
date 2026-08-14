"""章节正式标注与数据库图测试夹具（agent-semantic-v1 合同）"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import select

from src.agents.annotation.candidates import extract_dialogue_candidates
from src.agents.annotation.schema import (
    RELATION_DEFINITIONS,
    BoundChapterAnnotation,
    BoundCharacterObservation,
    BoundChunkAnnotation,
    BoundDialogue,
    BoundEntity,
    BoundEntityDirectory,
    BoundRelation,
    ChunkMetricsInput,
    EntityType,
)
from src.storage.models import Chunk, Novel
from src.storage.repositories import ChapterAnnotationRepository, DialogueRecordRepository, RunRepository
from src.storage.repositories.graph import persist_completion_graph


def create_run_with_chunks(
    session: Any,
    *,
    texts: list[str],
    chapter_ids: list[int] | None = None,
    title: str = "章节事实测试",
) -> tuple[str, str]:
    """2026-08-05 用于创建带真实章节身份的小说运行与原文 chunk"""
    novel_id = uuid.uuid4().hex[:8]
    run_id = str(uuid.uuid4())
    session.add(
        Novel(
            novel_id=novel_id,
            filename=f"{novel_id}.txt",
            file_path=f"tests/{novel_id}.txt",
            file_size=sum(len(text) for text in texts),
            title=title,
        )
    )
    session.commit()
    RunRepository(session).create_run(
        novel_id=novel_id,
        source_path="test",
        title=title,
        run_id=run_id,
    )
    resolved_chapter_ids = chapter_ids or [1] * len(texts)
    if len(resolved_chapter_ids) != len(texts):
        raise ValueError("chapter_ids 必须与 texts 等长")
    offset = 0
    rows: list[Chunk] = []
    for chunk_id, (chapter_id, text_value) in enumerate(
        zip(resolved_chapter_ids, texts, strict=True)
    ):
        rows.append(
            Chunk(
                chunk_id=chunk_id,
                chapter_id=chapter_id,
                char_offset=offset,
                char_end_offset=offset + len(text_value),
                text=text_value,
                run_id=run_id,
            )
        )
        offset += len(text_value)
    session.add_all(rows)
    session.commit()
    return novel_id, run_id


def _entity_spec(
    name: str,
    entity_type: EntityType,
    tags: list[str] | None = None,
) -> dict[str, str | list[str]]:
    """2026-08-08 用于声明事实隐含的实体名称、大类与可选标签"""
    spec: dict[str, str | list[str]] = {"name": name, "entity_type": entity_type}
    if tags:
        spec["tags"] = tags
    return spec


def character_fact(
    *,
    chunk_id: int,
    name: str,
    action: str,
    role_function: str = "主体",
    emotion: str = "neutral",
    chapter_id: int = 1,
) -> dict[str, Any]:
    """2026-08-11 用于构造逐 chunk 人物观察输入测试值"""
    del chapter_id
    return {
        "chunk_id": chunk_id,
        "character": name,
        "role_function": role_function,
        "action": action,
        "emotion": emotion,
        "_entity_specs": [_entity_spec(name, "character")],
    }


def relation_fact(
    *,
    chunk_id: int,
    from_name: str,
    to_name: str,
    relation_type: str,
    from_entity_type: EntityType = "character",
    to_entity_type: EntityType = "character",
    chapter_id: int = 1,
) -> dict[str, Any]:
    """2026-08-12 用于构造逐 chunk 三字段关系边输入测试值（本章确认存在的边）"""
    del chapter_id
    return {
        "chunk_id": chunk_id,
        "from_entity": from_name,
        "to_entity": to_name,
        "relation_type": relation_type,
        "_entity_specs": [
            _entity_spec(from_name, from_entity_type),
            _entity_spec(to_name, to_entity_type),
        ],
    }


def dialogue_fact(
    *,
    chunk_id: int,
    content: str,
    speaker: str | None,
    tone: str | None = None,
    verdict: str = "dialogue",
    chapter_id: int = 1,
) -> dict[str, Any]:
    """2026-08-11 用于构造按系统候选对齐的对话输入测试值"""
    del chapter_id
    return {
        "candidate_content": content,
        "verdict": verdict,
        "speaker": speaker,
        "tone": tone,
        "_chunk_id": chunk_id,
        "_entity_specs": [_entity_spec(speaker, "character")] if speaker else [],
    }


def identity_relation_output(
    *,
    subject_name: str,
    object_name: str,
    effective_chunk_id: int = 0,
) -> dict[str, Any]:
    """2026-08-07 用于构造同一人物关系的测试标注项"""
    return relation_fact(
        chunk_id=effective_chunk_id,
        from_name=subject_name,
        to_name=object_name,
        relation_type="同一人物",
    )


def _register_entity(
    directory: dict[str, list[BoundEntity]],
    *,
    name: str,
    entity_type: EntityType,
    tags: list[str] | None = None,
) -> None:
    """2026-08-11 用于把事实隐含实体注册到当前 chunk 实体目录"""
    for existing in directory["entities"]:
        if existing.name == name:
            return
    directory["entities"].append(
        BoundEntity(
            name=name,
            entity_type=entity_type,
            tags=tags or [],
        )
    )


def persist_chapter_annotation(
    session: Any,
    *,
    run_id: str,
    chapter_id: int,
    emotional_valences: dict[int, str] | None = None,
    event_types: dict[int, str] | None = None,
    pivot_chunks: set[int] | None = None,
    cliffhanger_chunks: set[int] | None = None,
    characters: list[dict[str, Any]] | None = None,
    dialogues: list[dict[str, Any]] | None = None,
    relations: list[dict[str, Any]] | None = None,
    entity_attributes: dict[tuple[int, str], dict[str, Any]] | None = None,
    resolved_cases: list[Any] | None = None,
) -> str:
    """2026-08-12 用于写入最新合同 BoundChapterAnnotation 并通过生产图入口持久化"""
    chunk_rows = list(
        session.execute(
            select(Chunk)
            .where(Chunk.run_id == run_id, Chunk.chapter_id == chapter_id)
            .order_by(Chunk.chunk_id)
        )
        .scalars()
        .all()
    )
    if not chunk_rows:
        raise ValueError(f"章节没有原文 chunk: run_id={run_id} chapter_id={chapter_id}")
    chunk_text_by_id = {int(row.chunk_id): str(row.text) for row in chunk_rows}
    candidate_by_content: dict[tuple[int, str], Any] = {}
    for chunk_id, chunk_text in chunk_text_by_id.items():
        for candidate in extract_dialogue_candidates(chunk_id, chunk_text):
            candidate_by_content[(chunk_id, candidate.content)] = candidate

    directories: dict[int, dict[str, list[BoundEntity]]] = {
        chunk_id: {"entities": []}
        for chunk_id in chunk_text_by_id
    }
    observations_by_chunk: dict[int, list[BoundCharacterObservation]] = {
        chunk_id: [] for chunk_id in chunk_text_by_id
    }
    dialogues_by_chunk: dict[int, list[BoundDialogue]] = {
        chunk_id: [] for chunk_id in chunk_text_by_id
    }
    relations_by_chunk: dict[int, list[BoundRelation]] = {
        chunk_id: [] for chunk_id in chunk_text_by_id
    }

    for fact in characters or []:
        chunk_id = int(fact["_chunk_id"]) if "_chunk_id" in fact else int(fact.get("chunk_id", -1))
        if chunk_id not in chunk_text_by_id:
            raise ValueError(f"测试事实引用了非本章 chunk: {chunk_id}")
        for spec in fact.get("_entity_specs", []):
            _register_entity(
                directories[chunk_id],
                name=spec["name"],
                entity_type=spec["entity_type"],
                tags=spec.get("tags"),
            )
        observations_by_chunk[chunk_id].append(
            BoundCharacterObservation(
                character=fact["character"],
                role_function=fact["role_function"],
                action=fact["action"],
                emotion=fact["emotion"],
            )
        )

    for fact in relations or []:
        chunk_id = int(fact.get("chunk_id", -1))
        if chunk_id not in chunk_text_by_id:
            raise ValueError(f"测试事实引用了非本章 chunk: {chunk_id}")
        for spec in fact.get("_entity_specs", []):
            _register_entity(
                directories[chunk_id],
                name=spec["name"],
                entity_type=spec["entity_type"],
                tags=spec.get("tags"),
            )
        definition = RELATION_DEFINITIONS[fact["relation_type"]]
        relations_by_chunk[chunk_id].append(
            BoundRelation(
                from_entity=fact["from_entity"],
                to_entity=fact["to_entity"],
                relation_type=fact["relation_type"],
                directionality=definition["directionality"],
                relation_semantics=definition["semantics"],
            )
        )

    for fact in dialogues or []:
        chunk_id = int(fact["_chunk_id"])
        content = fact["candidate_content"]
        candidate = candidate_by_content.get((chunk_id, content))
        if candidate is None:
            raise ValueError(
                f"测试对话未出现在系统候选原文中: chunk_id={chunk_id} content={content!r}"
            )
        speaker = fact["speaker"]
        if speaker is not None:
            _register_entity(
                directories[chunk_id],
                name=speaker,
                entity_type="character",
            )
        dialogues_by_chunk[chunk_id].append(
            BoundDialogue(
                candidate_index=1,
                candidate_key=candidate.candidate_key,
                content=candidate.content,
                start=candidate.start,
                end=candidate.end,
                speaker=speaker,
                tone=fact["tone"],
                is_inner_monologue=fact.get("verdict", "dialogue") == "inner_monologue",
            )
        )

    for (chunk_id, entity_name), attributes in (entity_attributes or {}).items():
        if chunk_id not in chunk_text_by_id:
            raise ValueError(f"测试实体属性引用了非本章 chunk: {chunk_id}")
        registered = [
            entity
            for entity in directories[chunk_id]["entities"]
            if entity.name == entity_name
        ]
        if registered:
            registered[0].attributes = dict(attributes)
        else:
            directories[chunk_id]["entities"].append(
                BoundEntity(
                    name=entity_name,
                    entity_type="character",
                    attributes=dict(attributes),
                )
            )

    chunks: list[BoundChunkAnnotation] = []
    for chunk_id, chunk_text in chunk_text_by_id.items():
        del chunk_text
        chunks.append(
            BoundChunkAnnotation(
                chunk_id=chunk_id,
                metrics=ChunkMetricsInput(
                    summary=f"chunk {chunk_id} 摘要",
                    emotional_valence=(emotional_valences or {}).get(chunk_id, "neutral"),
                    narrative_function=(event_types or {}).get(chunk_id, "铺垫"),
                    pivot_moment=chunk_id in (pivot_chunks or set()),
                    cliffhanger=chunk_id in (cliffhanger_chunks or set()),
                ),
                entities=BoundEntityDirectory.model_validate(directories[chunk_id]),
                character_observations=observations_by_chunk[chunk_id],
                dialogues=dialogues_by_chunk[chunk_id],
                events=[],
                relations=relations_by_chunk[chunk_id],
                foreshadowings=[],
            )
        )
    annotation = BoundChapterAnnotation(
        chapter_summary=f"章节 {chapter_id} 测试摘要",
        chunks=chunks,
    )
    row = ChapterAnnotationRepository(session).add_annotation(
        run_id=run_id,
        chapter_id=chapter_id,
        annotation=annotation,
    )
    persist_completion_graph(
        session=session,
        annotation=row,
        resolved_cases=resolved_cases or [],
        authorized_text_chunk_ids=set(chunk_text_by_id),
    )
    for chunk in annotation.chunks:
        DialogueRecordRepository(session).sync_dialogues(
            run_id=run_id,
            chapter_id=chapter_id,
            chunk_id=chunk.chunk_id,
            dialogues=chunk.dialogues,
        )
    session.commit()
    return row.annotation_id
