"""新声明契约的正式身份、阶段截点与来源审计不能退回过程归属（2026-10-16 全库 3NF 改造）

夹具自足：真实标注来源链 + 章级声明（event_declarations）直接写入；
发布走正式入口（诊断草稿 → 报告 → 完整事件/阶段 → 叙事组织）。
"""

from __future__ import annotations

import pytest
from sqlalchemy import select

from src.event_trees.read.forest import EventForestQuery
from src.event_trees.read.organization import CONTRACT_VERSION, EventTreeQuery, RunRequiresRebuildError
from src.metrics.queries.plotline import PlotlineQuery
from src.storage.models import ChapterAnnotation
from tests.support.chapter_annotation_helpers import create_run_with_chunks
from tests.support.event_tree_fixtures import (
    add_annotation_source,
    add_declaration,
    add_declaration_relation,
    add_diagnosis_context,
    add_foreshadowing_action,
    close_structure,
    first_paragraph,
    identity_every_declaration,
    publish_draft,
)
from tests.support.run_records import set_run_status

TEXTS = ["开始营救", "继续营救", "成功营救"]


def _fixture(session, *, published=True):
    novel_id, run_id = create_run_with_chunks(session, texts=TEXTS, chapter_ids=[1, 2, 3])
    session_id, execution_id = add_diagnosis_context(session, run_id)
    declarations: list[str] = []
    annotation_executions: list[str] = []
    for chapter in range(1, 4):
        record_id, annotation_execution = add_annotation_source(session, run_id, chapter, role="event")
        annotation_executions.append(annotation_execution)
        paragraph = first_paragraph(session, run_id, chapter_id=chapter)
        declarations.append(
            add_declaration(
                session,
                record_id=record_id,
                paragraph=paragraph,
                phrase=paragraph.text,
                title="营救",
                problem="能否救人",
                summary=paragraph.text,
                event_type="营救",
                status="resolved" if chapter == 3 else "ongoing",
                progress=paragraph.text,
                participants=((f"营救者{chapter}", "主体"),),
            )
        )
    session.flush()
    if not published:
        session.commit()
        return novel_id, run_id, declarations, None, annotation_executions
    draft, _meta = identity_every_declaration(
        session, run_id, groups=[declarations], context=(session_id, execution_id)
    )
    close_structure(
        session, draft, evidence_paragraph_id=int(first_paragraph(session, run_id, chapter_id=1).paragraph_id)
    )
    publish_draft(session, run_id, draft)
    event_id = next(iter(draft.events))
    add_foreshadowing_action(
        session,
        producer_execution_id=annotation_executions[0],
        source_declaration_id=declarations[0],
        paragraph=first_paragraph(session, run_id, chapter_id=1),
        action_type="setup",
    )
    set_run_status(session, run_id, "completed")
    session.commit()
    return novel_id, run_id, declarations, event_id, annotation_executions


def test_unpublished_declarations_are_sources_without_formal_event_identity(db_session):
    _, run_id, declarations, _, _ = _fixture(db_session, published=False)
    query = EventTreeQuery(db_session, run_id)
    result = query.fetch()
    assert result["organization_status"] == "pending_diagnosis" and result["events"] == []
    assert result["counts"]["declarations"] == 3
    assert "processes" not in result["counts"]
    paragraph_id = int(first_paragraph(db_session, run_id, chapter_id=1).paragraph_id)
    source = query.declaration_source(declarations[0])
    assert source and all(item["chapter_id"] == 1 for item in source)
    assert source[0]["paragraph_id"] == paragraph_id
    with pytest.raises(LookupError):
        query.detail(declarations[0])
    assert "owner_event_id" not in query.declaration_locator(declarations[0])


def test_chapter_relation_proposals_stay_audit_sources_before_publication(db_session):
    _, run_id, declarations, _, annotation_executions = _fixture(db_session, published=False)
    source, target = declarations[:2]
    annotation_execution = annotation_executions[0]
    add_declaration_relation(
        db_session,
        producer_execution_id=annotation_execution,
        source_declaration_id=source,
        target_declaration_id=target,
        paragraph=first_paragraph(db_session, run_id, chapter_id=1),
    )
    db_session.flush()
    query = EventTreeQuery(db_session, run_id)
    assert query.fetch()["relations"] == []
    exported = query.export()
    assert exported["organization_status"] == "pending_diagnosis"
    assert exported["declaration_relations"][0]["source_declaration_id"] == source


