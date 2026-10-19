"""真实 PostgreSQL + 程序面模型桩验证角色独立保存与恢复"""

from __future__ import annotations

from unittest.mock import patch

import pytest
from langchain_core.messages import AIMessage
from sqlalchemy import delete, func, select

from src.audit.queries import fetch_agent_turns, fetch_run_tool_calls
from src.config import settings
from src.fact_graph.graph import entity_key
from src.storage.models import (
    Agent,
    AgentLoop,
    Case,
    ChapterAnnotation,
    DialogueRecord,
    EventDeclaration,
    GraphEntity,
    GraphFact,
    GraphRelation,
)
from src.storage.repositories.queries.audit_queries import run_agent_execution_ids
from src.work.policy import completed_chapters
from src.work.queries import chapter_annotations, fetch_annotation_role_records, is_annotate_complete
from src.workflows.annotate import run_annotate
from tests.support.chapter_annotation_helpers import create_run_with_chunks
from tests.support.model_stream_adapter import StreamedFakeModelMixin
from tests.support.storage_fixtures import entity_id, storage_for


class ProgramModel(StreamedFakeModelMixin):
    model_name = "test_model"

    def __init__(self, code: str | list[str]) -> None:
        self.code = code
        self.calls = 0

    def bind_tools(self, tools):
        return self

    async def ainvoke(self, messages):
        self.calls += 1
        code = self.code if isinstance(self.code, str) else self.code[self.calls - 1]
        return AIMessage(
            content="", tool_calls=[{"name": "execute_code", "args": {"code": code}, "id": f"call{self.calls}"}]
        )


def _run_execution_ids(run_id: str):
    """本 run 真实尝试的执行选择器（执行行直接携带运行归属）"""
    return select(Agent.id).where(Agent.run_id == run_id)


def _run_products(db_session, run_id: str) -> list[ChapterAnnotation]:
    """本 run 的正式标注产物行（保存成功的唯一事实）"""
    return list(db_session.scalars(select(ChapterAnnotation).where(ChapterAnnotation.run_id == run_id)))


