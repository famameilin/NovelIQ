"""时间轴截点与独立事件树分页、完整事件身份及原文证据边界

夹具自足：八章真实原文与八份章级声明（第二章为伏笔根），沿正式发布链生成完整
事件与叙事线，伏笔动作按真实生产执行登记；证据坐标一律来自真实原文。
"""

from __future__ import annotations

import json
from dataclasses import dataclass

import pytest
from sqlalchemy import select

from src.event_trees.contributions import EventContribution
from src.event_trees.organization import OrganizationEvidence
from src.event_trees.read.organization import EventTreeQuery
from src.fact_graph.evidence import EvidenceParagraph
from src.metrics.queries.plotline import PlotlineQuery
from src.storage import new_id
from src.storage.models import EventForeshadowingAction
from src.storage.repositories.event_writes import EventWriter
from tests.support.chapter_annotation_helpers import create_run_with_chunks
from tests.support.event_tree_fixtures import (
    add_annotation_source,
    add_declaration,
    add_diagnosis_context,
    add_foreshadowing_action,
    close_structure,
    first_paragraph,
    identity_every_declaration,
    publish_draft,
)
from tests.support.run_records import set_run_status
from tests.support.storage_fixtures import storage_for, task_for_run


@dataclass(frozen=True)
class NarrativeScenario:
    novel_id: str
    run_id: str
    task_id: str
    session_id: str
    agent_id: str
    declarations: dict[int, str]
    events: dict[int, str]
    arcs: dict[str, str]
    actions: dict[str, str]


def _fixture(session) -> NarrativeScenario:
    novel, run = create_run_with_chunks(
        session, texts=[f"第{i}章原文" for i in range(1, 9)], chapter_ids=list(range(1, 9))
    )
    session_id, agent_id = add_diagnosis_context(session, run)
    declarations: dict[int, str] = {}
    executions: dict[int, str] = {}
    for chapter in range(1, 9):
        record_id, annotation_execution = add_annotation_source(session, run, chapter, role="event")
        executions[chapter] = annotation_execution
        declarations[chapter] = add_declaration(
            session,
            record_id=record_id,
            paragraph=first_paragraph(session, run, chapter_id=chapter),
            phrase=f"第{chapter}章原文",
            title="藏起旧信" if chapter == 2 else f"第{chapter}章行动",
            problem=f"第{chapter}章问题",
            summary="藏起旧信" if chapter == 2 else f"第{chapter}章行动",
            event_type="行动",
            is_foreshadowing_root=(chapter == 2),
            payoff_likelihood="high" if chapter == 2 else None,
        )
    session.flush()
    draft, _meta = identity_every_declaration(session, run, context=(session_id, agent_id))
    mapping = {key: item.event_id for item in draft.events.values() for key in item.declaration_ids}
    events = {chapter: mapping[declarations[chapter]] for chapter in range(1, 9)}
    close_structure(session, draft, evidence_paragraph_id=0)
    arc = draft.register_arc(
        key="mystery",
        kind="main",
        title="追寻旧信",
        objective="揭开旧事",
        role="核心问题",
        reason="信件推动调查",
        evidence=[OrganizationEvidence(paragraph_id=1, quote="第2章原文")],
    )
    for chapter in range(1, 9):
        draft.link_event_arc(
            event_id=events[chapter],
            arc_id=arc,
            role="推动调查",
            reason="行动推进信件谜题",
            evidence=[OrganizationEvidence(paragraph_id=chapter - 1)],
        )
    publish_draft(session, run, draft)
    actions = {
        "setup": add_foreshadowing_action(
            session,
            producer_agent_id=executions[2],
            source_declaration_id=declarations[2],
            target_declaration_id=declarations[2],
            paragraph=first_paragraph(session, run, chapter_id=2),
            action_type="setup",
            operation_order=1,
        )
    }
    for chapter, action in ((5, "reinforce"), (8, "payoff")):
        actions[action] = add_foreshadowing_action(
            session,
            producer_agent_id=executions[chapter],
            source_declaration_id=declarations[2],
            target_declaration_id=declarations[chapter],
            paragraph=first_paragraph(session, run, chapter_id=chapter),
            action_type=action,
            operation_order=1,
        )
    set_run_status(session, run, "completed")
    session.commit()
    return NarrativeScenario(
        novel_id=novel,
        run_id=run,
        task_id=task_for_run(run, session),
        session_id=session_id,
        agent_id=agent_id,
        declarations=declarations,
        events=events,
        arcs={"mystery": arc},
        actions=actions,
    )


