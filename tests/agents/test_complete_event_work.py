"""从程序构造器至正式事务验证事件身份、跨章范围与包含结构"""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest
from sqlalchemy import select
from sqlalchemy.orm import sessionmaker

from src.agents.annotation.agent import AnnotationAgent, WorkExecution
from src.agents.annotation.agent_ir import AgentAnnotation
from src.agents.annotation.agent_runtime import AgentProgramRuntime
from src.agents.annotation.ledger import AnnotationToolLedger
from src.agents.annotation.paragraphs import build_chapter_paragraph_info
from src.agents.annotation.work_tools import build_work_tools
from src.event_bus import EventBus, Message
from src.storage import new_id
from src.storage.models import (
    Agent,
    Chapter,
    Paragraph,
)
from src.work.annotation_work import WorkReceipt, annotation_work_id
from tests.support.chapter_annotation_helpers import create_run_with_chunks
from tests.support.storage_fixtures import natural_record, storage_factory, storage_for


def execution_for(agent, session, chapter_id):
    from src.event_bus.activity import ActivityRelay

    if not agent.bus.has_handler("analysis.activity", f"activity:{agent.run_id}"):
        ActivityRelay(agent.bus, agent.run_id, None)
    chapter = natural_record(session, Chapter, {"run_id": agent.run_id, "chapter_id": chapter_id})
    # 段落终点是读取投影：与生产派发同口径投影出 local_end_char
    paragraphs = [
        SimpleNamespace(
            chapter_id=row.chapter_id,
            paragraph_id=row.paragraph_id,
            local_start_char=row.local_start_char,
            local_end_char=row.local_start_char + len(row.text),
            text=row.text,
        )
        for row in session.scalars(
            select(Paragraph)
            .where(Paragraph.run_id == agent.run_id, Paragraph.chapter_id == chapter_id)
            .order_by(Paragraph.paragraph_index)
        )
    ]
    invocation = new_id()
    work_id = annotation_work_id(agent.run_id, chapter_id, "event")
    payload = {
        "chapter_id": chapter_id,
        "chapter_sequence": chapter.sequence,
        "chapter_text": chapter.text,
        "role": "event",
        "paragraphs": paragraphs,
    }
    ledger = AnnotationToolLedger(
        run_scope=agent.run_id,
        current_chapter_id=chapter_id,
        current_chapter_text=chapter.text,
        current_chapter_order=chapter.sequence,
        allow_future_context=False,
        graph=agent.fact_graph,
        paragraph_info=build_chapter_paragraph_info(paragraphs),
        work_id=work_id,
        invocation_id=invocation,
        role="event",
    )
    execution = WorkExecution(
        WorkReceipt(work_id, agent.run_id, "annotation", payload), invocation, ledger, AgentAnnotation(role="event")
    )
    agent.executions[work_id] = execution
    # 作者身份收敛为单字符串：真实执行号就是三域的贡献作者
    agent.fact_graph.begin(invocation, chapter.sequence, "event")
    agent.event_trees.begin(invocation)
    agent.case_pool.begin(invocation)
    query = SimpleNamespace(
        chapter_orders={
            row.chapter_id: row.sequence
            for row in session.scalars(select(Chapter).where(Chapter.run_id == agent.run_id))
        },
        current_chapter_order=chapter.sequence,
    )
    tools = {tool.name: tool for tool in build_work_tools(agent, execution, query)}

    async def invoke(tool_map, call):
        return await agent.invoke_tool(execution, tool_map, call)

    ledger.invoke_tool = invoke
    ledger.finish_work = execution.validate
    return execution, AgentProgramRuntime(tools, ledger, execution.agent)


async def save_and_confirm(agent, session, execution):
    assert execution.validate() == []
    execution.finished = execution.agent.finished = execution.ledger.chapter_finished = True
    agent.freeze(execution)
    # 无 relationship：真实尝试 → 正式记录按依赖分层 flush
    payload = execution.receipt.payload
    session.add(Agent(id=execution.invocation_id, run_id=agent.run_id, type=payload["role"], status="success"))
    session.flush()
    identifier = agent._save(execution, storage_for(session))
    session.commit()
    await agent.confirm(
        Message(
            topic="agent.confirm",
            source="test",
            target=agent.address,
            run_id=agent.run_id,
            work_id=execution.work_id,
            invocation_id=execution.invocation_id,
        )
    )
    return identifier


def declaration_code(key, summary):
    return (
        "event("
        + ", ".join(
            f"{name}={value!r}"
            for name, value in {
                "el": key,
                "title": summary,
                "problem": summary + "能否完成",
                "summary": summary,
                "event_type": "行动",
                "status": "ongoing",
                "evidence": 1,
            }.items()
        )
        + ")"
    )


