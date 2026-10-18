"""从程序构造器至正式事务验证事件身份、跨章版本、包含及实际过程"""

from __future__ import annotations

import json
from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import sessionmaker

from src.agents.annotation.agent import AnnotationAgent, WorkExecution
from src.agents.annotation.agent_ir import AgentAnnotation
from src.agents.annotation.agent_runtime import AgentProgramRuntime
from src.agents.annotation.ledger import AnnotationToolLedger
from src.agents.annotation.paragraphs import build_chapter_paragraph_info
from src.agents.annotation.work_tools import build_work_tools
from src.event_bus import EventBus, Message
from src.storage.models import (
    Chapter,
    Execution,
    Paragraph,
    naive_utcnow,
)
from src.work.annotation_work import WorkReceipt, annotation_work_id
from tests.support.chapter_annotation_helpers import create_run_with_chunks


def execution_for(agent, session, chapter_id):
    chapter = session.get(Chapter, {"run_id": agent.run_id, "chapter_id": chapter_id})
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
    invocation = uuid4().hex
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
    query = SimpleNamespace(chapter_orders={1: 1, 2: 2}, current_chapter_order=chapter.sequence)
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
    # 无 relationship：真实尝试 → 正式记录按依赖分层 flush（work 行已退场）
    payload = execution.receipt.payload
    attempt = (
        int(
            session.scalar(
                select(func.count())
                .select_from(Execution)
                .where(
                    Execution.run_id == agent.run_id,
                    Execution.chapter_id == payload["chapter_id"],
                    Execution.role == payload["role"],
                )
            )
            or 0
        )
        + 1
    )
    session.add(
        Execution(
            execution_id=execution.invocation_id,
            run_id=agent.run_id,
            chapter_id=payload["chapter_id"],
            role=payload["role"],
            attempt_number=attempt,
            started_at=naive_utcnow(),
            status="success",
        )
    )
    session.flush()
    identifier = agent._save(execution, session)
    session.commit()
    assert await agent.check(
        Message(
            topic="agent.check",
            source="test",
            target=agent.address,
            run_id=agent.run_id,
            work_id=execution.work_id,
            invocation_id=execution.invocation_id,
        )
    )
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
    return "event(" + ", ".join(f"{name}={value!r}" for name, value in {
        "el": key, "title": summary, "problem": summary + "能否完成", "summary": summary,
        "event_type": "行动", "status": "ongoing", "evidence": 1}.items()) + ")"


@pytest.mark.parametrize("reverse", [False, True])
async def test_same_fact_cannot_be_recreated_as_second_declaration(db_session, reverse):
    novel, run = create_run_with_chunks(db_session, texts=["入门后挡火。"])
    agent = AnnotationAgent(EventBus(), run, lambda: db_session, novel_id=novel)
    execution, runtime = execution_for(agent, db_session, 1)
    try:
        calls = [declaration_code("a", "入门"), declaration_code("b", "挡火")]
        if reverse:
            calls.reverse()
        receipt = json.loads(await runtime.execute("\n".join(calls)))
        assert not receipt.get("failed"), receipt
        rejected = json.loads(await runtime.execute(declaration_code("c", "挡火")))
        assert "duplicate_declaration" in str(rejected)
        assert len(execution.ledger.bound_payloads["events"]) == 2
        assert all(item.parent_node_id is None for item in execution.ledger.bound_payloads["events"])
        await save_and_confirm(agent, db_session, execution)
    finally:
        agent.close()


async def test_annotation_declarations_then_diagnosis_once_publication(db_session):
    from src.event_trees.read.organization import EventTreeQuery
    from src.event_trees.storage_map import run_declaration_ids, run_events, stage_chain
    from tests.support.event_tree_fixtures import close_structure, identity_every_declaration, publish_draft

    novel_id, run_id = create_run_with_chunks(db_session, texts=["顾霜寻找山门，点燃一盏灯。"])
    agent = AnnotationAgent(EventBus(), run_id, sessionmaker(bind=db_session.get_bind()), novel_id=novel_id)
    execution, runtime = execution_for(agent, db_session, 1)
    try:
        result = json.loads(await runtime.execute(declaration_code("search", "顾霜寻找山门") + "\n"
                                                 + declaration_code("lamp", "顾霜点灯") + "\nfinish()"))
        assert not result.get("failed"), result
        assert result["written_refs"][0]["ref"]["declaration_id"]
        await save_and_confirm(agent, db_session, execution)
        assert run_events(db_session, run_id) == {}
        assert EventTreeQuery(db_session, run_id).fetch()["organization_status"] == "pending_diagnosis"
        draft, _meta = identity_every_declaration(db_session, run_id)
        close_structure(db_session, draft, evidence_paragraph_id=0)
        publish_draft(db_session, run_id, draft)
        assert len(run_events(db_session, run_id)) == 2
        # 阶段链读取面：本运行的每个正式事件各有且仅有 1 个绑定声明的版本
        chains = stage_chain(db_session, list(run_events(db_session, run_id)))
        bound = [row for rows in chains.values() for row in rows if row.declaration_id is not None]
        assert len(bound) == 2
        assert len(run_declaration_ids(db_session, run_id)) == 2
        assert EventTreeQuery(db_session, run_id).fetch()["organization_status"] == "ready"
    finally:
        agent.close()
