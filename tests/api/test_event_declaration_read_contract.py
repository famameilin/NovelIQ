"标注正式事件无报告读取契约"

from src.event_trees.read.organization import EventTreeQuery
from tests.support.chapter_annotation_helpers import create_run_with_chunks
from tests.support.event_tree_fixtures import add_annotation_source, add_declaration, first_paragraph
from tests.support.storage_fixtures import storage_for


def test_annotation_event_is_formal_and_readable_without_diagnosis(db_session):
    _, run = create_run_with_chunks(db_session, texts=["开始营救。", "继续营救。"], chapter_ids=[1, 2])
    events = []
    for chapter in (1, 2):
        record, _ = add_annotation_source(db_session, run, chapter)
        events.append(
            add_declaration(
                db_session, record_id=record, paragraph=first_paragraph(db_session, run, chapter_id=chapter)
            )
        )
    query = EventTreeQuery(storage_for(db_session), run)
    data = query.fetch(limit=1)
    assert data["organization_status"] == "pending_diagnosis"
    assert data["counts"]["all_events"] == 2 and len(data["events"]) == 1
    second = query.fetch(cursor=data["next_cursor"], limit=1)
    assert second["events"][0]["event_id"] == events[1]
    assert second["next_cursor"] is None
    for chapter, event_id in enumerate(events, start=1):
        detail = query.chapter_detail(chapter, event_id)
        assert detail["event_id"] == event_id and detail["from"] == detail["to"] == chapter
        assert query.detail(event_id)["evidence"] == detail["evidence"]
