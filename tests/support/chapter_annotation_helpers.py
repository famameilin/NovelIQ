"""章节正式标注与数据库图测试夹具"""

from __future__ import annotations

import hashlib
import uuid
from typing import Any

from sqlalchemy import select

from src.agents.annotation.schema import ChapterFinish
from src.storage.models import Chunk, GraphEntity, Novel
from src.storage.repositories import ChapterAnnotationRepository, RunRepository
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


def evidence(reason: str, chunk_id: int) -> list[dict[str, Any]]:
    """2026-08-07 用于构造当前原文 chunk 授权的 TextEvidence 列表"""
    return [{"reason": reason, "chunk_id": chunk_id}]


def _stable_ref(prefix: str, *parts: object) -> str:
    """2026-08-07 用于为测试实体和事实生成短稳定 ref"""
    digest = hashlib.sha256(
        "\x1f".join(str(part) for part in parts).encode("utf-8")
    ).hexdigest()[:12]
    return f"{prefix}_{digest}"


def _entity_spec(
    *,
    name: str,
    entity_type: str,
    chunk_id: int,
) -> dict[str, Any]:
    """2026-08-07 用于附加测试夹具解析实体目录需要的内部元数据"""
    return {
        "ref": _stable_ref(entity_type, name),
        "name": name,
        "entity_type": entity_type,
        "chunk_id": chunk_id,
    }


def character_fact(
    *,
    chunk_id: int,
    name: str,
    action: str,
    role_function: str = "主体",
    emotion: str = "neutral",
    chapter_id: int = 1,
) -> dict[str, Any]:
    """2026-08-07 用于构造逐 chunk 人物观察测试值"""
    del chapter_id
    entity = _entity_spec(name=name, entity_type="character", chunk_id=chunk_id)
    return {
        "chunk_id": chunk_id,
        "ref": _stable_ref("character_observation", chunk_id, name, action),
        "evidence": evidence(action, chunk_id),
        "confidence": "high",
        "entity_ref": entity["ref"],
        "role_function": role_function,
        "action": action,
        "action_type": "行为",
        "emotion": emotion,
        "_entity_specs": [entity],
    }


def relation_fact(
    *,
    chunk_id: int,
    from_name: str,
    to_name: str,
    relation_type: str,
    from_entity_type: str = "character",
    to_entity_type: str = "character",
    evidence_reason: str | None = None,
    change_kind: str = "assert",
    relation_id: str | None = None,
    confidence: str = "high",
    directionality: str = "directed",
    relation_semantics: str = "ordinary",
    representative_endpoint: str | None = None,
    representative_node_id: str | None = None,
    chapter_id: int = 1,
) -> dict[str, Any]:
    """2026-08-07 用于构造逐 chunk 稳定关系测试值"""
    del chapter_id
    from_entity = _entity_spec(
        name=from_name,
        entity_type=from_entity_type,
        chunk_id=chunk_id,
    )
    to_entity = _entity_spec(
        name=to_name,
        entity_type=to_entity_type,
        chunk_id=chunk_id,
    )
    representative_ref = None
    representative_existing_entity_id = None
    if representative_endpoint == "subject":
        representative_ref = from_entity["ref"]
    elif representative_endpoint == "object":
        representative_ref = to_entity["ref"]
    elif representative_node_id is not None:
        representative_existing_entity_id = int(
            representative_node_id.removeprefix("entity:")
        )
    return {
        "chunk_id": chunk_id,
        "ref": _stable_ref(
            "relation",
            chunk_id,
            from_name,
            to_name,
            relation_type,
            change_kind,
        ),
        "evidence": evidence(
            evidence_reason or f"{from_name}{relation_type}{to_name}",
            chunk_id,
        ),
        "confidence": confidence,
        "from_ref": from_entity["ref"],
        "to_ref": to_entity["ref"],
        "relation_type": relation_type,
        "change_kind": change_kind,
        "relation_id": relation_id,
        "directionality": directionality,
        "relation_semantics": relation_semantics,
        "representative_ref": representative_ref,
        "representative_existing_entity_id": representative_existing_entity_id,
        "_entity_specs": [from_entity, to_entity],
    }


def dialogue_fact(
    *,
    chunk_id: int,
    content: str,
    speaker: str | None,
    tone: str | None = None,
    chapter_id: int = 1,
) -> dict[str, Any]:
    """2026-08-07 用于构造逐 chunk 带原文锚点的对话测试值"""
    del chapter_id
    speaker_entity = (
        _entity_spec(name=speaker, entity_type="character", chunk_id=chunk_id)
        if speaker is not None
        else None
    )
    return {
        "chunk_id": chunk_id,
        "ref": _stable_ref("dialogue", chunk_id, content),
        "evidence": evidence(content, chunk_id),
        "confidence": "high",
        "content": content,
        "start": 0,
        "end": len(content),
        "speaker_ref": speaker_entity["ref"] if speaker_entity is not None else None,
        "tone": tone,
        "is_inner_monologue": False,
        "_entity_specs": [speaker_entity] if speaker_entity is not None else [],
    }


def identity_relation_output(
    *,
    subject_name: str,
    object_name: str,
    representative_endpoint: str | None = None,
    representative_node_id: str | None = None,
    assertion: str = "affirmed",
    effective_chunk_id: int = 0,
    relation_id: str | None = None,
) -> dict[str, Any]:
    """2026-08-07 用于构造同一人物关系的测试标注项"""
    change_kind = "assert" if assertion == "affirmed" else "retract"
    return relation_fact(
        chunk_id=effective_chunk_id,
        from_name=subject_name,
        to_name=object_name,
        relation_type="同一人物",
        change_kind=change_kind,
        relation_id=relation_id,
        directionality="bidirectional",
        relation_semantics="same_character",
        representative_endpoint=representative_endpoint,
        representative_node_id=representative_node_id,
    )


