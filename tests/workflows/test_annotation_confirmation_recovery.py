"""实际业务事务提交后的确认恢复，不重复模型请求或案例办理"""

from __future__ import annotations

import asyncio
from unittest.mock import patch

import pytest
from langchain_core.messages import AIMessage
from sqlalchemy import select
from sqlalchemy.orm import Session

from src.agents.annotation.agent import AnnotationAgent
from src.case_pool import CasePool
from src.config import settings
from src.event_bus import Message
from src.storage.models import (
    Agent,
    Case,
    ChapterAnnotation,
    CompleteEvent,
    EventForeshadowingAction,
    GraphFact,
)
from src.work.annotation_work import annotation_work_id
from src.work.queries import fetch_annotation_role_records
from src.workflows.annotate import run_annotate
from tests.support.chapter_annotation_helpers import create_run_with_chunks
from tests.support.storage_fixtures import storage_for
from tests.workflows.test_annotation_work_pipeline import ProgramModel


def _run_executions(run_id: str):
    """本 run 真实尝试的执行选择器（执行行直接携带运行归属）"""
    return select(Agent.id).where(Agent.run_id == run_id)


def _run_products(db_session, run_id: str) -> list[ChapterAnnotation]:
    return list(db_session.scalars(select(ChapterAnnotation).where(ChapterAnnotation.run_id == run_id)))


@pytest.mark.asyncio
async def test_committed_case_recovers_confirmation_without_second_model_execution(
    db_session: Session, monkeypatch: pytest.MonkeyPatch, configured_model_pool: None
) -> None:
    """确认中断后保留实际保存事实和案例占用，从存储重建再完成确认"""
    novel_id, run_id = create_run_with_chunks(db_session, texts=["张三确认旧信的内容。"])
    model = ProgramModel(
        'pending(case_type="character", description="核查旧信")\n'
        "cases = search_cases()\n"
        'promise_case(case_id=cases[0]["case_id"])\n'
        "read_text(paragraph_id=0)\n"
        'event(el="e1", title="确认旧信", problem="旧信是否可靠", summary="张三确认旧信内容", '
        'event_type="核查", status="ongoing", evidence=1, isforeshadowing=True, confidence="high")\n'
        'plotline(subject_title="旧信真伪", description="确认内容", before="未知", after="可靠", '
        'evidence=1, event_id="e1")\n'
        'foreshadow_action(source_event_id="e1", action_type="reinforce", evidence=1)\n'
        'metric(summary="已核查正文", emotional_valence=0, '  # 同一程序文本
        'narrative_function="铺垫", caseid=cases[0]["cas'  # 同一程序文本
        'e_id"])\n'  # 同一程序文本
        "finish()"
    )
    original_confirm = CasePool.confirm
    original_recover = AnnotationAgent.recover
    interrupted: list[str] = []
    recovered: list[str] = []

    def interrupted_confirm(pool: CasePool, author: str) -> None:
        if not interrupted:
            interrupted.append(author)
            assert next(iter(pool.case_runtime.values()))["owner"] == author
            raise RuntimeError("业务提交后案例内存确认中断")
        original_confirm(pool, author)

    async def observed_recover(agent: AnnotationAgent, message: Message) -> None:
        if message.work_id:
            recovered.append(message.work_id)
            # 恢复只覆盖被中断的执行
            assert agent.executions[message.work_id].invocation_id == interrupted[0]
            # 尚未核清存储前不能释放已接受 resolved 交付的占用
            assert next(iter(agent.case_pool.case_runtime.values()))["owner"] == interrupted[0]
        await original_recover(agent, message)

    monkeypatch.setattr(CasePool, "confirm", interrupted_confirm)
    monkeypatch.setattr(AnnotationAgent, "recover", observed_recover)
    with patch("src.model_pool.llm.build_chat_model", return_value=model):
        assert await run_annotate(run_id, storage_for(db_session), novel_id=novel_id) == (1, 0, 1)
        assert await run_annotate(run_id, storage_for(db_session), novel_id=novel_id) == (1, 0, 1)

    assert model.calls == 1
    assert len(interrupted) == 1
    assert recovered == [annotation_work_id(run_id, 1, "annotation")]
    db_session.expire_all()
    states = fetch_annotation_role_records(storage_for(db_session), run_id)
    products = _run_products(db_session, run_id)
    assert len(states) == len(products) == 1
    assert states[0].state == "saved"
    assert states[0].invocation_id == interrupted[0]
    assert products[0].agent_id == interrupted[0]
    pool = CasePool(run_id)
    pool.load_storage(storage_for(db_session))
    records = pool.search()
    # 「建一个事件进一个池」：声明案例随 write_event 自动登记为 event 案例，另有一行已承诺
    promised = [record for record in records if record["promised"]]
    assert len(records) == 2 and len(promised) == 1
    assert pool.submissions_for(states[0].invocation_id) == [promised[0]["case_id"]]
    declaration = db_session.scalar(
        select(CompleteEvent).where(CompleteEvent.annotation_record_id == products[0].record_id)
    )
    assert declaration.title == "确认旧信" and declaration.status == "ongoing"
    assert (
        db_session.scalar(select(CompleteEvent).where(CompleteEvent.producer_agent_id.in_(_run_executions(run_id))))
        is None
    )
    actions = list(
        db_session.scalars(
            select(EventForeshadowingAction).where(
                EventForeshadowingAction.producer_agent_id.in_(_run_executions(run_id))
            )
        )
    )
    assert {action.action_type for action in actions} == {"setup", "reinforce"}
    # 写事件自带 setup 指向本声明；程序显式提交的 reinforce 只给来源，不指定目标
    assert all(action.source_event_id == declaration.event_id for action in actions)
    setup = next(action for action in actions if action.action_type == "setup")
    reinforce = next(action for action in actions if action.action_type == "reinforce")
    assert setup.target_event_id == declaration.event_id
    assert reinforce.target_event_id is None
    plotline = db_session.scalar(
        select(GraphFact).where(
            GraphFact.direct_producer_agent_id.in_(_run_executions(run_id)),
            GraphFact.plotline_subject_title.is_not(None),
        )
    )
    assert plotline.event_id == declaration.event_id and plotline.business_call_id is not None


