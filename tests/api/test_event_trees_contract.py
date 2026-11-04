"统一事件树的完整成员、详情、章节投影与原文读取"

from dataclasses import replace

import pytest
from sqlalchemy import delete

from src.event_trees.organization_models import OrganizationEvidence
from src.event_trees.read.forest import EventForestQuery
from src.event_trees.read.organization import EventTreeQuery
from src.storage.models import SourceEvidence
from src.storage.repositories.diagnosis_event_writes import save_case_session_rows
from tests.support.chapter_annotation_helpers import create_run_with_chunks
from tests.support.event_tree_fixtures import (
    add_annotation_source,
    add_declaration,
    first_paragraph,
    identity_every_declaration,
)
from tests.support.run_records import set_run_status
from tests.support.storage_fixtures import storage_for, task_for_run


@pytest.fixture
def tree_case(db_session):
    novel, run = create_run_with_chunks(db_session, texts=["甲进入山门。", "乙寻找甲。"], chapter_ids=[11, 29])
    children = []
    for chapter in (11, 29):
        record, _ = add_annotation_source(db_session, run, chapter)
        children.append(
            add_declaration(
                db_session,
                record_id=record,
                paragraph=first_paragraph(db_session, run, chapter_id=chapter),
                participants=((f"人物{chapter}", "主体"),),
            )
        )
    draft, _ = identity_every_declaration(db_session, run)
    parent = draft.event(
        key="search",
        title="寻人",
        problem="能否找到甲",
        summary="独立父事件概要",
        event_type="寻人",
        status="ongoing",
        reason="整体行动",
        from_chapter_id=11,
        to_chapter_id=11,
        evidence=[OrganizationEvidence(paragraph_id=0)],
    )["event_id"]
    parent_tree = draft.queue(
        event_ids=[parent], reason="完整父事件", evidence=[OrganizationEvidence(paragraph_id=0)]
    )
    graph = draft.queue_graph()
    trees = {parent: parent_tree, **{child: graph.event_tree[child] for child in children}}
    for child in children:
        draft.reference(
            parent_tree_id=parent_tree,
            child_tree_id=trees[child],
            reason="整体行动包含子事件",
            evidence=[OrganizationEvidence(paragraph_id=0)],
        )
    save_case_session_rows(db_session, run, draft.producer_agent_id, draft)
    set_run_status(db_session, run, "completed")
    db_session.commit()
    return novel, run, children, parent, trees


def test_pending_report_still_exposes_formal_tree(api_client, db_session, tree_case):
    novel, run, children, parent, trees = tree_case
    response = api_client.get(f"/api/novels/{novel}/event-trees", params={"task_id": task_for_run(run, db_session)})
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["organization_status"] == "pending_diagnosis"
    assert {event["event_id"] for event in data["events"]} == {parent, *children}
    assert data["event_line_ids"] == []
    assert {q["tree_id"] for q in data["queues"]} == set(trees.values())
    assert {(row["parent_tree_id"], row["child_tree_id"]) for row in data["queue_references"]} == {
        (trees[parent], trees[child]) for child in children
    }
    assert data["counts"]["all_events"] == 3 and data["counts"]["trees"] == 3
    assert data["counts"]["event_lines"] == 0 and data["counts"]["tree_references"] == 2
    assert "arcs" not in data and "event_arc_links" not in data
    assert "arcs" not in data["counts"] and "event_arc_links" not in data["counts"]
    assert "declarations" not in data["counts"]
    entry = next(row for row in data["events"] if row["event_id"] == parent)
    assert entry["from"] == entry["to"] == 11
    assert entry["problem"] == "能否找到甲"
    assert data["next_cursor"] is None


def test_tree_contains_all_descendant_levels_without_duplicate_identities(db_session, tree_case):
    _, run, children, parent, trees = tree_case
    draft, _ = identity_every_declaration(db_session, run)
    root = draft.event(
        key="journey",
        title="寻人旅程",
        problem="如何完成寻人",
        summary="在旅程中寻找甲",
        event_type="旅程",
        status="ongoing",
        reason="寻人行动属于整个旅程",
        from_chapter_id=11,
        to_chapter_id=29,
        evidence=[OrganizationEvidence(paragraph_id=0)],
    )["event_id"]
    root_tree = draft.queue(
        event_ids=[root], reason="完整旅程", evidence=[OrganizationEvidence(paragraph_id=0)]
    )
    draft.reference(
        parent_tree_id=root_tree,
        child_tree_id=trees[parent],
        reason="旅程包含寻人行动",
        evidence=[OrganizationEvidence(paragraph_id=0)],
    )
    save_case_session_rows(db_session, run, draft.producer_agent_id, draft)
    db_session.commit()
    data = EventTreeQuery(storage_for(db_session), run).fetch()
    assert data["event_line_ids"] == []
    assert {q["tree_id"] for q in data["queues"]} == {root_tree, *trees.values()}
    assert len(data["events"]) == len({event["event_id"] for event in data["events"]}) == 4
    assert len(data["queue_references"]) == 3
    assert all(row["reason"] and row["evidence"] for row in data["queue_references"])
    assert EventTreeQuery(storage_for(db_session), run).detail(children[0])["event_line_ids"] == []