def _mention(text_value: str, name: str, chunk_id: int) -> dict[str, Any]:
    """2026-08-07 用于从测试原文生成实体 mention 或稳定替代锚点"""
    start = text_value.find(name)
    mention_text = name
    if start < 0:
        start = 0
        mention_text = text_value[:1]
    return {
        "chunk_id": chunk_id,
        "start": start,
        "end": start + len(mention_text),
        "text": mention_text,
    }


def _clean_fact(
    fact: dict[str, Any],
    *,
    chunk_text: str,
    dialogue: bool = False,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """2026-08-07 用于移除夹具元数据并修正对话原文区间"""
    payload = dict(fact)
    entity_specs = [
        dict(item)
        for item in payload.pop("_entity_specs", [])
        if item is not None
    ]
    if dialogue:
        start = chunk_text.find(str(payload["content"]))
        if start < 0:
            raise ValueError(f"测试对话未出现在原文中: {payload['content']!r}")
        payload["start"] = start
        payload["end"] = start + len(str(payload["content"]))
    return payload, entity_specs


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
    states: list[dict[str, Any]] | None = None,
    locations: list[dict[str, Any]] | None = None,
    events: list[dict[str, Any]] | None = None,
    visible_relation_ids: set[str] | None = None,
) -> str:
    """2026-08-07 用于写入 ChapterFinish 并通过生产图入口持久化"""
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
    chunk_payloads = {
        int(row.chunk_id): {
            "chunk_id": int(row.chunk_id),
            "summary": f"chunk {row.chunk_id} 摘要",
            "metrics": {
                "emotional_valence": (emotional_valences or {}).get(row.chunk_id, "neutral"),
                "event_type": (event_types or {}).get(row.chunk_id, "铺垫"),
                "pivot_moment": row.chunk_id in (pivot_chunks or set()),
                "cliffhanger": row.chunk_id in (cliffhanger_chunks or set()),
            },
            "character_observations": [],
            "location_observations": [],
            "dialogues": [],
            "events": [],
            "relations": [],
            "states": [],
            "foreshadowings": [],
        }
        for row in chunk_rows
    }
    entity_specs_by_ref: dict[str, dict[str, Any]] = {}
    source_groups = (
        ("character_observations", characters or [], False),
        ("location_observations", locations or [], False),
        ("dialogues", dialogues or [], True),
        ("events", events or [], False),
        ("relations", relations or [], False),
        ("states", states or [], False),
    )
    for field_name, facts, dialogue in source_groups:
        for fact in facts:
            chunk_id = int(fact.get("chunk_id", -1))
            if chunk_id not in chunk_payloads:
                raise ValueError(f"测试事实引用了非本章 chunk: {chunk_id}")
            payload, entity_specs = _clean_fact(
                fact,
                chunk_text=chunk_text_by_id[chunk_id],
                dialogue=dialogue,
            )
            payload.pop("chunk_id", None)
            chunk_payloads[chunk_id][field_name].append(payload)
            for spec in entity_specs:
                entity_specs_by_ref[spec["ref"]] = spec

    existing_entities = {
        str(row.canonical_name): row
        for row in session.execute(
            select(GraphEntity).where(GraphEntity.run_id == run_id)
        ).scalars()
    }
    entity_directory = {
        "characters": [],
        "locations": [],
        "objects": [],
        "organizations": [],
    }
    entity_field_by_type = {
        "character": "characters",
        "location": "locations",
        "object": "objects",
        "organization": "organizations",
    }
    visible_graph_entity_ids: set[int] = set()
    for spec in entity_specs_by_ref.values():
        existing = existing_entities.get(spec["name"])
        if existing is not None:
            visible_graph_entity_ids.add(int(existing.entity_id))
        entity_directory[entity_field_by_type[spec["entity_type"]]].append(
            {
                "ref": spec["ref"],
                "name": spec["name"],
                "existing_entity_id": (
                    int(existing.entity_id)
                    if existing is not None
                    else None
                ),
                "mentions": [
                    _mention(
                        chunk_text_by_id[spec["chunk_id"]],
                        spec["name"],
                        spec["chunk_id"],
                    )
                ],
                "confidence": "high",
                "evidence": evidence(
                    f"{spec['name']} 在本章出现",
                    spec["chunk_id"],
                ),
            }
        )

    coverage = [
        {
            "chunk_id": int(row.chunk_id),
            "entities": True,
            "character_observations": True,
            "location_observations": True,
            "dialogues": True,
            "events": True,
            "relations": True,
            "states": True,
            "foreshadowings": True,
        }
        for row in chunk_rows
    ]
    finish = ChapterFinish.model_validate(
        {
            "chapter_summary": f"章节 {chapter_id} 测试摘要",
            "entities": entity_directory,
            "chunks": list(chunk_payloads.values()),
            "coverage": coverage,
        }
    )
    row = ChapterAnnotationRepository(session).add_annotation(
        run_id=run_id,
        chapter_id=chapter_id,
        finish=finish,
        initial_finish=finish,
        revision_payloads=[],
    )
    persist_completion_graph(
        session=session,
        annotation=row,
        pulled_results=[],
        authorized_text_chunk_ids=set(chunk_text_by_id),
        visible_graph_fact_refs=set(),
        visible_relation_ids=visible_relation_ids or set(),
        visible_graph_entity_ids=visible_graph_entity_ids,
    )
    session.commit()
    return row.annotation_id
