"""章节事实数据库图投影测试"""

from __future__ import annotations

import uuid

from sqlalchemy import select

from src.storage.models import (
    ChapterAnnotationRecord,
    ContinuityFact,
    GraphEntityParticipant,
    GraphFact,
    GraphFactSource,
    GraphFactVersion,
    GraphRelationCurrent,
    GraphRelationEvent,
)
from src.workflows.annotate_helpers.graph_projection import (
    project_graph_tables,
    stable_annotation_fact_id,
)
from tests.support.chapter_annotation_helpers import (
    character_fact,
    create_run_with_chunks,
    evidence,
    persist_chapter_annotation,
    relation_fact,
)


def _graph_snapshot(session, run_id: str) -> tuple[list[tuple], list[tuple]]:
    """2026-08-05 用于读取可跨图重建比较的稳定事实与版本关系"""
    facts = [
        (
            row.stable_fact_id,
            row.fact_type,
            row.subject_name,
            row.predicate,
            row.active,
        )
        for row in session.execute(
            select(GraphFact)
            .where(GraphFact.run_id == run_id)
            .order_by(GraphFact.stable_fact_id)
        )
        .scalars()
        .all()
    ]
    versions = [
        (
            row.previous_stable_fact_id,
            row.current_stable_fact_id,
            row.change_kind,
        )
        for row in session.execute(
            select(GraphFactVersion)
            .where(GraphFactVersion.run_id == run_id)
            .order_by(
                GraphFactVersion.previous_stable_fact_id,
                GraphFactVersion.current_stable_fact_id,
            )
        )
        .scalars()
        .all()
    ]
    return facts, versions


def test_annotation_fact_id_is_deterministic() -> None:
    """2026-08-05 用于验证 annotation_id 与 payload 路径稳定生成同一事实 ID"""
    first = stable_annotation_fact_id("annotation-1", "relations/0")
    second = stable_annotation_fact_id("annotation-1", "relations/0")
    other = stable_annotation_fact_id("annotation-1", "relations/1")
    assert first == second
    assert first != other


def test_graph_projection_rebuild_preserves_stable_facts_and_versions(db_session) -> None:
    """2026-08-05 用于验证清空图后只凭两类事实源完整恢复稳定语义"""
    _novel_id, run_id = create_run_with_chunks(
        db_session,
        texts=["顾霜与贺重明结盟"],
        title="图重建",
    )
    annotation_id = persist_chapter_annotation(
        db_session,
        run_id=run_id,
        chapter_id=1,
        characters=[
            character_fact(chunk_id=0, name="顾霜", action="结盟"),
            character_fact(chunk_id=0, name="贺重明", action="结盟"),
        ],
        relations=[
            relation_fact(
                chunk_id=0,
                from_name="顾霜",
                to_name="贺重明",
                relation_type="盟友",
            )
        ],
    )
    linked_id = stable_annotation_fact_id(annotation_id, "relations/0")
    continuity_id = str(uuid.uuid4())
    db_session.add(
        ContinuityFact(
            fact_id=continuity_id,
            run_id=run_id,
            created_by_annotation_id=annotation_id,
            fact_type="relation",
            subject={"name": "顾霜", "entity_type": "character"},
            predicate="盟友",
            object={"name": "贺重明", "entity_type": "character"},
            value=None,
            participants=[],
            scope="novel",
            story_time=None,
            assertion="affirmed",
            change_kind="refine",
            linked_fact_id=linked_id,
            confidence="high",
            evidence=evidence("后续确认结盟"),
            dedupe_key=uuid.uuid4().hex,
        )
    )
    db_session.flush()
    project_graph_tables(run_id, session=db_session, annotation_id=annotation_id)
    db_session.commit()
    before = _graph_snapshot(db_session, run_id)

    project_graph_tables(run_id, session=db_session, rebuild=True)
    db_session.commit()
    after = _graph_snapshot(db_session, run_id)

    assert after == before
    sources = list(
        db_session.execute(
            select(GraphFactSource).where(GraphFactSource.run_id == run_id)
        )
        .scalars()
        .all()
    )
    assert {row.stable_fact_id for row in sources} == {
        stable_annotation_fact_id(annotation_id, "segments/0"),
        stable_annotation_fact_id(annotation_id, "characters/0"),
        stable_annotation_fact_id(annotation_id, "characters/1"),
        linked_id,
        continuity_id,
    }


def test_graph_projection_rebuilds_retained_relation_views(db_session) -> None:
    """2026-08-05 用于验证关系事件当前快照和参与者投影不会在重建后变空"""
    _novel_id, run_id = create_run_with_chunks(
        db_session,
        texts=["林渡与顾霜并肩迎敌"],
        title="关系投影重建",
    )
    persist_chapter_annotation(
        db_session,
        run_id=run_id,
        chapter_id=1,
        characters=[
            character_fact(chunk_id=0, name="林渡", action="迎敌"),
            character_fact(chunk_id=0, name="顾霜", action="迎敌"),
        ],
        relations=[
            relation_fact(
                chunk_id=0,
                from_name="林渡",
                to_name="顾霜",
                relation_type="盟友",
            )
        ],
    )

    project_graph_tables(run_id, session=db_session, rebuild=True)
    db_session.commit()

    assert len(
        db_session.execute(
            select(GraphRelationEvent).where(GraphRelationEvent.run_id == run_id)
        )
        .scalars()
        .all()
    ) == 1
    assert len(
        db_session.execute(
            select(GraphRelationCurrent).where(GraphRelationCurrent.run_id == run_id)
        )
        .scalars()
        .all()
    ) == 1
    participants = list(
        db_session.execute(
            select(GraphEntityParticipant).where(GraphEntityParticipant.run_id == run_id)
        )
        .scalars()
        .all()
    )
    assert len(participants) == 2
    assert {row.relation_event_count for row in participants} == {1}


def test_project_graph_tables_only_flushes_caller_transaction(db_session) -> None:
    """2026-08-05 用于验证图投影不会自行提交调用方事务"""
    _novel_id, run_id = create_run_with_chunks(
        db_session,
        texts=["顾霜进入山门"],
        title="图投影事务边界",
    )
    annotation = ChapterAnnotationRecord(
        annotation_id=str(uuid.uuid4()),
        run_id=run_id,
        chapter_id=1,
        payload={
            "chapter_summary": "顾霜进入山门",
            "segments": [
                {
                    "chunk_id": 0,
                    "summary": "顾霜进入山门",
                    "emotional_valence": "neutral",
                    "event_type": "铺垫",
                    "pivot_moment": False,
                    "cliffhanger": False,
                }
            ],
            "characters": [],
            "locations": [],
            "dialogues": [],
            "events": [],
            "relations": [],
            "states": [],
        },
        initial_finish_payload={},
        after_chapter_ids=[],
        revision_payload={},
    )
    db_session.add(annotation)
    db_session.flush()

    project_graph_tables(run_id, session=db_session, annotation_id=annotation.annotation_id)
    assert db_session.in_transaction()
    db_session.rollback()

    assert db_session.execute(
        select(GraphFact).where(GraphFact.run_id == run_id)
    ).scalars().all() == []
