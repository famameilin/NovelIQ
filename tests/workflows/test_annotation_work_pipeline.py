"""真实 PostgreSQL + 程序面模型桩验证角色独立保存与恢复"""

from __future__ import annotations

from unittest.mock import patch

import pytest
from langchain_core.messages import AIMessage
from sqlalchemy import func, select

from src.config import settings
from src.storage.models import AnalysisOutput, AnnotationWork, ModelTurn
from src.storage.repositories.annotation import AnnotationRepository
from src.workflows.annotate import run_annotate
from tests.support.chapter_annotation_helpers import create_run_with_chunks
from tests.support.model_stream_adapter import StreamedFakeModelMixin


class ProgramModel(StreamedFakeModelMixin):
    model_name = "test_model"

    def __init__(self, code: str) -> None:
        self.code = code
        self.calls = 0

    def bind_tools(self, tools):
        return self

    async def ainvoke(self, messages):
        self.calls += 1
        return AIMessage(
            content="", tool_calls=[{"name": "execute_code", "args": {"code": self.code}, "id": f"call{self.calls}"}]
        )


@pytest.mark.asyncio
async def test_solo_runs_real_program_and_saves_one_work(db_session) -> None:
    novel_id, run_id = create_run_with_chunks(db_session, texts=["张三出门。"], chapter_ids=[1])
    model = ProgramModel(
        'entity(id="a1", name="张三", entity_type="character", evidence=1)\n'
        'event(el="t1", isroot=True, description="张三出门", evidence=1)\n'
        'metric(summary="出门", emotional_valence=0, narrative_function="铺垫")\nfinish()'
    )
    events = []

    async def emit(event):
        events.append(event)

    with patch("src.model_pool.llm.build_chat_model", return_value=model):
        assert await run_annotate(run_id, db_session, novel_id=novel_id, emitter=emit) == (1, 0, 1)
        assert await run_annotate(run_id, db_session, novel_id=novel_id) == (1, 0, 1)
    assert model.calls == 1
    db_session.expire_all()
    assert AnnotationRepository(db_session).is_annotate_complete(run_id)
    records = db_session.execute(select(AnnotationWork).where(AnnotationWork.run_id == run_id)).scalars().all()
    assert [(item.role, item.state) for item in records] == [("solo", "saved")]
    displayed = [event for event in events if event.action == "work_saved"]
    assert len(displayed) == 1
    assert displayed[0].work_id == records[0].work_id
    assert displayed[0].invocation_id == records[0].invocation_id
    outputs = (
        db_session.execute(select(AnalysisOutput).where(
            AnalysisOutput.run_id == run_id, AnalysisOutput.kind == "chapter_annotation"
        ))
        .scalars()
        .all()
    )
    assert len(outputs) == 1
    assert outputs[0].payload["metrics"]["summary"] == "出门"


@pytest.mark.asyncio
async def test_current_work_validates_serialized_participant_fields_before_save(db_session) -> None:
    """生产调用经 JSON 变成字典后，参与者仍按当前类型校验并写入真实章产出"""
    novel_id, run_id = create_run_with_chunks(db_session, texts=["张三出门。"])
    model = ProgramModel(
        'entity(id="a1", name="张三", entity_type="character", evidence=1)\n'
        'event(el="t1", isroot=True, description="张三出门", evidence=1)\n'
        'participants(el="t1", items=[{"entity_id": "a1", "role": "主体", "action": "出门", "emotion": 1}])\n'
        'metric(summary="出门", emotional_valence=0, narrative_function="铺垫")\nfinish()'
    )
    with patch("src.model_pool.llm.build_chat_model", return_value=model):
        assert await run_annotate(run_id, db_session, novel_id=novel_id) == (1, 0, 1)
    db_session.expire_all()
    output = db_session.execute(
        select(AnalysisOutput).where(
            AnalysisOutput.run_id == run_id, AnalysisOutput.kind == "chapter_annotation"
        )
    ).scalar_one().payload
    assert output["events"][0]["participants"][0]["entity"] == "张三"
    assert output["character_observations"][0]["emotion"] == 1