def test_detail_uses_own_evidence_and_participants(db_session, tree_case):
    _, run, children, parent, _trees = tree_case
    query = EventTreeQuery(storage_for(db_session), run)
    detail = query.detail(parent)
    assert detail["summary"] == "独立父事件概要"
    assert "arcs" not in detail
    assert detail["characters"] == []
    assert len(detail["evidence"]) == 1
    assert {row["event_id"] for row in detail["direct_children"]} == set(children)
    assert query.detail(children[1])["event_line_ids"] == []


def test_chapter_projection_keeps_roots_when_parent_is_external(db_session, tree_case):
    _, run, children, parent, _trees = tree_case
    forest = EventForestQuery(storage_for(db_session))
    early = forest.fetch_snapshot(run, chapter_id=11)
    latest = forest.fetch_snapshot(run, chapter_id=29)
    assert [node.event_id for node in early.event_nodes] == children[:1]
    assert {node.event_id for node in latest.event_nodes} == set(children)
    assert all(not node.parent_event_ids for node in latest.event_nodes)
    assert parent not in {node.event_id for node in latest.event_nodes}


def test_chapter_detail_uses_event_id_and_own_range(api_client, db_session, tree_case):
    novel, run, children, parent, _trees = tree_case
    params = {"task_id": task_for_run(run, db_session)}
    response = api_client.get(f"/api/novels/{novel}/event-forest/chapters/29/nodes/{children[1]}", params=params)
    assert response.status_code == 200
    assert response.json()["event_id"] == children[1]
    assert response.json()["from"] == response.json()["to"] == 29
    assert (
        api_client.get(f"/api/novels/{novel}/event-forest/chapters/11/nodes/{parent}", params=params).status_code == 404
    )


def test_source_is_available_before_report(api_client, db_session, tree_case, monkeypatch):
    from src.api.services.results_queries.event_trees import EventTreeReadService

    def fail_projection(_service):
        raise AssertionError("原文读取不依赖人物身份投影")

    monkeypatch.setattr(EventTreeReadService, "_projection", fail_projection)
    novel, run, children, _parent, _trees = tree_case
    response = api_client.get(
        f"/api/novels/{novel}/event-trees/nodes/{children[1]}/source", params={"task_id": task_for_run(run, db_session)}
    )
    assert response.status_code == 200, response.text
    assert response.json()["chapter_id"] == 29
    assert response.json()["evidence"][0]["paragraph_id"] == 1


def test_unknown_event_and_wrong_chapter_rejected(db_session, tree_case):
    _, run, children, _parent, _trees = tree_case
    query = EventTreeQuery(storage_for(db_session), run)
    with pytest.raises(LookupError):
        query.detail("missing")
    with pytest.raises(LookupError):
        query.chapter_detail(11, children[1])


def test_evidence_corruption_is_rejected_without_read_repair(db_session, tree_case):
    _, run, _children, parent, _trees = tree_case
    db_session.execute(delete(SourceEvidence).where(SourceEvidence.complete_event_id == parent))
    db_session.commit()
    with pytest.raises(ValueError, match="证据"):
        EventTreeQuery(storage_for(db_session), run).fetch()


def test_evidence_outside_paragraph_is_rejected(db_session, tree_case, monkeypatch):
    _, run, _children, _parent, _trees = tree_case
    storage = storage_for(db_session)
    list_passages = storage.reads.text.list_passages
    monkeypatch.setattr(
        storage.reads.text,
        "list_passages",
        lambda paragraph_ids, run_id: [replace(row, text="") for row in list_passages(paragraph_ids, run_id)],
    )
    with pytest.raises(ValueError, match="证据"):
        EventTreeQuery(storage, run).fetch()


def test_export_contains_direct_events_and_ranges(db_session, tree_case):
    _, run, children, parent, _trees = tree_case
    data = EventTreeQuery(storage_for(db_session), run).export()
    assert {item["event_id"] for item in data["complete_events"]} == set(children) | {parent}
    assert all("from" in item and "to" in item for item in data["complete_events"])
    assert "declaration_bindings" not in data and "declarations" not in data
