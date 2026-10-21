"统一事件树的分页、详情、章节投影与原文读取"

import pytest
from sqlalchemy import delete

from src.event_trees.organization import OrganizationEvidence
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
    for child in children:
        draft.contain(
            parent_event_id=parent,
            child_event_id=child,
            reason="整体行动包含子事件",
            evidence=[OrganizationEvidence(paragraph_id=0)],
        )
    save_case_session_rows(db_session, run, draft.producer_agent_id, draft)
    set_run_status(db_session, run, "completed")
    db_session.commit()
    return novel, run, children, parent


def test_pending_report_still_exposes_formal_tree(api_client, db_session, tree_case):
    novel, run, children, parent = tree_case
    response = api_client.get(f"/api/novels/{novel}/event-trees", params={"task_id": task_for_run(run, db_session)})
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["organization_status"] == "pending_diagnosis"
    assert [event["event_id"] for event in data["events"]] == [parent]
    assert data["counts"]["all_events"] == 3 and data["counts"]["child_events"] == 2
    assert "declarations" not in data["counts"]
    assert data["events"][0]["from"] == data["events"][0]["to"] == 11


def test_detail_uses_own_evidence_and_participants(db_session, tree_case):
    _, run, children, parent = tree_case
    query = EventTreeQuery(storage_for(db_session), run)
    detail = query.detail(parent)
    assert detail["summary"] == "独立父事件概要"
    assert detail["characters"] == []
    assert len(detail["evidence"]) == 1
    assert {row["event_id"] for row in detail["direct_children"]} == set(children)
    assert query.detail(children[1])["ancestry"] == [parent]


def test_chapter_projection_keeps_roots_when_parent_is_external(db_session, tree_case):
    _, run, children, parent = tree_case
    forest = EventForestQuery(storage_for(db_session))
    early = forest.fetch_snapshot(run, chapter_id=11)
    latest = forest.fetch_snapshot(run, chapter_id=29)
    assert [node.event_id for node in early.event_nodes] == children[:1]
    assert {node.event_id for node in latest.event_nodes} == set(children)
    assert all(node.parent_event_id is None for node in latest.event_nodes)
    assert parent not in {node.event_id for node in latest.event_nodes}


def test_chapter_detail_uses_event_id_and_own_range(api_client, db_session, tree_case):
    novel, run, children, parent = tree_case
    params = {"task_id": task_for_run(run, db_session)}
    response = api_client.get(f"/api/novels/{novel}/event-forest/chapters/29/nodes/{children[1]}", params=params)
    assert response.status_code == 200
    assert response.json()["event_id"] == children[1]
    assert response.json()["from"] == response.json()["to"] == 29
    assert (
        api_client.get(f"/api/novels/{novel}/event-forest/chapters/11/nodes/{parent}", params=params).status_code == 404
    )


def test_source_is_available_before_report(api_client, db_session, tree_case):
    novel, run, children, _ = tree_case
    response = api_client.get(
        f"/api/novels/{novel}/event-trees/nodes/{children[1]}/source", params={"task_id": task_for_run(run, db_session)}
    )
    assert response.status_code == 200, response.text
    assert response.json()["chapter_id"] == 29
    assert response.json()["evidence"][0]["paragraph_id"] == 1


def test_unknown_event_and_wrong_chapter_rejected(db_session, tree_case):
    _, run, children, _ = tree_case
    query = EventTreeQuery(storage_for(db_session), run)
    with pytest.raises(LookupError):
        query.detail("missing")
    with pytest.raises(LookupError):
        query.chapter_detail(11, children[1])


def test_evidence_corruption_is_rejected_without_read_repair(db_session, tree_case):
    _, run, _, parent = tree_case
    db_session.execute(delete(SourceEvidence).where(SourceEvidence.complete_event_id == parent))
    db_session.commit()
    with pytest.raises(ValueError, match="证据"):
        EventTreeQuery(storage_for(db_session), run).fetch()


def test_export_contains_direct_events_and_ranges(db_session, tree_case):
    _, run, children, parent = tree_case
    data = EventTreeQuery(storage_for(db_session), run).export()
    assert {item["event_id"] for item in data["complete_events"]} == set(children) | {parent}
    assert all("from" in item and "to" in item for item in data["complete_events"])
    assert "declaration_bindings" not in data and "declarations" not in data