@pytest.mark.asyncio
async def test_long_chapter_saves_three_work_without_chapter_finalize(db_session, monkeypatch) -> None:
    monkeypatch.setattr(settings.models.annotation, "sub_chunk_max_chars", 2)
    novel_id, run_id = create_run_with_chunks(db_session, texts=["章中原文。"], chapter_ids=[1])
    model = ProgramModel('metric(summary="原文", emotional_valence=0, narrative_function="铺垫")\nfinish()')
    with patch("src.model_pool.llm.build_chat_model", return_value=model):
        assert await run_annotate(run_id, db_session, novel_id=novel_id) == (1, 0, 1)
    db_session.expire_all()
    work = db_session.execute(select(AnnotationWork).where(AnnotationWork.run_id == run_id)).scalars().all()
    assert {item.role for item in work} == {"structure", "event", "evidence"}
    outputs = (
        db_session.execute(select(AnalysisOutput).where(
            AnalysisOutput.run_id == run_id, AnalysisOutput.kind == "chapter_annotation"
        ))
        .scalars()
        .all()
    )
    assert len(outputs) == 3
    assert AnnotationRepository(db_session).is_annotate_complete(run_id)


class RoleModel(ProgramModel):
    async def ainvoke(self, messages):
        text = str(messages[1].content)
        if 'role="structure"' in text:
            self.code = 'entity(id="a1", name="张三", entity_type="character", evidence=1)\nfinish()'
        elif 'role="event"' in text:
            self.code = 'event(el="t1", isroot=True, description="独立事件", evidence=1)\nfinish()'
        else:
            self.code = 'metric(summary="原文", emotional_valence=0, narrative_function="铺垫")\nfinish()'
        return await super().ainvoke(messages)


@pytest.mark.asyncio
async def test_later_chapter_saves_while_earlier_model_is_running(db_session, configured_model_pool):
    import asyncio

    from src.model_pool.capacity import MODEL_CAPACITY
    from src.storage.db import get_session_factory

    novel_id, run_id = create_run_with_chunks(db_session, texts=["早章。", "后章。"], chapter_ids=[1, 2])
    later_saved = asyncio.Event()

    class OrderedModel(ProgramModel):
        async def ainvoke(self, messages):
            if "早章" in str(messages[1].content):
                await asyncio.wait_for(later_saved.wait(), 3)
            return await super().ainvoke(messages)

    model = OrderedModel('metric(summary="实际输出", emotional_valence=0, narrative_function="铺垫")\nfinish()')
    order = []

    async def emit(event):
        if event.action == "progress":
            order.append(event.chapter_id)
            if event.chapter_id == 2:
                with get_session_factory()() as session:
                    saved = (
                        session.execute(select(AnnotationWork.chapter_id).where(AnnotationWork.run_id == run_id))
                        .scalars()
                        .all()
                    )
                    assert saved == [2]
                    assert any(MODEL_CAPACITY.snapshot().values())
                later_saved.set()

    with patch("src.model_pool.llm.build_chat_model", return_value=model):
        assert await run_annotate(run_id, db_session, novel_id=novel_id, emitter=emit) == (2, 0, 2)
    assert order == [2, 1]
    assert not any(MODEL_CAPACITY.snapshot().values())


@pytest.mark.asyncio
async def test_recovery_discards_partial_roles_and_keeps_completed_chapter(db_session, monkeypatch):
    from sqlalchemy import delete

    from src.storage.models import EventNode

    monkeypatch.setattr(settings.models.annotation, "sub_chunk_max_chars", 2)
    novel_id, run_id = create_run_with_chunks(db_session, texts=["短", "长章原文。"], chapter_ids=[1, 2])
    model = RoleModel("")
    with patch("src.model_pool.llm.build_chat_model", return_value=model):
        await run_annotate(run_id, db_session, novel_id=novel_id)
    db_session.expire_all()
    saved = db_session.execute(select(AnnotationWork).where(AnnotationWork.run_id == run_id)).scalars().all()
    complete = next(value for value in saved if value.chapter_id == 1)
    retained_invocation = complete.invocation_id
    partial_event = next(value for value in saved if value.role == "event")
    old_event_invocation = partial_event.invocation_id
    node = db_session.execute(select(EventNode).where(EventNode.author_work_id == partial_event.work_id)).scalar_one()
    identifier = node.event_id
    lost = next(value for value in saved if value.role == "evidence")
    db_session.execute(
        delete(AnalysisOutput).where(
            AnalysisOutput.work_id == lost.work_id, AnalysisOutput.kind == "chapter_annotation"
        )
    )
    db_session.execute(delete(AnnotationWork).where(AnnotationWork.work_id == lost.work_id))
    db_session.commit()
    calls = model.calls
    with patch("src.model_pool.llm.build_chat_model", return_value=model):
        await run_annotate(run_id, db_session, novel_id=novel_id)
    db_session.expire_all()
    assert model.calls - calls == 3
    assert db_session.get(AnnotationWork, complete.work_id).invocation_id == retained_invocation
    current = db_session.get(EventNode, identifier)
    assert current.producer_invocation_id != old_event_invocation
    assert (
        db_session.execute(
            select(func.count(func.distinct(ModelTurn.execution_id))).where(
                ModelTurn.run_id == run_id, ModelTurn.row_kind.in_(("agent_turn", "attempt_error"))
            )
        ).scalar_one()
        == 7
    )
    records = (
        db_session.execute(select(AnalysisOutput).where(
            AnalysisOutput.run_id == run_id, AnalysisOutput.kind == "chapter_annotation"
        ))
        .scalars()
        .all()
    )
    assert all(value.payload["metrics"] is None for value in records if value.role in {"structure", "event"})


