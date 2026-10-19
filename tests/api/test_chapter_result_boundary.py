"""章节快照沿正式保存链保留自身正文、身份和真实顺序"""

import pytest
from sqlalchemy import select

from src.event_trees.organization import OrganizationEvidence
from src.event_trees.read.forest import EventForestQuery
from src.event_trees.read.organization import EventTreeQuery
from src.fact_graph.read.references import EntityReferenceProjection
from src.storage.models import Chapter
from tests.support.chapter_annotation_helpers import (
    character_fact,
    create_run_with_chunks,
    persist_chapter_annotation,
    relation_fact,
)
from tests.support.event_tree_fixtures import (
    add_annotation_source,
    add_declaration,
    close_structure,
    first_paragraph,
    identity_every_declaration,
    publish_draft,
)
from tests.support.run_records import set_run_status
from tests.support.storage_fixtures import storage_for, task_for_run


def test_early_chapter_keeps_own_body_and_identity_with_empty_chapter_between(db_session, api_client):
    novel, run = create_run_with_chunks(
        db_session, texts=["阿青寻找伙伴。", "刘青确认了伙伴下落。"], chapter_ids=[11, 35]
    )
    first = db_session.scalar(select(Chapter).where(Chapter.run_id == run, Chapter.chapter_id == 11))
    first.sequence = 1
    later = db_session.scalar(select(Chapter).where(Chapter.run_id == run, Chapter.chapter_id == 35))
    later.sequence = 3
    db_session.flush()
    db_session.add(
        Chapter(
            run_id=run,
            chapter_id=24,
            sequence=2,
            title="卷间",
            display_title="卷间",
            level="volume",
            start_pos=8,
            end_pos=8,
        )
    )
    db_session.commit()
    persist_chapter_annotation(
        db_session,
        run_id=run,
        chapter_id=11,
        characters=[character_fact(chapter_id=11, name="阿青", action="寻找伙伴")],
    )
    persist_chapter_annotation(
        db_session,
        run_id=run,
        chapter_id=35,
        characters=[character_fact(chapter_id=35, name="刘青", action="确认下落")],
        relations=[
            relation_fact(
                chapter_id=35, from_name="阿青", to_name="刘青", relation_type="同一人物"
            )
        ],
        entity_attributes={(35, "刘青"): {"representative": True}},
    )
    declarations = []
    for chapter, summary in ((11,"本章只知寻找伙伴"),(35,"本章确认伙伴下落")):
        record, _ = add_annotation_source(db_session, run, chapter, role="event")
        declarations.append(
            add_declaration(
                db_session,
                record_id=record,
                paragraph=first_paragraph(db_session, run, chapter_id=chapter),
                summary=summary,
                participants=(("阿青", "主体"),),
            )
        )
    draft, _ = identity_every_declaration(db_session, run, groups=[declarations])
    whole_event = next(iter(draft.events))
    independent = draft.event(
        key="全书归纳",
        title="全书调查",
        problem="寻找的整体结果",
        summary="只属于全书的独立事件正文",
        event_type="调查",
        status="resolved",
        reason="原文支持独立的整体问题",
        compared_event_ids=[whole_event],
        evidence=[OrganizationEvidence(paragraph_id=0)],
    )["event_id"]
    close_structure(db_session, draft, evidence_paragraph_id=0)
    publish_draft(db_session, run, draft)
    set_run_status(db_session, run, "completed")
    db_session.commit()
    storage = storage_for(db_session)
    forest = EventForestQuery(storage)
    early = forest.fetch_snapshot(run, chapter_id=11)
    latest = forest.fetch_snapshot(run, chapter_id=35)
    assert early.chapter_order == 1 and latest.chapter_order == 3
    assert forest.fetch_snapshot(run, chapter_id=24) is None
    assert [node.declaration_id for node in early.event_nodes] == declarations[:1]
    assert [node.description for node in latest.event_nodes] == ["本章只知寻找伙伴", "本章确认伙伴下落"]
    assert all(node.event_id != independent for node in latest.event_nodes)
    query = EventTreeQuery(storage, run)
    assert query.detail(independent)["summary"] == "只属于全书的独立事件正文"
    participants = EntityReferenceProjection.load(storage, run).participants(
        early.event_nodes[0].participants
    )
    assert participants[0]["entity"]["name"] == "刘青"
    detail = query.chapter_detail(11, declarations[0])
    assert detail["participants"][0]["entity"]["name"] == "阿青"
    assert detail["summary"] == early.event_nodes[0].description
    response = api_client.get(
        f"/api/novels/{novel}/event-forest/chapters/11/nodes/{declarations[0]}",
        params={"task_id": task_for_run(run, db_session)},
    )
    assert response.status_code == 200 and response.json() == detail
    with pytest.raises(LookupError):
        query.chapter_detail(11, declarations[1])