@pytest.mark.parametrize("reverse", [False, True])
async def test_same_fact_cannot_be_recreated_as_second_declaration(db_session, reverse):
    novel, run = create_run_with_chunks(db_session, texts=["入门后挡火。"])
    agent = AnnotationAgent(EventBus(), run, storage_factory(lambda: db_session), novel_id=novel)
    execution, runtime = execution_for(agent, db_session, 1)
    try:
        calls = [declaration_code("a", "入门"), declaration_code("b", "挡火")]
        if reverse:
            calls.reverse()
        receipt = json.loads(await runtime.execute("\n".join(calls)))
        assert not receipt.get("failed"), receipt
        rejected = json.loads(await runtime.execute(declaration_code("c", "挡火")))
        assert "duplicate_annotation_event" in str(rejected)
        assert len(execution.ledger.bound_payloads["events"]) == 2
        assert all(item.parent_node_id is None for item in execution.ledger.bound_payloads["events"])
        await save_and_confirm(agent, db_session, execution)
    finally:
        agent.close()


async def test_annotation_declarations_then_diagnosis_once_publication(db_session):
    from src.event_trees.read.organization import EventTreeQuery
    from src.event_trees.storage_map import run_annotation_event_ids, run_events
    from tests.support.event_tree_fixtures import identity_every_declaration, publish_draft

    novel_id, run_id = create_run_with_chunks(db_session, texts=["顾霜寻找山门，点燃一盏灯。"])
    agent = AnnotationAgent(
        EventBus(), run_id, storage_factory(sessionmaker(bind=db_session.get_bind())), novel_id=novel_id
    )
    execution, runtime = execution_for(agent, db_session, 1)
    try:
        result = json.loads(
            await runtime.execute(
                declaration_code("search", "顾霜寻找山门") + "\n" + declaration_code("lamp", "顾霜点灯") + "\nfinish()"
            )
        )
        assert not result.get("failed"), result
        assert result["written_refs"][0]["ref"]["event_id"]
        await save_and_confirm(agent, db_session, execution)
        assert len(run_events(storage_for(db_session), run_id)) == 2
        assert EventTreeQuery(storage_for(db_session), run_id).fetch()["organization_status"] == "pending_diagnosis"
        draft, _meta = identity_every_declaration(db_session, run_id)
        publish_draft(db_session, run_id, draft)
        assert len(run_events(storage_for(db_session), run_id)) == 2
        assert len(run_annotation_event_ids(storage_for(db_session), run_id)) == 2
        assert EventTreeQuery(storage_for(db_session), run_id).fetch()["organization_status"] == "ready"
    finally:
        agent.close()


async def test_annotation_builds_cross_chapter_parent_and_preserves_promised_child_case(db_session):
    from src.event_trees.read.organization import EventTreeQuery
    from src.storage.models import CompleteEvent

    novel, run = create_run_with_chunks(
        db_session, texts=["顾霜入门。", "顾霜继续调查。", "顾霜发现后事。"], chapter_ids=[11, 29, 35]
    )
    agent = AnnotationAgent(EventBus(), run, storage_factory(lambda: db_session), novel_id=novel)
    try:
        first, first_program = execution_for(agent, db_session, 11)
        result = json.loads(await first_program.execute(declaration_code("gate", "顾霜入门")))
        assert not result.get("failed"), result
        await save_and_confirm(agent, db_session, first)
        child = next(iter(agent.event_trees.nodes))
        old_case = agent.case_pool.search()[0]
        second, second_program = execution_for(agent, db_session, 29)
        rejected = json.loads(
            await second_program.execute(
                'event(el="future", title="未来", problem="能否知晓后事", summary="后事", '
                'event_type="行动", status="ongoing", evidence=1, from_chapter_id=11, to_chapter_id=35)'
            )
        )
        assert rejected.get("failed"), rejected
        code = (
            f"claim_case(case_id={old_case['case_id']!r})\n"
            'event(el="journey", title="入门后的调查", problem="能否查明", summary="顾霜入门后继续调查", '
            'event_type="行动", status="ongoing", evidence=1, from_chapter_id=11, to_chapter_id=29)\n'
            'page = search_events(query="入门后的调查")\n'
            'parent = page["events"][0]["event_id"]\n'
            f"read_event(node_id={child!r})\n"
            f'write_link(source_id=parent, target_id={child!r}, kind="contains", reason="入门属于调查过程", evidence=1)'
            f"\nsubmit_case(case_id={old_case['case_id']!r})"
        )
        result = json.loads(await second_program.execute(code))
        assert not result.get("failed"), result
        await save_and_confirm(agent, db_session, second)
        parent = db_session.scalar(select(CompleteEvent).where(CompleteEvent.producer_agent_id == second.invocation_id))
        assert (parent.from_chapter_id, parent.to_chapter_id) == (11, 29)
        query = EventTreeQuery(storage_for(db_session), run)
        assert [item["event_id"] for item in query.fetch()["events"]] == [parent.event_id]
        assert query.detail(parent.event_id)["direct_children"][0]["event_id"] == child
        assert query.chapter_detail(11, child)["event_id"] == child
        cases = {item["case_id"]: item for item in agent.case_pool.search()}
        assert cases[old_case["case_id"]]["submitted"] is True
        assert len(cases) == 2
        assert parent.event_id in next(item["description"] for item in cases.values() if not item["submitted"])
    finally:
        agent.close()