@pytest.mark.asyncio
async def test_save_failure_rolls_back_all_business_and_releases_case(db_session, monkeypatch):
    from src.agents.annotation.agent import AnnotationAgent
    from src.case_pool import CasePool
    from src.model_pool.capacity import MODEL_CAPACITY
    from src.storage.models import BookCase, EventNode, GraphFact

    novel_id, run_id = create_run_with_chunks(db_session, texts=["原文。"])
    model = ProgramModel(
        'pending(description="待核查")\n'
        'event(el="t1", isroot=True, description="原文事件", evidence=1)\n'
        'metric(summary="原文", emotional_valence=0, narrative_function="铺垫")\nfinish()'
    )
    aborted = []
    original_abort = AnnotationAgent.abort

    async def abort(agent, message):
        await original_abort(agent, message)
        assert not agent.event_trees.nodes and not agent.case_pool.cases
        aborted.append(message.work_id)

    def fail_save(*args):
        raise RuntimeError("案例保存故障")

    monkeypatch.setattr(AnnotationAgent, "abort", abort)
    monkeypatch.setattr(CasePool, "save_work", fail_save)
    with patch("src.model_pool.llm.build_chat_model", return_value=model):
        with pytest.raises(RuntimeError, match="案例保存故障"):
            await run_annotate(run_id, db_session, novel_id=novel_id)
    db_session.expire_all()
    for cls in (AnnotationWork, AnalysisOutput, EventNode, GraphFact, BookCase):
        assert db_session.query(cls).filter(cls.run_id == run_id).count() == 0
    assert aborted and not any(MODEL_CAPACITY.snapshot().values())
    assert (
        db_session.execute(
            select(func.count(func.distinct(ModelTurn.execution_id))).where(
                ModelTurn.run_id == run_id, ModelTurn.row_kind.in_(("agent_turn", "attempt_error"))
            )
        ).scalar_one()
        == 1
    )


@pytest.mark.asyncio
async def test_lost_commit_reply_verifies_actual_save_before_confirm(db_session, monkeypatch):
    from src.model_pool.capacity import MODEL_CAPACITY
    from src.storage.db import get_session_factory

    novel_id, run_id = create_run_with_chunks(db_session, texts=["原文。"])
    original_factory = get_session_factory()
    replies = []

    def factory():
        session = original_factory()
        original_commit = session.commit

        def commit():
            owns_work = any(isinstance(row, AnnotationWork) for row in session.identity_map.values())
            # 队列 flush 后行可能不再由 identity_map 强引用，实际新 work 用查询确认
            owns_work = owns_work or bool(session.query(AnnotationWork).filter(AnnotationWork.run_id == run_id).count())
            original_commit()
            if owns_work and not replies:
                assert any(MODEL_CAPACITY.snapshot().values())
                replies.append("lost")
                raise OSError("提交回执丢失")

        session.commit = commit
        return session

    monkeypatch.setattr("src.workflows.annotate.get_session_factory", lambda: factory)
    model = ProgramModel('metric(summary="原文", emotional_valence=0, narrative_function="铺垫")\nfinish()')
    with patch("src.model_pool.llm.build_chat_model", return_value=model):
        assert await run_annotate(run_id, db_session, novel_id=novel_id) == (1, 0, 1)
    assert replies == ["lost"] and model.calls == 1
    assert not any(MODEL_CAPACITY.snapshot().values())