def test_one_formal_event_retains_three_stages_and_participants(db_session):
    _, run_id, declarations, event_id, _ = _fixture(db_session)
    query = EventTreeQuery(db_session, run_id)
    assert [row["event_id"] for row in query.fetch()["events"]] == [event_id]
    detail = query.detail(event_id)
    assert detail["summary"] == "成功营救" and detail["status"] == "resolved"
    assert detail["source_chapters"] == [1, 2, 3]
    exported = query.export()
    assert {
        item["entity"]["name"] for row in exported["revisions"] for item in row["participants"]
    } == {"营救者1", "营救者2", "营救者3"}
    assert "processes" not in exported and "process_structures" not in exported
    assert {row["declaration_id"] for row in exported["declaration_bindings"]} == set(declarations)
    assert len(exported["revisions"]) == 3
    assert exported["foreshadowing_actions"][0]["root_event_id"] == event_id


def test_forest_and_timeline_use_formal_event_and_preserve_reading_cutoff(db_session):
    _, run_id, declarations, event_id, _ = _fixture(db_session)
    forest = EventForestQuery(db_session)
    first = forest.fetch_snapshot(run_id, chapter_id=1)
    last = forest.fetch_snapshot(run_id, chapter_id=3)
    assert [row.event_id for row in first.event_nodes] == [event_id]
    assert first.event_nodes[0].description == "开始营救"
    assert last.event_nodes[0].description == "成功营救"
    assert declarations[0] not in first.derived_event_order
    changes = PlotlineQuery(db_session, run_id).fetch(through_chapter_id=1)["changes"]
    assert changes[0]["source_event_ids"] == [event_id]


def test_declaration_source_api_does_not_offer_process_owner_navigation(db_session, api_client):
    novel_id, run_id, declarations, event_id, _ = _fixture(db_session)
    url = f"/api/novels/{novel_id}/event-trees/nodes/{declarations[0]}/source"
    response = api_client.get(url, params={"task_id": run_id, "kind": "declaration"})
    assert response.status_code == 200
    assert response.json()["locator"]["target_kind"] == "declaration"
    assert "owner_event_id" not in response.json()["locator"]
    assert api_client.get(url, params={"task_id": run_id, "kind": "process"}).status_code == 422
    event = api_client.get(f"/api/novels/{novel_id}/event-trees/nodes/{event_id}", params={"task_id": run_id})
    assert event.status_code == 200 and event.json()["event_id"] == event_id


def test_missing_binding_and_mixed_source_contract_are_rejected(db_session):
    _, run_id, declarations, _, _ = _fixture(db_session)
    # 绑定后的新声明没有正式身份绑定：已发布运行必须拒绝缺失绑定的声明
    record_id, _execution = add_annotation_source(db_session, run_id, 3, role="metric")
    orphan = add_declaration(
        db_session,
        record_id=record_id,
        paragraph=first_paragraph(db_session, run_id, chapter_id=3),
        phrase="成功",
        title="孤儿声明",
    )
    db_session.flush()
    with pytest.raises(ValueError, match="身份绑定"):
        EventTreeQuery(db_session, run_id).fetch()
    # 混用旧契约标记的运行必须从原文重建，不接受读取层转换
    db_session.get(ChapterAnnotation, record_id).contract_version = "event-tree-2026-10-13"
    db_session.flush()
    with pytest.raises(RunRequiresRebuildError):
        EventTreeQuery(db_session, run_id).fetch()
    assert orphan not in declarations


def test_old_publication_contract_marker_is_rejected(db_session):
    _, run_id, _, _, _ = _fixture(db_session)
    from src.storage.models import DiagnosisReport, Execution

    report = db_session.scalars(
        select(DiagnosisReport)
        .join(Execution, Execution.execution_id == DiagnosisReport.session_id)
        .where(Execution.session_run_id == run_id)
    ).one()
    assert report.contract_version == CONTRACT_VERSION
    report.contract_version = "event-tree-2026-10-13"
    db_session.flush()
    with pytest.raises(RunRequiresRebuildError):
        EventTreeQuery(db_session, run_id).fetch()