@pytest.mark.asyncio
async def test_confirmation_recovery_preserves_concurrent_entity_and_case_owner(
    db_session: Session, monkeypatch: pytest.MonkeyPatch, configured_model_pool: None
) -> None:
    """用真实工具与事务验证单作者恢复不会撤销另一个正在执行的作者"""
    novel_id, run_id = create_run_with_chunks(
        db_session, texts=["甲章整理记录。", "乙章调查线索。"], chapter_ids=[1, 2]
    )
    first_work = annotation_work_id(run_id, 1, "annotation")
    other_work = annotation_work_id(run_id, 2, "annotation")
    other_ready = asyncio.Event()
    other_release = asyncio.Event()

    class ConcurrentModel(ProgramModel):
        def __init__(self) -> None:
            super().__init__("")
            self.chapter_calls = {1: 0, 2: 0}

        async def ainvoke(self, messages: list) -> AIMessage:
            chapter = 1 if "甲章整理记录" in str(messages[1].content) else 2
            self.chapter_calls[chapter] += 1
            self.calls += 1
            if chapter == 1:
                await asyncio.wait_for(other_ready.wait(), timeout=5)
                code = 'metric(summary="甲章完成", emotional_valence=0, narrative_function="铺垫")\nfinish()'
            elif self.chapter_calls[2] == 1:
                code = (
                    'entity(id="a1", name="乙章人物", entity_type="character", evidence=1)\n'
                    'pending(case_type="relation", description="乙章独占线索")\n'
                    'cases = search_cases()\npromise_case(case_id=cases[0]["case_id"])'
                )
            else:
                other_ready.set()
                await asyncio.wait_for(other_release.wait(), timeout=5)
                code = (
                    "cases = search_cases()\n"
                    'metric(summary="乙章完成", emotional_valence=0, narrative_function="铺垫")\n'
                    "finish()"
                )
            return AIMessage(
                content="", tool_calls=[{"name": "execute_code", "args": {"code": code}, "id": f"call{self.calls}"}]
            )

    model = ConcurrentModel()
    original_confirm = CasePool.confirm
    original_recover = AnnotationAgent.recover
    interrupted = False
    observed: list[str] = []

    def interrupted_confirm(pool: CasePool, author: str) -> None:
        nonlocal interrupted
        if not interrupted:
            # 甲章提交后确认中断，乙章仍在执行：乙章确认被 other_release 挡在后
            interrupted = True
            raise RuntimeError("甲章提交后确认中断，乙章仍在执行")
        original_confirm(pool, author)

    async def observed_recover(agent: AnnotationAgent, message: Message) -> None:
        if message.work_id != first_work:
            await original_recover(agent, message)
            return
        other = agent.executions[other_work]
        author = other.invocation_id
        case = next(iter(agent.case_pool.case_runtime.values()))
        entity_id = agent.fact_graph.entity_id("乙章人物", "character")
        assert case["owner"] == author
        assert author not in agent.fact_graph.saved
        await original_recover(agent, message)
        assert next(iter(agent.case_pool.case_runtime.values()))["owner"] == author
        assert agent.fact_graph.entity_id("乙章人物", "character") == entity_id
        resolved = agent.fact_graph.resolve_entity_id(entity_id, label="确认恢复后乙章实体")
        assert agent.fact_graph.display_name(resolved) == "乙章人物"
        assert author in agent.fact_graph.contributions
        assert author not in agent.fact_graph.saved
        observed.append(message.work_id)
        other_release.set()

    monkeypatch.setattr(CasePool, "confirm", interrupted_confirm)
    monkeypatch.setattr(AnnotationAgent, "recover", observed_recover)
    with patch("src.model_pool.llm.build_chat_model", return_value=model):
        assert await run_annotate(run_id, storage_for(db_session), novel_id=novel_id) == (2, 0, 2)
    assert model.chapter_calls == {1: 1, 2: 2}
    assert observed == [first_work]
    db_session.expire_all()
    states = fetch_annotation_role_records(storage_for(db_session), run_id)
    assert len(states) == 2
    assert all(item.state == "saved" for item in states)
    pool = CasePool(run_id)
    pool.load_storage(storage_for(db_session))
    records = pool.search()
    target = next(record for record in records if record["description"] == "乙章独占线索")
    # 承诺即解决：承诺痕迹落库；未产生写交付，支持条目 adopted=False
    assert target["submitted"] is True

    row = db_session.get(Case, target["case_id"])
    assert row.status == "resolved" and row.promised_agent_id is not None
    assert len(records) == 2
    assert any("实体尚无正式引用" in record["description"] for record in records)


