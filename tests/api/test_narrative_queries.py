"""新查询的任务状态、截点、窗口、搜索及证据边界"""

import json
from uuid import uuid4

import pytest
from sqlalchemy import select

from src.event_trees.contributions import EventContribution
from src.event_trees.organization import EventOrganizationDraft, OrganizationEvidence, save_organization
from src.event_trees.read.organization import EventOrganizationQuery
from src.event_trees.trees import EventTrees
from src.fact_graph.evidence import EvidenceParagraph
from src.metrics.queries.progression import ProgressionQuery
from src.storage.models import AnalysisOutput, EventNode, ForeshadowingAction
from src.storage.repositories import StatsRepository
from tests.support.chapter_annotation_helpers import create_run_with_chunks, persist_chapter_annotation
from tests.support.run_records import set_run_status


def fixture(session):
    novel, run = create_run_with_chunks(
        session, texts=[f"第{i}章原文" for i in range(1, 9)], chapter_ids=list(range(1, 9))
    )
    root = str(uuid4())
    for chapter in range(1, 9):
        persist_chapter_annotation(
            session,
            run_id=run,
            chapter_id=chapter,
            events=[
                {
                    "node_id": root if chapter == 2 else str(uuid4()),
                    "tree_id": f"tree-{chapter}",
                    "description": "藏起旧信" if chapter == 2 else f"第{chapter}章行动",
                    "evidence_paragraph_id": chapter - 1,
                    "participants": [],
                    "cause_role": "root",
                    "isforeshadowing": chapter == 2,
                    "payoff_likelihood": "high" if chapter == 2 else None,
                }
            ],
        )
    for chapter, action in [(5, "reinforce"), (8, "payoff")]:
        output = session.scalar(
            select(AnalysisOutput).where(
                AnalysisOutput.run_id == run,
                AnalysisOutput.chapter_id == chapter,
                AnalysisOutput.kind == "chapter_annotation",
            )
        )
        node = session.scalar(select(EventNode).where(EventNode.run_id == run, EventNode.chapter_id == chapter))
        session.add(
            ForeshadowingAction(
                action_id=str(uuid4()),
                run_id=run,
                root_event_id=root,
                target_event_id=node.event_id,
                action_type=action,
                chapter_id=chapter,
                chapter_order=chapter,
                source_work_id=output.work_id,
                source_operation_id=action,
                operation_order=1,
                evidence=node.evidence,
                evidence_scope="paragraph",
                annotation_id=output.output_id,
            )
        )
    draft = EventOrganizationDraft(session, run)
    all_events = draft.search_events(limit=100)["items"]
    arc = draft.register_arc(
        key="mystery",
        kind="main",
        title="追寻旧信",
        objective="揭开旧事",
        role="核心问题",
        reason="信件推动调查",
        evidence=[OrganizationEvidence(event_id=root)],
    )
    draft.assign_events(
        [item["event_id"] for item in all_events],
        arc_id=arc,
        role="推动调查",
        reason="行动推进信件谜题",
        evidence=[OrganizationEvidence(event_id=root)],
    )
    output = StatsRepository(session).insert_agent_analysis(
        run, {"narrative_organization": draft.finish().model_dump()}
    )
    save_organization(session, run, draft.finish(), output)
    set_run_status(session, run, "completed")
    session.commit()
    return novel, run, root, arc


def test_cutoff_windows_pagination_and_future_detail(db_session, api_client):
    novel, run, root, _ = fixture(db_session)
    query = ProgressionQuery(db_session, run)
    first = api_client.get(f"/api/novels/{novel}/timeline", params={"task_id": run}).json()
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
        f"/api/novels/{novel}/timeline/changes/{change['progression_change_id']}",
        params={"task_id": run, "through_chapter_id": 3},
    )
    assert response.status_code == 404 and "CHANGE_NOT_VISIBLE" in response.text
    response = api_client.get(
        f"/api/novels/{novel}/timeline/changes/{change['progression_change_id']}/source",
        params={"task_id": run, "through_chapter_id": 8, "chapter_id": 2},
    )
    assert response.status_code == 404
    set_run_status(db_session, run, "cancelled")
    db_session.commit()
    assert api_client.get(f"/api/novels/{novel}/timeline", params={"task_id": run}).status_code == 400
    assert api_client.get(f"/api/novels/{novel}/event-trees", params={"task_id": run}).status_code == 400


def test_tree_search_finds_unloaded_events_and_exports_same_identity(db_session):
    _, run, root, arc = fixture(db_session)
    query = EventOrganizationQuery(db_session, run)
    skeleton = query.fetch()
    assert skeleton["total_events"] == 8
    assert not any(node["kind"] == "event" for node in skeleton["nodes"])
    branch = query.fetch(parent_id=f"arc:{arc}", limit=1)
    assert branch["next_cursor"]
    assert any(edge["source_id"] == f"arc:{arc}" for edge in branch["edges"])
    result = query.fetch(q="藏起旧信")
    assert result["total"] == 1
    assert len(result["matches"]) == 1
    match = next(item for item in result["matches"] if item["node_id"] == f"event:{root}")
    assert match["ancestor_ids"][:2] == ["root", f"arc:{arc}"]
    detail = query.detail(f"event:{root}")
    assert detail["organization_evidence"] == [{"event_id": root, "paragraph_id": None}]
    assert detail["is_foreshadowing_root"] is True
    assert detail["foreshadowing_status"] == db_session.get(EventNode, root).foreshadowing_status
    parent_relation = next(item for item in detail["relations"] if item["kind"] == "organization")
    assert parent_relation["direction"] == "incoming"
    assert parent_relation["related_node"]["kind"] == "group"
    assert parent_relation["ancestor_ids"] == ["root", f"arc:{arc}"]
    assert query.export()["total_events"] == skeleton["total_events"]


