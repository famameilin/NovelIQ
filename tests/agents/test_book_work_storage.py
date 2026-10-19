"""共享案例的保存顺序及独立审计回执验证"""


import pytest
from sqlalchemy import select

from src.audit.module import AuditModule
from src.event_bus import EventBus, Message
from src.fact_graph.read.annotations import fetch_chapter_characters_full
from src.storage import new_id
from src.storage.db import get_session_factory
from tests.support.chapter_annotation_helpers import create_run_with_chunks
from tests.support.storage_fixtures import fixture_id, storage_factory, storage_for


@pytest.mark.parametrize("reference_kind", ["relation", "event", "dialogue"])
def test_retained_reference_restores_entity_after_source_chapter_discard(db_session, reference_kind):
    """引用自身已保存且有效，丢弃源章不补造实体写入，也不丢引用端点"""
    from types import SimpleNamespace

    from src.agents.annotation.output_models import BoundChapterAnnotation
    from src.fact_graph.graph import FactGraph
    from src.fact_graph.inputs import ChapterMetricsInput
    from src.fact_graph.outputs import BoundDialogue
    from src.storage.models import (
        ChapterAnnotation,
        GraphEntity,
        GraphFact,
        Paragraph,
    )
    from src.storage.repositories.annotation import AnnotationRepository
    from tests.support.chapter_annotation_helpers import (
        commit_test_annotation,
        make_bound_event,
        persist_chapter_annotation,
        relation_fact,
    )

    text = 'Alice says: "Go."'
    _, run_id = create_run_with_chunks(db_session, texts=["Alice knows Bob.", text], chapter_ids=[1, 2])
    persist_chapter_annotation(
        db_session,
        run_id=run_id,
        chapter_id=1,
        relations=[relation_fact(chapter_id=1, from_name="Alice", to_name="Bob", relation_type="敌对")],
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
                node_id=new_id(),
                tree_id=new_id(),
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
    # 作者身份就是真实执行号（executions 行携带 run/章/角色）
    graph = FactGraph(run_scope=run_id)
    storage_for(db_session).annotations.discard_chapters(run_id, {1})
    db_session.expire_all()
    kept = db_session.get(ChapterAnnotation, kept_id)
    kept_record = SimpleNamespace(
        agent_id=kept.agent_id,
        record_id=kept.record_id,
        chapter_id=2,
        sequence=2,
        role="annotation",
    )
    graph.restore_storage(storage_for(db_session), [kept_record])
    graph.restore_storage(storage_for(db_session), [kept_record])
    alice = db_session.scalar(
        select(GraphEntity.entity_id).where(GraphEntity.run_id == run_id, GraphEntity.canonical_name == "Alice")
    )
    resolved = graph.resolve_entity_id(alice, label="source")
    assert graph.display_name(resolved) == "Alice"
    # 引用恢复不补造实体写入（只有引用支持，没有实体操作）
    assert graph.drain_ops(next(iter(graph.saved)))["entity_ops"] == []
    assert db_session.get(GraphEntity, alice) is not None
    assert not list(
        db_session.scalars(
            select(GraphFact).where(GraphFact.entity_id == alice, GraphFact.tags_submitted.is_not(False))
        )
    )
    assert list(
        db_session.scalars(select(GraphFact).where(GraphFact.entity_id == alice, GraphFact.tags_submitted.is_(False)))
    )
    assert fetch_chapter_characters_full(storage_for(AnnotationRepository(db_session).session), run_id) == []




@pytest.mark.asyncio
async def test_actual_usage_duplicate_is_durable_and_does_not_double_charge(db_session):
    novel_id, run_id = create_run_with_chunks(db_session, texts=["实际文本。"])
    bus = EventBus()
    message = Message(
        topic=f"audit:{run_id}",
        source="preprocess",
        target=f"audit:{run_id}",
        run_id=run_id,
        invocation_id=fixture_id(__name__, "usage-inv"),
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
    audit = AuditModule(bus, run_id, storage_factory(get_session_factory()))
    bus.publish(message)
    bus.publish(message)
    await audit.close()
    audit = AuditModule(bus, run_id, storage_factory(get_session_factory()))
    bus.publish(message)
    await audit.close()
    db_session.expire_all()
    from src.storage.models import AgentLoop

    # 独立调用与用量同列于 model_calls（用量与实报总量是同一行的事实）
    calls = list(db_session.scalars(select(AgentLoop).where(AgentLoop.standalone_run_id == run_id)))
    assert len(calls) == 1
    assert calls[0].prompt_tokens == 10
    assert calls[0].reported_total_tokens == 10
