"""实际业务事务提交后的确认恢复，不重复模型请求或案例办理"""

from __future__ import annotations

import asyncio
from unittest.mock import patch

import pytest
from langchain_core.messages import AIMessage
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from src.agents.annotation.agent import AnnotationAgent
from src.agents.annotation.work import annotation_work_id
from src.case_pool import CasePool
from src.config import settings
from src.event_bus import Message
from src.storage.models import AnalysisOutput, AnnotationWork, BookCase
from src.workflows.annotate import run_annotate
from tests.support.chapter_annotation_helpers import create_run_with_chunks
from tests.workflows.test_annotation_work_pipeline import ProgramModel


@pytest.mark.asyncio
async def test_committed_case_recovers_confirmation_without_second_model_execution(
    db_session: Session, monkeypatch: pytest.MonkeyPatch, configured_model_pool: None
) -> None:
    """确认中断后保留实际保存事实和案例占用，从存储重建再完成确认"""
    novel_id, run_id = create_run_with_chunks(db_session, texts=["张三确认旧信的内容。"])
    model = ProgramModel(
        'pending(description="核查旧信")\n'
        'cases = search_cases()\n'
        'promise_case(case_id=cases[0]["case_id"])\n'
        'read_text(paragraph_id=0)\n'
        'metric(summary="已核查正文", emotional_valence=0, narrative_function="铺垫")\n'
        'finish(case_delivery={"case_id":cases[0]["case_id"],"state":"resolved","reason":"已阅读原文，无需新增连接"})'
    )
    original_confirm = CasePool.confirm
    original_recover = AnnotationAgent.recover
    interrupted: list[tuple[str, str]] = []
    recovered: list[str] = []

    def interrupted_confirm(pool: CasePool, work_id: str, invocation_id: str) -> None:
        if not interrupted:
            interrupted.append((work_id, invocation_id))
            assert next(iter(pool.case_runtime.values()))["owner"] == (work_id, invocation_id)
            raise RuntimeError("业务提交后案例内存确认中断")
        original_confirm(pool, work_id, invocation_id)

    async def observed_recover(agent: AnnotationAgent, message: Message) -> None:
        if message.work_id:
            recovered.append(message.work_id)
            # 尚未核清存储前不能释放此前已接受 resolved 交付的占用
            assert next(iter(agent.case_pool.case_runtime.values()))["owner"] == interrupted[0]
        await original_recover(agent, message)

    monkeypatch.setattr(CasePool, "confirm", interrupted_confirm)
    monkeypatch.setattr(AnnotationAgent, "recover", observed_recover)
    with patch("src.model_pool.llm.build_chat_model", return_value=model):
        assert await run_annotate(run_id, db_session, novel_id=novel_id) == (1, 0, 1)
        assert await run_annotate(run_id, db_session, novel_id=novel_id) == (1, 0, 1)

    assert model.calls == 1
    assert len(interrupted) == 1
    assert recovered == [interrupted[0][0]]
    db_session.expire_all()
    works = list(db_session.execute(select(AnnotationWork).where(AnnotationWork.run_id == run_id)).scalars())
    outputs = list(
        db_session.execute(select(AnalysisOutput).where(AnalysisOutput.run_id == run_id)).scalars()
    )
    assert len(works) == len(outputs) == 1
    assert works[0].state == "saved"
    assert works[0].invocation_id == interrupted[0][1]
    states = list(db_session.execute(select(BookCase).where(BookCase.run_id == run_id)).scalars())
    assert len(states) == 1
    assert states[0].state == "resolved"
    deliveries = states[0].contributions[works[0].work_id]["deliveries"]
    assert len(deliveries) == 1