def _agent_execution_count(db_session, run_id: str) -> int:
    """本 run 真实尝试数（按模型调用行归属的 distinct execution）"""
    return int(
        db_session.scalar(
            select(func.count(func.distinct(AgentLoop.agent_id))).where(
                AgentLoop.agent_id.in_(run_agent_execution_ids(run_id))
            )
        )
        or 0
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("chapter_id", [1, 3])
async def test_annotation_role_runs_real_program_and_saves_one_product(db_session, chapter_id) -> None:
    novel_id, run_id = create_run_with_chunks(db_session, texts=["张三出门。"], chapter_ids=[chapter_id])
    model = ProgramModel(
        "entity(id='a1', name='张三', entity_type='chara"  # 同一程序文本
        "cter', evidence=1)\nevent(el='t1', evidence=1,"  # 同一程序文本
        " title='张三出门', problem='明确事件问题', summary='张三出"  # 同一程序文本
        "门', event_type='行动', status='ongoing')\nmetric"  # 同一程序文本
        "(summary='出门', emotional_valence=0, narrative"  # 同一程序文本
        "_function='铺垫')\nfinish()"  # 同一程序文本
    )
    events = []

    async def emit(event):
        events.append(event)

    with patch("src.model_pool.llm.build_chat_model", return_value=model):
        assert await run_annotate(run_id, storage_for(db_session), novel_id=novel_id, emitter=emit) == (1, 0, 1)
        assert await run_annotate(run_id, storage_for(db_session), novel_id=novel_id) == (1, 0, 1)
    assert model.calls == 1
    db_session.expire_all()
    assert is_annotate_complete(storage_for(db_session), run_id)
    states = fetch_annotation_role_records(storage_for(db_session), run_id)
    assert [(item.role, item.state) for item in states] == [("annotation", "saved")]
    assert not [event for event in events if event.action == "progress" and event.current is not None]
    views = chapter_annotations(storage_for(db_session), run_id)
    assert len(views) == 1
    assert views[0].payload["metrics"]["summary"] == "出门"
    assert [row.record_id for row in _run_products(db_session, run_id)] == [views[0].output_id]


@pytest.mark.asyncio
async def test_reverse_resubmission_of_bidirectional_relation_keeps_save_confirmed(db_session) -> None:
    """同一双向关系被两个 work 换向提交不重插行、两章都能保存"""
    novel_id, run_id = create_run_with_chunks(
        db_session,
        texts=["张三与李四并肩而行于长街。", "李四与张三于校场比试拳脚。"],
        chapter_ids=[1, 2],
    )
    zhang_id = entity_id(run_id, entity_key("张三", "character"))
    li_id = entity_id(run_id, entity_key("李四", "character"))
    first_code = (
        "entity(id='a1', name='张三', entity_type='character', evidence=1)\n"
        "entity(id='a2', name='李四', entity_type='character', evidence=1)\n"
        "relation(from_entity={'name': '张三', 'entity_type': 'character'},"
        " to_entity={'name': '李四', 'entity_type': 'character'}, relation_type='友情')\n"
        "event(el='t1', evidence=1, title='同行', problem='明确事件问题',"
        " summary='同行', event_type='行动', status='ongoing')\n"
        "metric(summary='同行', emotional_valence=0, narrative_function='铺垫')\n"
        "finish()"
    )
    second_code = (
        "entity(id='a1', name='张三', entity_type='character', evidence=1)\n"
        "entity(id='a2', name='李四', entity_type='character', evidence=1)\n"
        "relation(from_entity={'name': '李四', 'entity_type': 'character'},"
        " to_entity={'name': '张三', 'entity_type': 'character'}, relation_type='友情')\n"
        "event(el='t1', evidence=1, title='比试', problem='明确事件问题',"
        " summary='比试', event_type='行动', status='ongoing')\n"
        "metric(summary='比试', emotional_valence=0, narrative_function='铺垫')\n"
        "finish()"
    )

    class ChapterAwareModel(StreamedFakeModelMixin):
        model_name = "test_model"

        def bind_tools(self, tools):
            return self

        async def ainvoke(self, messages):
            # 两章并发派发，按章原文判向；先写者落库方向为准，后写者换向提交
            code = second_code if "比试" in str(messages) else first_code
            return AIMessage(content="", tool_calls=[{"name": "execute_code", "args": {"code": code}, "id": "call"}])

    model = ChapterAwareModel()
    with patch("src.model_pool.llm.build_chat_model", return_value=model):
        assert await run_annotate(run_id, storage_for(db_session), novel_id=novel_id) == (2, 0, 2)
    db_session.expire_all()
    zhang_id = db_session.scalar(
        select(GraphEntity.entity_id).where(GraphEntity.run_id == run_id, GraphEntity.canonical_name == "张三")
    )
    li_id = db_session.scalar(
        select(GraphEntity.entity_id).where(GraphEntity.run_id == run_id, GraphEntity.canonical_name == "李四")
    )
    states = fetch_annotation_role_records(storage_for(db_session), run_id)
    assert [(item.role, item.state) for item in states] == [("annotation", "saved"), ("annotation", "saved")]
    assert (
        db_session.scalar(
            select(func.count())
            .select_from(GraphRelation)
            .where(
                GraphRelation.relation_type == "友情",
                GraphRelation.from_entity_id.in_([zhang_id, li_id]),
                GraphRelation.to_entity_id.in_([zhang_id, li_id]),
            )
        )
        == 1
    )


@pytest.mark.asyncio
async def test_next_provider_turn_persists_all_domain_facts(db_session) -> None:
    """下一模型回合的真实审计记录必须包含上一程序产生的所有领域事实"""
    novel_id, run_id = create_run_with_chunks(db_session, texts=["“去吧。”张三出门。"])
    model = ProgramModel(
        [
            (
                "entity(id='a1', name='张三', entity_type='chara"  # 同一程序文本
                "cter', evidence=1)\nevent(el='t1', evidence=1,"  # 同一程序文本
                " title='张三出门', problem='明确事件问题', summary='张三出"  # 同一程序文本
                "门', event_type='行动', status='ongoing')\npartic"  # 同一程序文本
                "ipants(el='t1', items=[{'name': '张三', 'entity"  # 同一程序文本
                "_type': 'character', 'role': '主体', 'action': "  # 同一程序文本
                "'出门', 'emotion': 1}])\ndialogue(candidate_inde"  # 同一程序文本
                "x=1, verdict='dialogue', evidence=1, speaker="  # 同一程序文本
                "{'name': '张三', 'entity_type': 'character'})\nm"  # 同一程序文本
                "etric(summary='出门', emotional_valence=0, narr"  # 同一程序文本
                "ative_function='铺垫')"  # 同一程序文本
            ),
            "finish()",
        ]
    )
    with patch("src.model_pool.llm.build_chat_model", return_value=model):
        assert await run_annotate(run_id, storage_for(db_session), novel_id=novel_id) == (1, 0, 1)
    db_session.expire_all()
    turns = fetch_agent_turns(storage_for(db_session), run_id)
    assert len(turns) == 2
    assert turns[0].agent_id == turns[1].agent_id
    assert [turn.turn_index for turn in turns] == [1, 2]
    facts = turns[1].context_summary["facts"]
    assert {"metrics", "events", "dialogues", "character_observations"} <= set(facts)
    assert facts["metrics"]["summary"] == "出门"
    assert facts["events"][0]["description"] == "张三出门"
    assert facts["dialogues"][0]["speaker"] == "张三"
    assert facts["character_observations"][0]["action"] == "出门"


@pytest.mark.asyncio
async def test_current_work_validates_serialized_participant_fields_before_save(db_session) -> None:
    """生产调用经 JSON 变成字典后，参与者仍按当前类型校验并写入真实章产出"""
    novel_id, run_id = create_run_with_chunks(db_session, texts=["张三出门。"])
    model = ProgramModel(
        "entity(id='a1', name='张三', entity_type='chara"  # 同一程序文本
        "cter', evidence=1)\nevent(el='t1', evidence=1,"  # 同一程序文本
        " title='张三出门', problem='明确事件问题', summary='张三出"  # 同一程序文本
        "门', event_type='行动', status='ongoing')\npartic"  # 同一程序文本
        "ipants(el='t1', items=[{'name': '张三', 'entity"  # 同一程序文本
        "_type': 'character', 'role': '主体', 'action': "  # 同一程序文本
        "'出门', 'emotion': 1}])\nmetric(summary='出门', em"  # 同一程序文本
        "otional_valence=0, narrative_function='铺垫')\nf"  # 同一程序文本
        "inish()"  # 同一程序文本
    )
    with patch("src.model_pool.llm.build_chat_model", return_value=model):
        assert await run_annotate(run_id, storage_for(db_session), novel_id=novel_id) == (1, 0, 1)
    db_session.expire_all()
    payload = chapter_annotations(storage_for(db_session), run_id)[0].payload
    entities = {
        row.entity_id: (row.canonical_name, row.entity_type)
        for row in db_session.scalars(select(GraphEntity).where(GraphEntity.run_id == run_id))
    }
    participant = payload["events"][0]["participants"][0]
    assert entities[participant["entity_id"]] == ("张三", "character")
    assert participant["role"] == "主体"
    assert payload["character_observations"][0]["action"] == "出门"
    assert payload["character_observations"][0]["emotion"] == 1


@pytest.mark.asyncio
async def test_long_chapter_saves_three_lanes_without_chapter_finalize(db_session, monkeypatch) -> None:
    monkeypatch.setattr(settings.models.annotation, "sub_chunk_max_chars", 2)
    novel_id, run_id = create_run_with_chunks(db_session, texts=["章中原文。"], chapter_ids=[1])
    model = ProgramModel('metric(summary="原文", emotional_valence=0, narrative_function="铺垫")\nfinish()')
    with patch("src.model_pool.llm.build_chat_model", return_value=model):
        assert await run_annotate(run_id, storage_for(db_session), novel_id=novel_id) == (1, 0, 1)
    db_session.expire_all()
    states = fetch_annotation_role_records(storage_for(db_session), run_id)
    assert {item.role for item in states} == {"entity", "event", "metric"}
    assert all(item.state == "saved" for item in states)
    assert len(_run_products(db_session, run_id)) == 3
    assert is_annotate_complete(storage_for(db_session), run_id)


class RoleModel(ProgramModel):
    async def ainvoke(self, messages):
        text = str(messages[1].content)
        if 'role="entity"' in text:
            self.code = 'entity(id="a1", name="张三", entity_type="character", evidence=1)\nfinish()'
        elif 'role="event"' in text:
            self.code = (
                "event(el='t1', evidence=1, title='独立事件', prob"  # 同一程序文本
                "lem='明确事件问题', summary='独立事件', event_type='行动'"  # 同一程序文本
                ", status='ongoing')\nfinish()"  # 同一程序文本
            )
        else:
            self.code = 'metric(summary="原文", emotional_valence=0, narrative_function="铺垫")\nfinish()'
        return await super().ainvoke(messages)


@pytest.mark.asyncio
async def test_later_chapter_saves_while_earlier_model_is_running(db_session, configured_model_pool):
    import asyncio

    from src.model_pool.capacity import MODEL_CAPACITY

    novel_id, run_id = create_run_with_chunks(db_session, texts=["早章。", "后章。"], chapter_ids=[1, 2])
    later_saved = asyncio.Event()

    class OrderedModel(ProgramModel):
        async def ainvoke(self, messages):
            if "早章" in str(messages[1].content):
                await asyncio.wait_for(later_saved.wait(), 3)
            return await super().ainvoke(messages)

    model = OrderedModel('metric(summary="实际输出", emotional_valence=0, narrative_function="铺垫")\nfinish()')
    order = []

    from src.storage.access import AnnotationAccess
    original_save = AnnotationAccess.save
    loop = asyncio.get_running_loop()

    def saved(access, request):
        result = original_save(access, request)
        chapter = request.record["chapter_id"]
        order.append(chapter)
        if chapter == 2:
            loop.call_soon_threadsafe(later_saved.set)
        return result

    with (
        patch("src.model_pool.llm.build_chat_model", return_value=model),
        patch.object(AnnotationAccess, "save", saved),
    ):
        assert await run_annotate(run_id, storage_for(db_session), novel_id=novel_id) == (2, 0, 2)
    assert order == [2, 1]
    assert not any(MODEL_CAPACITY.snapshot().values())


@pytest.mark.asyncio
async def test_recovery_discards_partial_roles_and_keeps_completed_chapter(db_session, monkeypatch):
    monkeypatch.setattr(settings.models.annotation, "sub_chunk_max_chars", 2)
    novel_id, run_id = create_run_with_chunks(db_session, texts=["短", "长章原文。"], chapter_ids=[1, 2])
    model = RoleModel("")
    with patch("src.model_pool.llm.build_chat_model", return_value=model):
        await run_annotate(run_id, storage_for(db_session), novel_id=novel_id)
    db_session.expire_all()
    states = fetch_annotation_role_records(storage_for(db_session), run_id)
    complete = next(item for item in states if item.chapter_id == 1)
    retained_invocation = complete.invocation_id
    partial_event = next(item for item in states if item.role == "event")
    old_event_invocation = partial_event.invocation_id
    # 模拟整章部分角色产物丢失：只删该角色的正式产物（真实尝试由整章废弃清理）
    lost = next(item for item in states if item.role == "metric")
    db_session.execute(delete(ChapterAnnotation).where(ChapterAnnotation.agent_id == lost.invocation_id))
    db_session.commit()
    calls = model.calls
    with patch("src.model_pool.llm.build_chat_model", return_value=model):
        await run_annotate(run_id, storage_for(db_session), novel_id=novel_id)
    db_session.expire_all()
    assert model.calls - calls == 3
    # 章×角色才是稳定身份：重建后执行号必须换、身份键不变
    refreshed = {
        (item.chapter_id, item.role): item for item in fetch_annotation_role_records(storage_for(db_session), run_id)
    }
    assert refreshed[(complete.chapter_id, complete.role)].invocation_id == retained_invocation
    current_event = refreshed[(partial_event.chapter_id, partial_event.role)]
    assert current_event.invocation_id != old_event_invocation
    record_id = db_session.scalar(
        select(ChapterAnnotation.record_id).where(ChapterAnnotation.agent_id == current_event.invocation_id)
    )
    declaration = db_session.scalar(select(EventDeclaration).where(EventDeclaration.record_id == record_id))
    assert declaration is not None and declaration.title == "独立事件"
    # 废弃章的旧尝试随整章废弃一并清理（含其模型调用行），现存执行 = 短章 1 + 重建的 3 条 lane
    assert _agent_execution_count(db_session, run_id) == 7
    metric_rows = db_session.execute(
        select(ChapterAnnotation.role, ChapterAnnotation.summary).where(ChapterAnnotation.run_id == run_id)
    ).all()
    assert all(summary is None for role, summary in metric_rows if role in {"entity", "event"})


@pytest.mark.asyncio
async def test_recovery_discards_chapter_with_only_executions(db_session, monkeypatch):
    """只有失败执行行、尚无产物的章也必须随章级废弃清执行行：重派按 attempt=1 登记不得撞唯一约束"""
    monkeypatch.setattr(settings.models.annotation, "sub_chunk_max_chars", 2)
    novel_id, run_id = create_run_with_chunks(db_session, texts=["短", "长章原文。"], chapter_ids=[1, 2])

    class FailingModel(RoleModel):
        async def ainvoke(self, messages):
            if "长章原文" in str(messages[1].content):
                raise RuntimeError("模拟失败轮次：长章角色未产出")
            return await super().ainvoke(messages)

    with patch("src.model_pool.llm.build_chat_model", return_value=FailingModel("")):
        with pytest.raises(RuntimeError, match="模拟失败轮次"):
            await run_annotate(run_id, storage_for(db_session), novel_id=novel_id)
    db_session.expire_all()
    # 失败轮次留下真实执行行，长章一行产物都没有
    stale = db_session.scalar(
        select(func.count())
        .select_from(Agent)
        .where(Agent.run_id == run_id, Agent.status == "error")
    )
    assert stale >= 1
    assert not [item for item in fetch_annotation_role_records(storage_for(db_session), run_id) if item.chapter_id == 2]
    # 旧枚举按产物行取章，长章不在废弃集 → 重派撞 uq_executions_annotation_attempt
    model = RoleModel("")
    with patch("src.model_pool.llm.build_chat_model", return_value=model):
        await run_annotate(run_id, storage_for(db_session), novel_id=novel_id)
    db_session.expire_all()
    assert completed_chapters(fetch_annotation_role_records(storage_for(db_session), run_id)) == {1, 2}


@pytest.mark.asyncio
async def test_save_failure_rolls_back_all_business_and_releases_case(db_session, monkeypatch):
    from src.agents.annotation.agent import AnnotationAgent
    from src.model_pool.capacity import MODEL_CAPACITY

    novel_id, run_id = create_run_with_chunks(db_session, texts=["原文。"])
    model = ProgramModel(
        "pending(case_type='character', description='待核查')\nevent(el='t1', evi"  # 同一程序文本
        "dence=1, title='原文事件', problem='明确事件问题', summ"  # 同一程序文本
        "ary='原文事件', event_type='行动', status='ongoing'"  # 同一程序文本
        ")\nmetric(summary='原文', emotional_valence=0, n"  # 同一程序文本
        "arrative_function='铺垫')\nfinish()"  # 同一程序文本
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
    monkeypatch.setattr("src.storage.repositories.case_writes.CaseWritesRepository.save_work", fail_save)
    with patch("src.model_pool.llm.build_chat_model", return_value=model):
        with pytest.raises(RuntimeError, match="案例保存故障"):
            await run_annotate(run_id, storage_for(db_session), novel_id=novel_id)
    db_session.expire_all()
    # 失败事务不留下任何业务行：工作身份是派发期事实，正式产物与域数据必须为空
    assert _run_products(db_session, run_id) == []
    run_executions = _run_execution_ids(run_id)
    run_records = select(ChapterAnnotation.record_id).where(ChapterAnnotation.agent_id.in_(run_executions))
    assert (
        db_session.scalar(
            select(func.count()).select_from(EventDeclaration).where(EventDeclaration.record_id.in_(run_records))
        )
        == 0
    )
    assert (
        db_session.scalar(
            select(func.count())
            .select_from(GraphFact)
            .where(GraphFact.direct_producer_agent_id.in_(run_executions))
        )
        == 0
    )
    assert (
        db_session.scalar(select(func.count()).select_from(Case).where(Case.run_id == run_id)) == 0
    )
    assert aborted and not any(MODEL_CAPACITY.snapshot().values())
    assert _agent_execution_count(db_session, run_id) == 1


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
            owns_work = any(isinstance(row, ChapterAnnotation) for row in session.identity_map.values())
            # 队列 flush 后正式产物可能不再由 identity_map 强引用，实际新产物用查询确认
            owns_work = owns_work or bool(
                session.query(ChapterAnnotation)
                .join(Agent, Agent.id == ChapterAnnotation.agent_id)
                .filter(ChapterAnnotation.run_id == run_id)
                .count()
            )
            original_commit()
            if owns_work and not replies:
                assert any(MODEL_CAPACITY.snapshot().values())
                replies.append("lost")
                raise OSError("提交回执丢失")

        session.commit = commit
        return session

    from src.storage import Storage
    from src.storage.operations import OperationRunner

    monkeypatch.setattr(
        "src.workflows.annotate.get_storage_factory", lambda: lambda: Storage(_runner=OperationRunner(factory))
    )
    model = ProgramModel('metric(summary="原文", emotional_valence=0, narrative_function="铺垫")\nfinish()')
    with patch("src.model_pool.llm.build_chat_model", return_value=model):
        assert await run_annotate(run_id, storage_for(db_session), novel_id=novel_id) == (1, 0, 1)
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
    monkeypatch.setattr("src.model_pool.selection.select_annotation_model", lambda *args, **kwargs: None)
    with pytest.raises(ModelElectionExhausted):
        await run_annotate(run_id, storage_for(db_session), novel_id=novel_id)
    assert not started
    db_session.expire_all()
    assert _run_products(db_session, run_id) == []
    # 未保存的角色没有产物行：pending 由缺行表达
    assert fetch_annotation_role_records(storage_for(db_session), run_id) == []


@pytest.mark.asyncio
async def test_program_can_read_shared_nodes_claim_case_and_save_cross_chapter_link(db_session, configured_model_pool):
    from src.case_pool import CasePool
    from src.storage.models import NarrativeLink

    settings.models.model_pool[0].max_in_flight = 1
    novel_id, run_id = create_run_with_chunks(
        db_session, texts=["张三拾得旧信。", "张三读懂旧信。"], chapter_ids=[1, 2]
    )

    class SharedModel(ProgramModel):
        async def ainvoke(self, messages):
            if "拾得" in str(messages[1].content):
                self.code = (
                    "pending(case_type='character', description='旧信的用途')\nevent(el='t1', e"  # 同一程序文本
                    "vidence=1, isforeshadowing=True, confidence='"  # 同一程序文本
                    "high', title='拾得旧信', problem='明确事件问题', summar"  # 同一程序文本
                    "y='拾得旧信', event_type='行动', status='ongoing')\n"  # 同一程序文本
                    "metric(summary='拾信', emotional_valence=0, nar"  # 同一程序文本
                    "rative_function='铺垫')\nfinish()"  # 同一程序文本
                )
            else:
                self.code = """
cases = search_cases()
promise_case(case_id=cases[0]["case_id"])
page = search_events(query="拾得")
source = page["events"][0]["declaration_id"]
created = event(el="t1", evidence=1, title="读懂旧信", problem="旧信有何用途",
                summary="读懂旧信", event_type="发现", status="resolved")
write_link(source_id=source, target_id=created["ref"]["declaration_id"],
           kind="foreshadowing", reason="旧信内容得以解释", evidence=1, caseid=cases[0]["case_id"])
metric(summary="读信", emotional_valence=0, narrative_function="铺垫")
finish()
"""
            return await super().ainvoke(messages)

    with patch("src.model_pool.llm.build_chat_model", return_value=SharedModel("")):
        assert await run_annotate(run_id, storage_for(db_session), novel_id=novel_id) == (2, 0, 2)
    db_session.expire_all()
    pool = CasePool(run_id)
    pool.load_storage(storage_for(db_session))
    resolved = [record for record in pool.search() if record["promised"]]
    assert len(resolved) == 1
    row = db_session.get(Case, resolved[0]["case_id"])
    assert row.status == "resolved" and row.promised_agent_id is not None
    links = list(
        db_session.scalars(
            select(NarrativeLink).where(
                NarrativeLink.producer_agent_id.in_(
                    select(Agent.id).where(Agent.run_id == run_id)
                )
            )
        )
    )
    assert [link.relation_type for link in links] == ["foreshadowing"]



@pytest.mark.asyncio
async def test_read_authorization_survives_failed_call_rollback(db_session, configured_model_pool) -> None:
    """失败调用回滚后，此后读取的授权记录仍必须对现行 work 可见"""
    from src.storage.models import NarrativeLink

    settings.models.model_pool[0].max_in_flight = 1
    novel_id, run_id = create_run_with_chunks(
        db_session, texts=["张三拾得旧信。", "张三读懂旧信。"], chapter_ids=[1, 2]
    )
    first_code = (
        "event(el='t1', evidence=1, isforeshadowing=True, confidence='"
        "high', title='拾得旧信', problem='明确事件问题', summary="
        "'拾得旧信', event_type='行动', status='ongoing')\n"
        "metric(summary='拾信', emotional_valence=0, narrative_"
        "function='铺垫')\nfinish()"
    )
    second_code = (
        "rejected = write_link(source_id='00000000-0000-0000-0000-000000000000',"
        " target_id='00000000-0000-0000-0000-000000000000', kind='causal',"
        " reason='无效引用制造一次失败回滚', evidence=1)\n"
        "page = search_events(query='拾得')\n"
        "source = page['events'][0]['declaration_id']\n"
        "detail = read_event(node_id=source)\n"
        "created = event(el='t1', evidence=1, title='读懂旧信', problem='旧信有何用途',"
        " summary='读懂旧信', event_type='发现', status='resolved')\n"
        "write_link(source_id=source, target_id=created['ref']['declaration_id'],"
        " kind='foreshadowing', reason='旧信内容得以解释', evidence=1)\n"
        "metric(summary='读信', emotional_valence=0, narrative_function='铺垫')\n"
        "finish()"
    )

    class ChapterAwareModel(StreamedFakeModelMixin):
        model_name = "test_model"

        def bind_tools(self, tools):
            return self

        async def ainvoke(self, messages):
            code = second_code if "读懂" in str(messages) else first_code
            return AIMessage(content="", tool_calls=[{"name": "execute_code", "args": {"code": code}, "id": "call"}])

    with patch("src.model_pool.llm.build_chat_model", return_value=ChapterAwareModel()):
        assert await run_annotate(run_id, storage_for(db_session), novel_id=novel_id) == (2, 0, 2)
    db_session.expire_all()
    links = list(
        db_session.scalars(
            select(NarrativeLink).where(NarrativeLink.producer_agent_id.in_(_run_execution_ids(run_id)))
        )
    )
    assert [link.relation_type for link in links] == ["foreshadowing"]


@pytest.mark.asyncio
async def test_same_batch_write_after_finish_is_saved_and_audited(db_session):
    novel_id, run_id = create_run_with_chunks(db_session, texts=["原文。"])
    model = ProgramModel(
        'metric(summary="原文", emotional_valence=0, nar'  # 同一程序文本
        'rative_function="铺垫")\nfinish()\npending(case_type="dialogue", descri'  # 同一程序文本
        'ption="迟到")'  # 同一程序文本
    )
    with patch("src.model_pool.llm.build_chat_model", return_value=model):
        assert await run_annotate(run_id, storage_for(db_session), novel_id=novel_id) == (1, 0, 1)
    assert model.calls == 1
    assert db_session.query(Case).filter(Case.run_id == run_id).count() == 1
    turns = fetch_agent_turns(storage_for(db_session), run_id)
    assert len(turns) == 1
    tool_calls = fetch_run_tool_calls(storage_for(db_session), run_id)
    by_name = {call.tool_name: call for call in tool_calls if call.call_id == turns[0].call_id}
    assert by_name["pending"].error is None
    program_call = by_name["execute_code"]
    assert program_call.error is None
    receipt = program_call.receipt_observed
    assert receipt["status"] == "applied"
    assert receipt["applied"] == 3


@pytest.mark.asyncio
async def test_runtime_name_references_auto_register_all_four_surfaces(db_session) -> None:
    """真实保存链不先富登记，四个引用面会合到同一组正式实体"""
    novel_id, run_id = create_run_with_chunks(db_session, texts=["“去吧。”张三出门去山门找李四。"])
    model = ProgramModel(
        "event(el='t1', evidence=1, title='张三出门', prob"  # 同一程序文本
        "lem='明确事件问题', summary='张三出门', event_type='行动'"  # 同一程序文本
        ", status='ongoing')\nparticipants(el='t1', ite"  # 同一程序文本
        "ms=[{'name': '张三', 'entity_type': 'character'"  # 同一程序文本
        ", 'role': '主体'}, {'name': '山门', 'entity_type'"  # 同一程序文本
        ": 'organization', 'role': '地点'}])\nrelation(fr"  # 同一程序文本
        "om_entity={'name': '张三', 'entity_type': 'char"  # 同一程序文本
        "acter'}, to_entity={'name': '李四', 'entity_typ"  # 同一程序文本
        "e': 'character'}, relation_type='盟友')\ndialogu"  # 同一程序文本
        "e(candidate_index=1, verdict='dialogue', evid"  # 同一程序文本
        "ence=1, speaker={'name': '张三', 'entity_type':"  # 同一程序文本
        " 'character'})\nmetric(summary='出门', emotional"  # 同一程序文本
        "_valence=0, narrative_function='铺垫')\nfinish()"  # 同一程序文本
    )
    with patch("src.model_pool.llm.build_chat_model", return_value=model):
        assert await run_annotate(run_id, storage_for(db_session), novel_id=novel_id) == (1, 0, 1)
    db_session.expire_all()
    entities = db_session.scalars(select(GraphEntity).where(GraphEntity.run_id == run_id)).all()
    assert {(entity.canonical_name, entity.entity_type) for entity in entities} == {
        ("张三", "character"),
        ("李四", "character"),
        ("山门", "organization"),
    }
    relations = list(
        db_session.scalars(
            select(GraphRelation).where(
                GraphRelation.relation_id.in_(
                    select(GraphFact.relation_id).where(
                        GraphFact.direct_producer_agent_id.in_(_run_execution_ids(run_id)),
                        GraphFact.relation_id.is_not(None),
                    )
                )
            )
        )
    )
    assert len(relations) == 1
    dialogues = list(
        db_session.scalars(
            select(DialogueRecord)
            .join(Agent, Agent.id == DialogueRecord.creation_agent_id)
            .where(Agent.run_id == run_id)
        )
    )
    assert [row.speaker_entity_id for row in dialogues] == [
        entity.entity_id for entity in entities if entity.canonical_name == "张三"
    ]
    assert model.calls == 1