def test_tree_expand_all_consumes_pages_and_keeps_cross_page_relations(db_session, api_client):
    novel, run, _, _ = fixture(db_session)
    query = EventOrganizationQuery(db_session, run)
    cursor = None
    nodes, edges = {}, set()
    while True:
        page = query.fetch(expand_all=True, limit=2, cursor=cursor)
        nodes.update((node["node_id"], node) for node in page["nodes"])
        edges.update((edge["source_id"], edge["target_id"], edge["kind"]) for edge in page["edges"])
        cursor = page["next_cursor"]
        if not cursor:
            break
    assert set(nodes) == set(query.nodes)
    assert sum(node["kind"] == "event" for node in nodes.values()) == 8
    assert edges == {(edge["source_id"], edge["target_id"], edge["kind"]) for edge in query.relations}
    response = api_client.get(f"/api/novels/{novel}/event-trees", params={"task_id": run, "expand_all": True})
    assert response.status_code == 200
    assert len(response.json()["nodes"]) == len(query.nodes)
    assert response.json()["next_cursor"] is None
    with pytest.raises(ValueError, match="游标"):
        query.fetch(expand_all=True, cursor=query.fetch(limit=1)["next_cursor"])
    with pytest.raises(ValueError, match="不能"):
        query.fetch(expand_all=True, q="旧信")


def test_group_evidence_belongs_to_local_events_not_whole_arc(db_session, api_client):
    novel, run, _, arc = fixture(db_session)
    query = EventOrganizationQuery(db_session, run)
    event = db_session.scalar(select(EventNode).where(EventNode.run_id == run, EventNode.chapter_id == 5))
    group_id = f"group:{arc}:{event.tree_id}"
    detail = query.detail(group_id)
    assert detail["chapter_id"] == 5
    assert detail["chapter_order"] == 5
    assert detail["evidence"] == event.evidence
    assert detail["evidence_scope"] == "paragraph"
    assert detail["anchor_paragraph_ids"] == event.anchor_paragraph_ids
    assert detail["role"] == "推动调查"
    assert detail["reason"] == "行动推进信件谜题"
    source = api_client.get(f"/api/novels/{novel}/event-trees/nodes/{group_id}/source", params={"task_id": run})
    assert source.status_code == 200
    assert source.json()["chapter_id"] == 5
    assert "第5章原文" in source.text
    outgoing = next(relation for relation in detail["relations"] if relation["direction"] == "outgoing")
    assert outgoing["related_node"]["node_id"] == f"event:{event.event_id}"
    assert outgoing["ancestor_ids"] == ["root", f"arc:{arc}", group_id]
    assert query.fetch(q="第5章行动")["total"] == 1


@pytest.mark.parametrize("future_endpoint", ["root_event_id", "target_event_id"])
def test_action_save_rejects_future_endpoints(db_session, future_endpoint):
    _, run, root, _ = fixture(db_session)
    chapter = 1 if future_endpoint == "root_event_id" else 5
    output = db_session.scalar(
        select(AnalysisOutput).where(
            AnalysisOutput.run_id == run,
            AnalysisOutput.chapter_id == chapter,
            AnalysisOutput.kind == "chapter_annotation",
        )
    )
    later = db_session.scalar(select(EventNode).where(EventNode.run_id == run, EventNode.chapter_id == 8))
    action = {
        "source_operation_id": "invalid-future",
        "root_event_id": root,
        "target_event_id": later.event_id if future_endpoint == "target_event_id" else None,
        "action_type": "reinforce",
        "chapter_id": chapter,
        "operation_order": 2,
        "evidence": [{"chapter_id": chapter, "paragraph_id": chapter - 1}],
    }
    frozen = EventContribution(
        run,
        output.work_id,
        output.invocation_id,
        chapter,
        (EvidenceParagraph(chapter, chapter - 1, f"第{chapter}章原文", 0, 5),),
        json.dumps({"nodes": {}, "connections": {}, "actions": {str(uuid4()): action}}),
        "{}",
    )
    with pytest.raises(ValueError, match=future_endpoint + ".*来源章晚于"):
        EventTrees(run).save_work(db_session, frozen, output.output_id)


def test_source_rejects_mismatched_text_hash(db_session):
    from src.fact_graph.read.source import read_evidence_source

    _, run, root, _ = fixture(db_session)
    event = db_session.get(EventNode, root)
    with pytest.raises(ValueError, match="证据文本校验不一致"):
        read_evidence_source(db_session, run, [{**event.evidence[0], "text_hash": "wrong"}])