def test_cutoff_windows_pagination_and_future_detail(db_session, api_client):
    scenario = _fixture(db_session)
    run = scenario.run_id
    query = PlotlineQuery(storage_for(db_session), run)
    first = api_client.get(f"/api/novels/{scenario.novel_id}/timeline", params={"task_id": scenario.task_id}).json()
    assert first["through_chapter_id"] == 1
    assert first["total"] == 0
    assert query.fetch(through_chapter_id=3)["states"][0]["state"] == "已埋设"
    assert query.fetch(through_chapter_id=6)["states"][0]["state"] == "已强化"
    last = query.fetch(through_chapter_id=8, limit=1)
    assert last["total"] == 3 and last["states"][0]["state"] == "疑似回收"
    window = query.fetch(through_chapter_id=8, window_start_chapter_id=8)
    assert window["total"] == 1 and window["states"] == last["states"]
    with pytest.raises(ValueError, match="游标"):
        query.fetch(through_chapter_id=6, cursor=last["next_cursor"])
    change = window["changes"][0]
    response = api_client.get(
        f"/api/novels/{scenario.novel_id}/timeline/changes/{change['plotline_change_id']}",
        params={"task_id": scenario.task_id, "through_chapter_id": 3},
    )
    assert response.status_code == 404 and "CHANGE_NOT_VISIBLE" in response.text
    response = api_client.get(
        f"/api/novels/{scenario.novel_id}/timeline/changes/{change['plotline_change_id']}/source",
        params={"task_id": scenario.task_id, "through_chapter_id": 8, "chapter_id": 2},
    )
    assert response.status_code == 404
    set_run_status(db_session, run, "cancelled")
    db_session.commit()
    assert (
        api_client.get(f"/api/novels/{scenario.novel_id}/timeline", params={"task_id": scenario.task_id}).status_code
        == 400
    )
    assert (
        api_client.get(f"/api/novels/{scenario.novel_id}/event-trees", params={"task_id": scenario.task_id}).status_code
        == 400
    )


def test_tree_reads_complete_event_without_process_or_search_projection(db_session):
    scenario = _fixture(db_session)
    query = EventTreeQuery(storage_for(db_session), scenario.run_id)
    overview = query.fetch()
    assert overview["counts"]["all_events"] == 8
    assert overview["counts"]["declarations"] == 8
    assert "matches" not in overview
    owner = scenario.events[2]
    assert owner != scenario.declarations[2]
    detail = query.detail(owner)
    assert detail["event_type"] == "行动"
    assert [item["arc_id"] for item in detail["arcs"]] == [scenario.arcs["mystery"]]
    assert detail["arcs"][0]["evidence"][0]["paragraph_id"] == 1
    assert detail["direct_children"] == []
    assert query.export()["counts"] == overview["counts"]
    with pytest.raises(LookupError, match="NODE_NOT_FOUND"):
        query.detail(scenario.declarations[2])
    with pytest.raises(TypeError):
        query.fetch(q="藏起旧信")


def test_tree_pages_top_events_and_keeps_all_relation_evidence(db_session, api_client):
    scenario = _fixture(db_session)
    query = EventTreeQuery(storage_for(db_session), scenario.run_id)
    cursor = None
    events, links = {}, set()
    while True:
        page = query.fetch(limit=2, cursor=cursor)
        events.update((event["event_id"], event) for event in page["events"])
        links.update((link["event_id"], link["arc_id"]) for link in page["event_arc_links"])
        assert len(page["event_arc_links"]) == 8
        assert page["counts"]["all_events"] == 8
        cursor = page["next_cursor"]
        if not cursor:
            break
    assert set(events) == set(query.events)
    assert len(links) == 8
    response = api_client.get(f"/api/novels/{scenario.novel_id}/event-trees", params={"task_id": scenario.task_id})
    assert response.status_code == 200
    assert len(response.json()["events"]) == len(query.events)
    assert response.json()["next_cursor"] is None
    with pytest.raises(ValueError, match="游标"):
        query.fetch(cursor="invalid-cursor")


def test_complete_event_evidence_and_process_source_keep_actual_identity(db_session, api_client):
    scenario = _fixture(db_session)
    query = EventTreeQuery(storage_for(db_session), scenario.run_id)
    owner = scenario.events[5]
    detail = query.detail(owner)
    assert detail["source_chapters"] == [5]
    assert detail["evidence_scope"] == "paragraph"
    assert detail["arcs"][0]["arc_id"] == scenario.arcs["mystery"]
    assert detail["arcs"][0]["reason"] == "行动推进信件谜题"
    source = api_client.get(
        f"/api/novels/{scenario.novel_id}/event-trees/nodes/{owner}/source", params={"task_id": scenario.task_id}
    )
    assert source.status_code == 200
    assert source.json()["chapter_id"] == 5
    assert "第5章原文" in source.text
    process_source = api_client.get(
        f"/api/novels/{scenario.novel_id}/event-trees/nodes/{scenario.declarations[5]}/source",
        params={"task_id": scenario.task_id, "kind": "declaration"},
    )
    assert process_source.status_code == 200
    assert process_source.json()["chapter_id"] == 5


