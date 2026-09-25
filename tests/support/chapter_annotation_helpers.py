"""章节正式标注与数据库图测试夹具（agent-semantic-v2 合同）"""

from __future__ import annotations

import uuid
from dataclasses import replace
from typing import Any
from uuid import uuid4

from sqlalchemy import select

from src.agents.annotation.candidates import extract_dialogue_candidates
from src.agents.annotation.schema import (
    RELATION_DEFINITIONS,
    BoundChapterAnnotation,
    BoundCharacterObservation,
    BoundDialogue,
    BoundEntity,
    BoundEvent,
    BoundRelation,
    ChapterMetricsInput,
    EntityType,
    EventParticipantInput,
)
from src.chunking.chunker import Chunk as ChunkerChunk
from src.chunking.chunker import split_chunk_paragraphs
from src.storage.models import Chapter, Novel
from src.storage.repositories import (
    ChapterAnnotationRepository,
    ChapterRepository,
    DialogueRecordRepository,
    RunRepository,
)
from src.storage.repositories.graph import persist_completion_graph


def create_run_with_chunks(
    session: Any,
    *,
    texts: list[str],
    chapter_ids: list[int] | None = None,
    title: str = "章节事实测试",
) -> tuple[str, str]:
    """2026-08-05 用于创建带真实章节身份的小说运行与原文章节"""
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
    chunks: list[ChunkerChunk] = []
    for chunk_index, (chapter_id, text_value) in enumerate(zip(resolved_chapter_ids, texts, strict=True)):
        chunks.append(
            ChunkerChunk(
                index=chunk_index,
                chapter_id=chapter_id,
                start=offset,
                end=offset + len(text_value),
                text=text_value,
            )
        )
        offset += len(text_value)
    # M9a-2：chunks 表合并进 chapters——正文切片经 ChapterRepository 落库
    # （缺失章节行以默认结构补建，见 insert_chapter_texts）
    ChapterRepository(session).insert_chapter_texts(run_id, chunks)
    session.commit()
    # 2026-08-14 二期：annotate 阶段要求段落事实源存在（章节段落边界查询），
    # helper 同步插入段落行（一次传入全部章节，paragraph_id 全局连续），
    # token_count 用简单切分填充
    from src.storage.repositories import ParagraphRepository

    spans = [replace(span, token_count=max(1, len(span.text) // 2)) for span in split_chunk_paragraphs(chunks)]
    if spans:
        ParagraphRepository(session).insert_paragraphs(run_id, spans)
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
    chapter_id: int,
    name: str,
    action: str,
    role_function: str = "主体",
    emotion: int = 0,
) -> dict[str, Any]:
    """2026-08-11 用于构造章内人物观察输入测试值"""
    return {
        "chapter_id": chapter_id,
        "character": name,
        "role_function": role_function,
        "action": action,
        "emotion": emotion,
        "_entity_specs": [_entity_spec(name, "character")],
    }


def relation_fact(
    *,
    chapter_id: int,
    from_name: str,
    to_name: str,
    relation_type: str,
    from_entity_type: EntityType = "character",
    to_entity_type: EntityType = "character",
) -> dict[str, Any]:
    """2026-08-12 用于构造章内三字段关系边输入测试值（本章确认存在的边）"""
    return {
        "chapter_id": chapter_id,
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
    chapter_id: int,
    content: str,
    speaker: str | None,
    tone: str | None = None,
    verdict: str = "dialogue",
) -> dict[str, Any]:
    """2026-08-11 用于构造按系统候选对齐的对话输入测试值"""
    return {
        "candidate_content": content,
        "verdict": verdict,
        "speaker": speaker,
        "tone": tone,
        "chapter_id": chapter_id,
        "_entity_specs": [_entity_spec(speaker, "character")] if speaker else [],
    }


def identity_relation_output(
    *,
    subject_name: str,
    object_name: str,
    effective_chapter_id: int = 0,
) -> dict[str, Any]:
    """2026-08-07 用于构造同一人物关系的测试标注项"""
    return relation_fact(
        chapter_id=effective_chapter_id,
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
    """2026-08-11 用于把事实隐含实体注册到当前章实体目录"""
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


def make_bound_event(
    *,
    description: str,
    participants: list[dict[str, str]] | None = None,
    tree_id: str | None = None,
    node_id: str | None = None,
    parent_node_id: str | None = None,
    cause_role: str = "root",
) -> BoundEvent:
    """2026-08-22 用于构造测试用 BoundEvent（服务端 uuid 派生 id；证据由持久化层章级盖章）"""
    return BoundEvent(
        node_id=node_id or str(uuid4()),
        tree_id=tree_id or f"tree-{uuid4()}",
        parent_node_id=parent_node_id,
        cause_role=cause_role,
        description=description,
        participants=[EventParticipantInput(entity=p["entity"], role=p["role"]) for p in (participants or [])],
    )


def persist_chapter_annotation(
    session: Any,
    *,
    run_id: str,
    chapter_id: int,
    emotional_valences: dict[int, int] | None = None,
    event_types: dict[int, str] | None = None,
    pivot_chapters: set[int] | None = None,
    cliffhanger_chapters: set[int] | None = None,
    characters: list[dict[str, Any]] | None = None,
    dialogues: list[dict[str, Any]] | None = None,
    relations: list[dict[str, Any]] | None = None,
    entity_attributes: dict[tuple[int, str], dict[str, Any]] | None = None,
    resolved_cases: list[Any] | None = None,
    events: list[dict[str, Any]] | None = None,
    foreshadowings: list[dict[str, Any]] | None = None,
) -> str:
    """2026-08-12 用于写入最新合同 BoundChapterAnnotation 并通过生产图入口持久化

    M9a-2：chunks 表合并进 chapters 后，章节正文取自 chapters 表。

    2026-08-19：events 每项含 description/participants/tree_id/cause_role
    （缺省 root；2026-09-14 起 causal_event_refs 退役）。
    2026-08-22事件 id 由 uuid4 服务端派生，伏笔 setup_node_id
    直接指向本章事件节点（setup_event_index 为 1 基序号映射）。
    2026-08-22 重构：节点不再携带锚点；章级证据由持久化层盖章。
    """
    chapter_row = session.execute(
        select(Chapter).where(Chapter.run_id == run_id, Chapter.chapter_id == chapter_id)
    ).scalar_one_or_none()
    if chapter_row is None or chapter_row.text is None:
        raise ValueError(f"章节没有原文: run_id={run_id} chapter_id={chapter_id}")
    chapter_text_by_id = {chapter_id: str(chapter_row.text)}
    candidate_by_content: dict[tuple[int, str], Any] = {}
    for chapter_id, chapter_text in chapter_text_by_id.items():
        for candidate in extract_dialogue_candidates(chapter_id, chapter_text):
            candidate_by_content[(chapter_id, candidate.content)] = candidate

    keys = list(chapter_text_by_id)
    directories = {key: {"entities": []} for key in keys}
    observations_by_chapter: dict[int, list[BoundCharacterObservation]] = {key: [] for key in keys}
    dialogues_by_chapter: dict[int, list[BoundDialogue]] = {key: [] for key in keys}
    relations_by_chapter: dict[int, list[BoundRelation]] = {key: [] for key in keys}

    for fact in characters or []:
        chapter_id = int(fact["chapter_id"])
        if chapter_id not in chapter_text_by_id:
            raise ValueError(f"测试事实引用了非本章章节: {chapter_id}")
        for spec in fact.get("_entity_specs", []):
            _register_entity(
                directories[chapter_id],
                name=spec["name"],
                entity_type=spec["entity_type"],
                tags=spec.get("tags"),
            )
        observations_by_chapter[chapter_id].append(
            BoundCharacterObservation(
                character=fact["character"],
                role_function=fact["role_function"],
                action=fact["action"],
                emotion=fact["emotion"],
            )
        )

    for fact in relations or []:
        chapter_id = int(fact.get("chapter_id", -1))
        if chapter_id not in chapter_text_by_id:
            raise ValueError(f"测试事实引用了非本章章节: {chapter_id}")
        for spec in fact.get("_entity_specs", []):
            _register_entity(
                directories[chapter_id],
                name=spec["name"],
                entity_type=spec["entity_type"],
                tags=spec.get("tags"),
            )
        definition = RELATION_DEFINITIONS[fact["relation_type"]]
        relations_by_chapter[chapter_id].append(
            BoundRelation(
                from_entity=fact["from_entity"],
                to_entity=fact["to_entity"],
                relation_type=fact["relation_type"],
                directionality=definition["directionality"],
                relation_semantics=definition["semantics"],
            )
        )

    for fact in dialogues or []:
        chapter_id = int(fact["chapter_id"])
        content = fact["candidate_content"]
        candidate = candidate_by_content.get((chapter_id, content))
        if candidate is None:
            raise ValueError(f"测试对话未出现在系统候选原文中: chapter_id={chapter_id} content={content!r}")
        speaker = fact["speaker"]
        if speaker is not None:
            _register_entity(
                directories[chapter_id],
                name=speaker,
                entity_type="character",
            )
        dialogues_by_chapter[chapter_id].append(
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

    for (chapter_id, entity_name), attributes in (entity_attributes or {}).items():
        if chapter_id not in chapter_text_by_id:
            raise ValueError(f"测试实体属性引用了非本章章节: {chapter_id}")
        registered = [entity for entity in directories[chapter_id]["entities"] if entity.name == entity_name]
        if registered:
            registered[0].attributes = dict(attributes)
        else:
            directories[chapter_id]["entities"].append(
                BoundEntity(
                    name=entity_name,
                    entity_type="character",
                    attributes=dict(attributes),
                )
            )

    chapter_annotations: list[BoundChapterAnnotation] = []
    for chapter_id, _chapter_text in chapter_text_by_id.items():
        bound_events: list[BoundEvent] = []
        for event_spec in events or []:
            event_participants = [{"entity": p, "role": "主体"} for p in event_spec.get("participants", [])]
            for p in event_spec.get("participants", []):
                _register_entity(
                    directories[chapter_id],
                    name=p,
                    entity_type="character",
                )
            bound_event = make_bound_event(
                description=event_spec["description"],
                participants=event_participants,
                tree_id=event_spec.get("tree_id"),
                node_id=event_spec.get("node_id"),
                parent_node_id=event_spec.get("parent_node_id"),
                cause_role=event_spec.get("cause_role", "root"),
            )
            # 2026-09-13 伏笔即事件树：isforeshadowing=true 的章内事件即伏笔树根
            # （2026-09-14 伏笔属性收敛：expected_payoff_family 退役）
            if event_spec.get("isforeshadowing"):
                bound_event.is_foreshadow_setup = True
                bound_event.payoff_likelihood = event_spec.get("payoff_likelihood", "medium")
            bound_events.append(bound_event)
        # 2026-09-13 伏笔即事件树：setup_event_index（1 基）指向的章内事件即伏笔树根
        for fs_spec in foreshadowings or []:
            root_event = bound_events[int(fs_spec["setup_event_index"]) - 1]
            root_event.is_foreshadow_setup = True
            root_event.payoff_likelihood = fs_spec.get("payoff_likelihood", "medium")
        chapter_annotations.append(
            BoundChapterAnnotation(
                metrics=ChapterMetricsInput(
                    summary=f"章节 {chapter_id} 摘要",
                    emotional_valence=(emotional_valences or {}).get(chapter_id, 0),
                    narrative_function=(event_types or {}).get(chapter_id, "铺垫"),
                    pivot_moment=chapter_id in (pivot_chapters or set()),
                    cliffhanger=chapter_id in (cliffhanger_chapters or set()),
                ),
                character_observations=observations_by_chapter[chapter_id],
                dialogues=dialogues_by_chapter[chapter_id],
                events=bound_events,
            )
        )
    # 2026-09-04 单一写面：实体/关系不再是章标注字段，改为派生 FactGraph 操作日志
    # （在章循环之后收集，事件参与者登记的实体一并覆盖）
    entity_ops: list[dict[str, Any]] = []
    relation_assert_ops: list[dict[str, Any]] = []
    for chapter_id, _chapter_text in chapter_text_by_id.items():
        for entity in directories[chapter_id]["entities"]:
            entity_ops.append(
                {
                    "name": entity.name,
                    "entity_type": str(entity.entity_type),
                    "tags": list(entity.tags or []),
                    "description": entity.description,
                    "attributes": dict(entity.attributes or {}),
                    "chapter_id": chapter_id,
                }
            )
        for relation in relations_by_chapter[chapter_id]:
            relation_assert_ops.append(
                {
                    "from_entity": str(relation.from_entity),
                    "to_entity": str(relation.to_entity),
                    "relation_type": str(relation.relation_type),
                    "chapter_id": chapter_id,
                }
            )
    # 2026-09-19 章即块拍平：单章一份标注，chapter_id 身份由 add_annotation 行携带
    annotation = chapter_annotations[0]
    row = ChapterAnnotationRepository(session).add_annotation(
        run_id=run_id,
        chapter_id=chapter_id,
        annotation=annotation,
    )
    persist_completion_graph(
        session=session,
        annotation=row,
        resolved_cases=resolved_cases or [],
        entity_ops=entity_ops,
        relation_assert_ops=relation_assert_ops,
        authorized_text_chapter_ids=set(chapter_text_by_id),
    )
    DialogueRecordRepository(session).sync_dialogues(
        run_id=run_id,
        chapter_id=chapter_id,
        dialogues=annotation.dialogues,
    )
    session.commit()
    return row.annotation_id