@pytest.mark.asyncio
async def test_confirmation_recovery_preserves_concurrent_entity_and_case_owner(
    db_session: Session, monkeypatch: pytest.MonkeyPatch, configured_model_pool: None
) -> None:
    """用真实工具与事务验证单作者恢复不会撤销另一个正在执行的作者"""
    novel_id, run_id = create_run_with_chunks(
        db_session, texts=["甲章整理记录。", "乙章调查线索。"], chapter_ids=[1, 2]
    )
    first_work = annotation_work_id(run_id, 1, "solo")
    other_work = annotation_work_id(run_id, 2, "solo")
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
                    'pending(description="乙章独占线索")\n'
                    'cases = search_cases()\npromise_case(case_id=cases[0]["case_id"])'
                )
            else:
                other_ready.set()
                await asyncio.wait_for(other_release.wait(), timeout=5)
                code = (
                    'cases = search_cases()\n'
                    'metric(summary="乙章完成", emotional_valence=0, narrative_function="铺垫")\n'
                    'finish(case_delivery={"case_id":cases[0]["case_id"],"state":"deferred","reason":"需后文核查"})'
                )
            return AIMessage(
                content="", tool_calls=[{"name": "execute_code", "args": {"code": code}, "id": f"call{self.calls}"}]
            )

    model = ConcurrentModel()
    original_confirm = CasePool.confirm
    original_recover = AnnotationAgent.recover
    interrupted = False
    observed: list[str] = []

    def interrupted_confirm(pool: CasePool, work_id: str, invocation_id: str) -> None:
        nonlocal interrupted
        if work_id == first_work and not interrupted:
            interrupted = True
            raise RuntimeError("甲章提交后确认中断，乙章仍在执行")
        original_confirm(pool, work_id, invocation_id)

    async def observed_recover(agent: AnnotationAgent, message: Message) -> None:
        if message.work_id != first_work:
            await original_recover(agent, message)
            return
        other = agent.executions[other_work]
        author = (other.work_id, other.invocation_id)
        case = next(iter(agent.case_pool.case_runtime.values()))
        entity_id = agent.fact_graph.entity_id("乙章人物")
        assert case["owner"] == author
        assert author not in agent.fact_graph.saved
        await original_recover(agent, message)
        assert next(iter(agent.case_pool.case_runtime.values()))["owner"] == author
        assert agent.fact_graph.entity_id("乙章人物") == entity_id
        assert agent.fact_graph.resolve_entity_id(entity_id, label="确认恢复后乙章实体") == "乙章人物"
        assert author in agent.fact_graph.contributions
        assert author not in agent.fact_graph.saved
        observed.append(message.work_id)
        other_release.set()

    monkeypatch.setattr(CasePool, "confirm", interrupted_confirm)
    monkeypatch.setattr(AnnotationAgent, "recover", observed_recover)
    with patch("src.model_pool.llm.build_chat_model", return_value=model):
        assert await run_annotate(run_id, db_session, novel_id=novel_id) == (2, 0, 2)
    assert model.chapter_calls == {1: 1, 2: 2}
    assert observed == [first_work]
    db_session.expire_all()
    works = list(db_session.execute(select(AnnotationWork).where(AnnotationWork.run_id == run_id)).scalars())
    assert len(works) == 2
    assert all(work.state == "saved" for work in works)
    state = db_session.execute(select(BookCase).where(BookCase.run_id == run_id)).scalar_one()
    assert state.state == "deferred"
    assert len(state.contributions[other_work]["deliveries"]) == 1


@pytest.mark.asyncio
async def test_resume_threshold_change_resets_only_discarded_chapter_display(
    db_session: Session, monkeypatch: pytest.MonkeyPatch, configured_model_pool: None
) -> None:
    """恢复长章为 solo 时清除旧章的全部角色展示，保留已经完整保存的另一章"""
    monkeypatch.setattr(settings.models.annotation, "sub_chunk_max_chars", 2)
    novel_id, run_id = create_run_with_chunks(db_session, texts=["长章原文。", "短。"], chapter_ids=[1, 2])
    model = ProgramModel('metric(summary="原文", emotional_valence=0, narrative_function="铺垫")\nfinish()')
    with patch("src.model_pool.llm.build_chat_model", return_value=model):
        assert await run_annotate(run_id, db_session, novel_id=novel_id) == (2, 0, 2)
    db_session.execute(delete(AnnotationWork).where(
        AnnotationWork.run_id == run_id, AnnotationWork.chapter_id == 1, AnnotationWork.role == "evidence"
    ))
    db_session.commit()
    monkeypatch.setattr(settings.models.annotation, "sub_chunk_max_chars", 100)
    shown = []

    async def emit(event) -> None:
        shown.append(event)

    before = model.calls
    with patch("src.model_pool.llm.build_chat_model", return_value=model):
        assert await run_annotate(run_id, db_session, novel_id=novel_id, emitter=emit) == (2, 0, 2)
    assert model.calls - before == 1
    resets = [event for event in shown if event.action == "chapter_reset"]
    assert [event.chapter_id for event in resets] == [1]
    assert shown.index(resets[0]) < next(index for index, event in enumerate(shown) if event.action == "work_reset")
    assert [event.sub_stage for event in shown if event.action == "work_reset"] == ["solo"]