def _future_action_case(session):
    """三章来源链：第五章声明是伏笔根，第八章声明是未来目标"""
    _novel, run = create_run_with_chunks(
        session, texts=[f"第{i}章原文" for i in range(1, 9)], chapter_ids=list(range(1, 9))
    )
    sources: dict[int, tuple[str, str]] = {}
    declarations: dict[int, str] = {}
    for chapter in (1, 5, 8):
        record_id, annotation_execution = add_annotation_source(session, run, chapter, role="event")
        sources[chapter] = (record_id, annotation_execution)
        declarations[chapter] = add_declaration(
            session,
            record_id=record_id,
            paragraph=first_paragraph(session, run, chapter_id=chapter),
            phrase=f"第{chapter}章原文",
            title=f"第{chapter}章行动",
            is_foreshadowing_root=(chapter == 5),
        )
    session.commit()
    return run, sources, declarations


@pytest.mark.parametrize("future_endpoint", ["root_event_id", "target_event_id"])
def test_action_save_rejects_future_endpoints(db_session, future_endpoint):
    run, sources, declarations = _future_action_case(db_session)
    chapter = 1 if future_endpoint == "root_event_id" else 5
    record_id, annotation_execution = sources[chapter]
    paragraph = first_paragraph(db_session, run, chapter_id=chapter)
    action = {
        "source_operation_id": "invalid-future",
        "root_event_id": declarations[5],
        "target_event_id": declarations[8] if future_endpoint == "target_event_id" else None,
        "action_type": "reinforce",
        "chapter_id": chapter,
        "operation_order": 2,
        "evidence": [
            {
                "chapter_id": chapter,
                "paragraph_id": int(paragraph.paragraph_id),
                "char_start": 0,
                "char_end": len(paragraph.text),
                "text": paragraph.text,
            }
        ],
    }
    frozen = EventContribution(
        run,
        annotation_execution,
        chapter,
        (EvidenceParagraph(chapter, int(paragraph.paragraph_id), paragraph.text, 0, len(paragraph.text)),),
        json.dumps({"nodes": {}, "connections": {}, "actions": {new_id(): action}}),
        "{}",
    )
    source_field = "source_declaration_id" if future_endpoint == "root_event_id" else "target_declaration_id"
    with pytest.raises(ValueError, match=source_field + ".*来源章晚于"):
        EventWriter(run).save_work(db_session, frozen, record_id)


def test_action_save_accepts_earlier_saved_work_endpoints(db_session):
    """跨章回收/强化：端点可指向更早章已保存 work 的声明（0.2.x 语义， 修回归）

    曾把"他 work 端点须来源 work 已有效保存"压成"必须属于当前 work"，
    第 5 章的伏笔根被第 8 章回收即误报"来源 work 未有效保存"。
    """
    run, sources, declarations = _future_action_case(db_session)
    chapter = 8
    record_id, annotation_execution = sources[chapter]
    paragraph = first_paragraph(db_session, run, chapter_id=chapter)
    action = {
        "source_operation_id": "cross-chapter-payoff",
        "root_event_id": declarations[5],
        "target_event_id": None,
        "action_type": "payoff",
        "chapter_id": chapter,
        "operation_order": 0,
        "evidence": [
            {
                "chapter_id": chapter,
                "paragraph_id": int(paragraph.paragraph_id),
                "char_start": 0,
                "char_end": len(paragraph.text),
                "text": paragraph.text,
            }
        ],
    }
    frozen = EventContribution(
        run,
        annotation_execution,
        chapter,
        (EvidenceParagraph(chapter, int(paragraph.paragraph_id), paragraph.text, 0, len(paragraph.text)),),
        json.dumps({"nodes": {}, "connections": {}, "actions": {new_id(): action}}),
        "{}",
    )
    EventWriter(run).save_work(db_session, frozen, record_id)
    stored = list(
        db_session.scalars(
            select(EventForeshadowingAction).where(
                EventForeshadowingAction.producer_agent_id == annotation_execution
            )
        )
    )
    assert [item.action_type for item in stored] == ["payoff"]
    assert stored[0].source_declaration_id == declarations[5]


def test_source_rejects_mismatched_text_hash(db_session):
    from src.fact_graph.read.source import read_evidence_source

    scenario = _fixture(db_session)
    paragraph = first_paragraph(db_session, scenario.run_id, chapter_id=2)
    evidence = [
        {
            "chapter_id": 2,
            "paragraph_id": int(paragraph.paragraph_id),
            "char_start": 0,
            "char_end": len(paragraph.text),
            "text_hash": "wrong",
        }
    ]
    with pytest.raises(ValueError, match="证据文本校验不一致"):
        read_evidence_source(storage_for(db_session), scenario.run_id, evidence)