@pytest.mark.asyncio
async def test_no_eligible_model_ends_without_starting_or_saving_work(db_session, monkeypatch):
    from src.agents.annotation.agent import AnnotationAgent
    from src.model_pool.capacity import ModelElectionExhausted

    novel_id, run_id = create_run_with_chunks(db_session, texts=["原文。"])
    started = []

    async def unexpected(*args):
        started.append(True)
        raise AssertionError("不应启动 work")

    monkeypatch.setattr(AnnotationAgent, "execute", unexpected)
    monkeypatch.setattr("src.config.model_assignment.select_annotation_model", lambda *args, **kwargs: None)
    with pytest.raises(ModelElectionExhausted):
        await run_annotate(run_id, db_session, novel_id=novel_id)
    assert not started
    assert db_session.query(AnnotationWork).filter(AnnotationWork.run_id == run_id).count() == 0


@pytest.mark.asyncio
async def test_program_can_read_shared_nodes_claim_case_and_save_cross_chapter_link(db_session, configured_model_pool):
    from src.storage.models import BookCase, EventEdge
    from src.storage.repositories.book_state import book_state_view

    settings.models.model_pool[0].max_in_flight = 1
    novel_id, run_id = create_run_with_chunks(
        db_session, texts=["张三拾得旧信。", "张三读懂旧信。"], chapter_ids=[1, 2]
    )

    class SharedModel(ProgramModel):
        async def ainvoke(self, messages):
            if "拾得" in str(messages[1].content):
                self.code = (
                    'pending(description="旧信的用途")\n'
                    'event(el="t1", isroot=True, description="拾得旧信", evidence=1, '
                    'isforeshadowing=True, confidence="high")\n'
                    'metric(summary="拾信", emotional_valence=0, narrative_function="铺垫")\nfinish()'
                )
            else:
                self.code = (
                    'cases = search_cases()\npromise_case(case_id=cases[0]["case_id"])\n'
                    'nodes = search_events(query="拾得")\n'
                    'read_text(paragraph_id=nodes[0]["content"]["evidence_paragraph_id"])\n'
                    'event(el="t1", isroot=True, description="读懂旧信", evidence=1, '
                    'type="main", parent_ref=nodes[0]["node_id"])\n'
                    'metric(summary="读信", emotional_valence=0, narrative_function="铺垫")\n'
                    'finish(case_delivery={"case_id":cases[0]["case_id"],"state":"resolved","reason":"原文支持旧信导致读信"})'
                )
            return await super().ainvoke(messages)

    with patch("src.model_pool.llm.build_chat_model", return_value=SharedModel("")):
        assert await run_annotate(run_id, db_session, novel_id=novel_id) == (2, 0, 2)
    db_session.expire_all()
    snapshot = book_state_view(db_session, run_id)
    assert snapshot["case_states"]["resolved"] == 1 and len(snapshot["connections"]) == 1
    assert snapshot["connections"][0]["type"] == "main"
    state = db_session.get(BookCase, snapshot["cases"][0]["case_id"])
    assert len(state.contributions) == 2
    assert db_session.query(EventEdge).filter(EventEdge.run_id == run_id).count() == 1


@pytest.mark.asyncio
async def test_late_write_after_finish_is_refused_and_audited_without_reopening(db_session):
    from src.storage.models import AgentToolCall, BookCase, ModelTurn

    novel_id, run_id = create_run_with_chunks(db_session, texts=["原文。"])
    model = ProgramModel(
        'metric(summary="原文", emotional_valence=0, narrative_function="铺垫")\nfinish()\npending(description="迟到")'
    )
    with patch("src.model_pool.llm.build_chat_model", return_value=model):
        assert await run_annotate(run_id, db_session, novel_id=novel_id) == (1, 0, 1)
    assert model.calls == 1
    assert db_session.query(BookCase).filter(BookCase.run_id == run_id).count() == 0
    execution = (
        db_session.execute(
            select(ModelTurn.execution_id).where(ModelTurn.run_id == run_id, ModelTurn.row_kind == "agent_turn")
        )
        .scalars()
        .one()
    )
    rejected = (
        db_session.query(AgentToolCall)
        .join(ModelTurn, AgentToolCall.turn_id == ModelTurn.id)
        .filter(ModelTurn.execution_id == execution, AgentToolCall.tool_name == "pending")
        .one()
    )
    assert rejected.status == "error"
