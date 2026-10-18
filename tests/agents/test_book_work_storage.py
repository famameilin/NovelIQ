"""共享案例的保存顺序及独立审计回执验证"""

from copy import deepcopy

import pytest
from sqlalchemy import select

from src.audit.module import AuditModule
from src.case_pool import CasePool
from src.event_bus import EventBus, Message
from src.fact_graph.read.annotations import fetch_chapter_characters_full
from src.storage.db import get_session_factory
from src.storage.models import BookCase
from tests.support.chapter_annotation_helpers import create_run_with_chunks


@pytest.mark.parametrize("reference_kind", ["relation", "event", "dialogue"])
def test_retained_reference_restores_entity_after_source_chapter_discard(db_session, reference_kind):
    """引用自身已保存且有效，丢弃源章不补造实体写入，也不丢引用端点"""
    from types import SimpleNamespace
    from uuid import uuid4

    from src.agents.annotation.output_models import BoundChapterAnnotation
    from src.fact_graph.graph import FactGraph, mention_uuid
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
    source_id = persist_chapter_annotation(
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
    # 作者身份就是真实执行号（executions 行携带 run/章/角色）
    source = db_session.get(ChapterAnnotation, source_id)
    source_author = str(source.execution_id)
    graph = FactGraph(run_scope=run_id)
    graph.discard_storage(db_session, {source_author})
    db_session.delete(source)
    db_session.flush()
    graph.rebuild_storage(db_session)
    kept = db_session.get(ChapterAnnotation, kept_id)
    kept_record = SimpleNamespace(
        execution_id=kept.execution_id,
        record_id=kept.record_id,
        chapter_id=2,
        sequence=2,
        role="annotation",
    )
    graph.restore_storage(db_session, [kept_record])
    graph.restore_storage(db_session, [kept_record])
    alice = mention_uuid(run_id, 2, "Alice", "character")
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
        db_session.scalars(
            select(GraphFact).where(GraphFact.entity_id == alice, GraphFact.tags_submitted.is_(False))
        )
    )
    assert fetch_chapter_characters_full(AnnotationRepository(db_session).session, run_id) == []


def test_case_delivery_rows_decide_adoption_and_promise_reconstructs(db_session):
    """采纳由真实交付行决定（写交付=adopted）；承诺随痕迹重建，废弃作者不被恢复"""
    from uuid import uuid4

    _novel, run_id = create_run_with_chunks(db_session, texts=["原文一。", "原文二。"], chapter_ids=[1, 2])
    from src.storage.models import CaseEntry, Execution
    from src.storage.models.base import naive_utcnow

    # 作者身份是真实执行号（单一字符串）；案例支持必须引用真实执行：
    # (run, chapter, role) 唯一，因此两个作者落在两章
    suffix = uuid4().hex[:8]
    a, b = f"a1-{suffix}", f"b1-{suffix}"
    for author, chapter_id in ((a, 1), (b, 2)):
        db_session.add(
            Execution(
                execution_id=author,
                run_id=run_id,
                chapter_id=chapter_id,
                role="annotation",
                attempt_number=1,
                started_at=naive_utcnow(),
                status="success",
            )
        )
    db_session.flush()
    pool = CasePool(run_id)
    pool.begin(a)
    pool.begin(b)
    case = pool.push("dialogue", "核查实际关联", a)
    pool.promise(case["case_id"], a)
    pool.associate(case["case_id"], a, tool_name="read_event", call_id="first", receipt={}, is_write=False)
    # 同一案例只有承诺者能投递：他执行接手只会得到 taken，投递直接拒收
    assert pool.promise(case["case_id"], b)["status"] == "taken"
    assert (
        pool.associate(case["case_id"], b, tool_name="write_event", call_id="second", receipt={}, is_write=True)[
            "status"
        ]
        == "warning"
    )
    pool.associate(case["case_id"], a, tool_name="write_event", call_id="second", receipt={}, is_write=True)
    # 案例本身先落行；交付行决定采纳，不依赖保存顺序
    db_session.add(
        BookCase(
            case_id=case["case_id"],
            registration_run_id=run_id,
            case_type="dialogue",
            description="核查实际关联",
        )
    )
    db_session.flush()

    def execution(author):
        import json

        from src.case_pool.contributions import CaseContribution

        snapshot = {
            "created_case_ids": sorted(pool.created.get(author, set())),
            "registrations": {key: deepcopy(pool.cases[key]) for key in pool.registrations[author]},
            "deliveries": deepcopy(pool.deliveries[author]),
        }
        return CaseContribution(run_id, author, json.dumps(snapshot, ensure_ascii=False))

    pool.save_work(db_session, execution(a))
    db_session.commit()
    supports = {
        str(entry.producer_execution_id): entry
        for entry in db_session.scalars(
            select(CaseEntry).where(
                CaseEntry.case_id == case["case_id"], CaseEntry.producer_execution_id.is_not(None)
            )
        )
    }
    assert supports[a].adopted is True and b not in supports
    loaded = CasePool(run_id)
    loaded.load_storage(db_session)
    assert loaded.case_runtime[case["case_id"]]["promised"] is True
    calls = [item["call_id"] for item in loaded.deliveries[a] if item["tool_name"] != "promise_case"]
    assert sorted(calls) == ["first", "second"]
    restored = CasePool(run_id)
    restored.restore_storage(db_session, {a})
    # 无支持的案例随废弃执行整体退场
    assert restored.search() == []


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
    from src.storage.models import ModelCall

    # 独立调用与用量同列于 model_calls（用量与实报总量是同一行的事实）
    calls = list(
        db_session.scalars(select(ModelCall).where(ModelCall.standalone_run_id == run_id))
    )
    assert len(calls) == 1
    assert calls[0].prompt_tokens == 10
    assert calls[0].reported_total_tokens == 10
