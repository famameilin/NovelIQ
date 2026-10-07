"""共享案例的保存顺序及独立审计回执验证"""

from copy import deepcopy

import pytest
from sqlalchemy import select

from src.audit.module import AuditModule
from src.case_pool import CasePool
from src.event_bus import EventBus, Message
from src.fact_graph.read.annotations import fetch_chapter_characters_full
from src.storage.db import get_session_factory
from src.storage.models import BookCase, ModelTurn
from tests.support.chapter_annotation_helpers import create_run_with_chunks


@pytest.mark.parametrize("reference_kind", ["relation", "event", "dialogue"])
def test_retained_reference_restores_entity_after_source_chapter_discard(db_session, reference_kind):
    """引用自身已保存且有效，丢弃源章不补造实体写入，也不丢引用端点"""
    from uuid import uuid4

    from src.agents.annotation.output_models import BoundChapterAnnotation
    from src.fact_graph.graph import FactGraph, mention_uuid
    from src.fact_graph.inputs import ChapterMetricsInput
    from src.fact_graph.outputs import BoundDialogue
    from src.storage.models import AnalysisOutput, AnnotationWork, GraphEntity, GraphFact, Paragraph
    from src.storage.repositories.annotation import AnnotationRepository
    from tests.support.chapter_annotation_helpers import (
        commit_test_annotation,
        make_bound_event,
        persist_chapter_annotation,
        relation_fact,
    )

    text = 'Alice says: "Go."'
    _, run_id = create_run_with_chunks(db_session, texts=["Alice knows Bob.", text], chapter_ids=[1, 2])
    source_id = persist_chapter_annotation(
        db_session,
        run_id=run_id,
        chapter_id=1,
        relations=[relation_fact(chapter_id=1, from_name="Alice", to_name="Bob", relation_type="敌对")],
        entity_attributes={(1, "Alice"): {"discarded_attribute": True}},
    )
    output = BoundChapterAnnotation(
        metrics=ChapterMetricsInput(summary="Actual input", emotional_valence=0, narrative_function="铺垫"),
        events=[],
        dialogues=[],
        character_observations=[],
    )
    relations = []
    if reference_kind == "relation":
        relations = [{"from_entity": "Alice", "to_entity": "Bob", "relation_type": "敌对", "chapter_id": 2}]
    elif reference_kind == "event":
        output.events = [
            make_bound_event(
                description="Alice speaks",
                participants=[{"entity": "Alice", "role": "主体"}],
                node_id=str(uuid4()),
                tree_id=str(uuid4()),
            )
        ]
        paragraph = db_session.query(Paragraph).filter_by(run_id=run_id, chapter_id=2).one()
        output.events[0].evidence_paragraph_id = paragraph.paragraph_id
    else:
        output.dialogues = [
            BoundDialogue(
                candidate_index=1,
                candidate_key="actual-go",
                content="Go.",
                start=text.index("Go."),
                end=text.index("Go.") + 3,
                speaker="Alice",
            )
        ]
    kept_id = commit_test_annotation(
        db_session,
        run_id=run_id,
        chapter_id=2,
        annotation=output,
        relation_assert_ops=relations,
    )
    source = db_session.get(AnalysisOutput, source_id)
    source_work = source.work_id
    graph = FactGraph(run_scope=run_id)
    graph.discard_storage(db_session, {source_work})
    db_session.delete(source)
    db_session.delete(db_session.get(AnnotationWork, source_work))
    db_session.flush()
    graph.rebuild_storage(db_session)
    graph.restore_storage(db_session, [db_session.get(AnalysisOutput, kept_id)])
    graph.restore_storage(db_session, [db_session.get(AnalysisOutput, kept_id)])
    assert graph.resolve_entity_id(mention_uuid(run_id, 2, "Alice"), label="source") == "Alice"
    assert graph.drain_ops(*next(iter(graph.saved)))["entity_ops"] == []
    assert db_session.get(GraphEntity, mention_uuid(run_id, 2, "Alice")).attributes == {}
    assert db_session.query(GraphFact).filter_by(run_id=run_id, fact_type="entity").count() == 0
    assert db_session.query(GraphFact).filter_by(run_id=run_id, fact_type="entity_reference").count() >= 1
    assert fetch_chapter_characters_full(AnnotationRepository(db_session).session, run_id) == []


def test_case_delivery_order_does_not_follow_database_save_order(db_session):
    _novel, run_id = create_run_with_chunks(db_session, texts=["原文。"])
    pool = CasePool(run_id)
    a, b = ("a", "a1"), ("b", "b1")
    pool.begin(*a)
    pool.begin(*b)
    case = pool.push("核查实际关联", a)
    pool.promise(case["case_id"], a)
    pool.deliver(
        {"case_id": case["case_id"], "state": "deferred", "reason": "等待更多原文"},
        a,
        call_id="first",
        connections=[],
        reads=[],
    )
    pool.promise(case["case_id"], b)
    pool.deliver(
        {"case_id": case["case_id"], "state": "resolved", "reason": "已核查，无需连接"},
        b,
        call_id="second",
        connections=[],
        reads=[{"paragraph_id": 0, "content": "原文。"}],
    )

    def execution(author):
        import json

        from src.case_pool.contributions import CaseContribution

        snapshot = {
            "registrations": {key: deepcopy(pool.cases[key]) for key in pool.registrations[author]},
            "deliveries": deepcopy(pool.deliveries[author]),
        }
        return CaseContribution(run_id, author[0], author[1], json.dumps(snapshot, ensure_ascii=False))

    pool.save_work(db_session, execution(b))
    db_session.commit()
    pool.save_work(db_session, execution(a))
    db_session.commit()
    assert db_session.get(BookCase, case["case_id"]).state == "resolved"
    restored = CasePool(run_id)
    restored.restore_storage(db_session, {"b"})
    assert restored.search()[0]["state"] == "deferred"


@pytest.mark.asyncio
async def test_actual_usage_duplicate_is_durable_and_does_not_double_charge(db_session):
    novel_id, run_id = create_run_with_chunks(db_session, texts=["实际文本。"])
    bus = EventBus()
    message = Message(
        topic=f"audit:{run_id}",
        source="preprocess",
        target=f"audit:{run_id}",
        run_id=run_id,
        invocation_id="usage-inv",
        message_id=f"{run_id}:usage:1",
        payload={
            "method": "nonagent_usage",
            "local_id": 1,
            "kwargs": {
                "run_id": run_id,
                "task_type": "embedding",
                "call_type": "embedding",
                "model": "test",
                "prompt_tokens": 10,
                "total_tokens": 10,
            },
        },
    )
    audit = AuditModule(bus, run_id, get_session_factory())
    bus.publish(message)
    bus.publish(message)
    await audit.close()
    audit = AuditModule(bus, run_id, get_session_factory())
    bus.publish(message)
    await audit.close()
    db_session.expire_all()
    usage = (
        db_session.execute(select(ModelTurn).where(ModelTurn.run_id == run_id, ModelTurn.row_kind == "usage"))
        .scalars()
        .all()
    )
    assert len(usage) == 1 and usage[0].total_tokens == 10
