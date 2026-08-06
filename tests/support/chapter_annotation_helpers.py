"""章节正式标注与数据库图测试夹具"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import select

from src.agents.annotation.schema import (
    ChapterAnnotation,
    EntityRef,
    Evidence,
    FactPayload,
    FactPushOutput,
    RepresentativeNodeSelector,
)
from src.storage.models import Chunk, Novel
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
    for chunk_id, (chapter_id, text_value) in enumerate(zip(resolved_chapter_ids, texts, strict=True)):
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


def evidence(reason: str, chapter_id: int = 1) -> dict[str, Any]:
    """2026-08-05 用于构造全文唯一 Evidence 测试值"""
    return {"reason": reason, "chapterid": chapter_id}


def character_fact(
    *,
    chunk_id: int,
    name: str,
    action: str,
    role_function: str = "主体",
    emotion: str = "neutral",
    chapter_id: int = 1,
) -> dict[str, Any]:
    """2026-08-05 用于构造章节人物事实测试值"""
    return {
        "chunk_id": chunk_id,
        "evidence": evidence(action, chapter_id),
        "confidence": "high",
        "entity": {"name": name, "entity_type": "character"},
        "role_function": role_function,
        "action": action,
        "action_type": "行为",
        "emotion": emotion,
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
    confidence: str = "high",
    directionality: str = "directed",
    relation_semantics: str = "ordinary",
    representative_endpoint: str | None = None,
    representative_node_id: str | None = None,
    chapter_id: int = 1,
) -> dict[str, Any]:
    """2026-08-05 用于构造章节关系事实测试值"""
    return {
        "chunk_id": chunk_id,
        "evidence": evidence(evidence_reason or f"{from_name}{relation_type}{to_name}", chapter_id),
        "confidence": confidence,
        "from_entity": {"name": from_name, "entity_type": from_entity_type},
        "to_entity": {"name": to_name, "entity_type": to_entity_type},
        "relation_type": relation_type,
        "change_kind": change_kind,
        "directionality": directionality,
        "relation_semantics": relation_semantics,
        "representative_node": (
            {
                "endpoint": representative_endpoint,
                "node_id": representative_node_id,
            }
            if representative_endpoint is not None or representative_node_id is not None
            else None
        ),
    }


def dialogue_fact(
    *,
    chunk_id: int,
    content: str,
    speaker: str | None,
    tone: str | None = None,
    chapter_id: int = 1,
) -> dict[str, Any]:
    """2026-08-05 用于构造章节对话事实测试值"""
    return {
        "chunk_id": chunk_id,
        "evidence": evidence(content, chapter_id),
        "confidence": "high",
        "content": content,
        "speaker": (
            {"name": speaker, "entity_type": "character"}
            if speaker is not None
            else None
        ),
        "tone": tone,
        "is_inner_monologue": False,
    }


def identity_relation_output(
    *,
    subject_name: str,
    object_name: str,
    representative_endpoint: str | None = None,
    representative_node_id: str | None = None,
    assertion: str = "affirmed",
    chapter_id: int = 1,
) -> FactPushOutput:
    """2026-08-06 用于构造两个独立人物节点之间的同一人物关系输出"""
    has_single_selector = (representative_endpoint is None) != (representative_node_id is None)
    if assertion == "affirmed" and not has_single_selector:
        raise ValueError("常用节点测试选择器必须恰好指定 endpoint 或 node_id")
    if assertion == "negated" and (representative_endpoint is not None or representative_node_id is not None):
        raise ValueError("否定同一人物关系测试输出不允许选择常用节点")
    return FactPushOutput(
        output_kind="fact",
        source_case_ids=[],
        evidence=Evidence(reason=f"{subject_name}与{object_name}确认是同一人物", chapterid=chapter_id),
        payload=FactPayload(
            fact_type="relation",
            subject=EntityRef(name=subject_name, entity_type="character"),
            predicate="同一人物",
            object=EntityRef(name=object_name, entity_type="character"),
            scope="global",
            assertion=assertion,
            confidence="high",
            directionality="bidirectional",
            relation_semantics="same_character",
            representative_node=(
                RepresentativeNodeSelector(
                    endpoint=representative_endpoint,
                    node_id=representative_node_id,
                )
                if has_single_selector
                else None
            ),
        ),
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
    states: list[dict[str, Any]] | None = None,
    locations: list[dict[str, Any]] | None = None,
    events: list[dict[str, Any]] | None = None,
) -> str:
    """2026-08-06 用于写入正式章节标注并通过生产入口持久化数据库图"""
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
    emotional_valences = emotional_valences or {}
    event_types = event_types or {}
    pivot_chunks = pivot_chunks or set()
    cliffhanger_chunks = cliffhanger_chunks or set()
    annotation = ChapterAnnotation.model_validate(
        {
            "chapter_summary": f"章节 {chapter_id} 测试摘要",
            "segments": [
                {
                    "chunk_id": row.chunk_id,
                    "summary": f"chunk {row.chunk_id} 摘要",
                    "emotional_valence": emotional_valences.get(row.chunk_id, "neutral"),
                    "event_type": event_types.get(row.chunk_id, "铺垫"),
                    "pivot_moment": row.chunk_id in pivot_chunks,
                    "cliffhanger": row.chunk_id in cliffhanger_chunks,
                }
                for row in chunk_rows
            ],
            "characters": characters or [],
            "locations": locations or [],
            "dialogues": dialogues or [],
            "events": events or [],
            "relations": relations or [],
            "states": states or [],
        }
    )
    row = ChapterAnnotationRepository(session).add_annotation(
        run_id=run_id,
        chapter_id=chapter_id,
        annotation=annotation,
        initial_finish=annotation,
        revision_payload={},
    )
    persist_completion_graph(
        session=session,
        annotation=row,
        fact_outputs=[],
    )
    session.commit()
    return row.annotation_id