@pytest.mark.asyncio
async def test_resume_threshold_change_clears_discarded_chapter_lanes(
    db_session: Session, monkeypatch: pytest.MonkeyPatch, configured_model_pool: None
) -> None:
    """中断留下的未完成长章按新阈值只重建整章标注：恢复先清除旧车道展示再重跑"""
    monkeypatch.setattr(settings.models.annotation, "sub_chunk_max_chars", 2)
    novel_id, run_id = create_run_with_chunks(db_session, texts=["长章原文。"])
    cancelled: list[bool] = []

    from src.storage.access import AnnotationAccess
    original_save = AnnotationAccess.save
    monkeypatch.setattr(settings.models.model_pool[0], "max_in_flight", 1)

    def cancel_on_first_save(access, request):
        result = original_save(access, request)
        cancelled.append(True)
        return result

    # 第一次运行在首个角色保存后取消：本章缺少必需角色，从未出章末核对凭据
    first = ProgramModel('metric(summary="原文", emotional_valence=0, narrative_function="铺垫")\nfinish()')
    with (
        patch("src.model_pool.llm.build_chat_model", return_value=first),
        patch.object(AnnotationAccess, "save", cancel_on_first_save),
    ):
        with pytest.raises(asyncio.CancelledError):
            await run_annotate(
                run_id,
                storage_for(db_session),
                novel_id=novel_id,
                is_cancelled=lambda: bool(cancelled),
            )
    assert cancelled
    db_session.expire_all()
    before = fetch_annotation_role_records(storage_for(db_session), run_id)
    # 只有已保存产物才有行：中断后长章三工位只留下一部分产物（pending 由缺行表达）
    assert 0 < len(before) < 3
    assert {item.role for item in before} <= {"entity", "event", "metric"}
    saved_before = {item.role: item.invocation_id for item in before}
    # 阈值放宽后本章只需整章标注：整章废弃重建，旧车道展示与旧产物身份都不保留
    monkeypatch.setattr(settings.models.annotation, "sub_chunk_max_chars", 100)
    shown = []

    async def emit(event) -> None:
        shown.append(event)

    second = ProgramModel('metric(summary="重建原文", emotional_valence=0, narrative_function="铺垫")\nfinish()')
    with patch("src.model_pool.llm.build_chat_model", return_value=second):
        assert await run_annotate(run_id, storage_for(db_session), novel_id=novel_id, emitter=emit) == (1, 0, 1)
    assert second.calls == 1
    resets = [event for event in shown if event.action == "chapter_reset"]
    assert [event.chapter_id for event in resets] == [1]
    assert shown.index(resets[0]) < next(index for index, event in enumerate(shown) if event.action == "work_reset")
    assert [event.sub_stage for event in shown if event.action == "work_reset"] == ["annotation"]
    db_session.expire_all()
    after = fetch_annotation_role_records(storage_for(db_session), run_id)
    assert [(item.chapter_id, item.role, item.state) for item in after] == [(1, "annotation", "saved")]
    assert after[0].invocation_id not in set(saved_before.values())
