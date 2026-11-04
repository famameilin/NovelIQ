"统一事件、章节范围与包含关系的数据库契约"

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from src.storage.ids import new_id
from src.storage.models import Base, Case, CompleteEvent, NarrativeGroup, NarrativeLink, SourceEvidence
from src.storage.repositories.case_writes import CaseWritesRepository
from tests.support.chapter_annotation_helpers import create_run_with_chunks
from tests.support.event_tree_fixtures import add_annotation_source, add_declaration, first_paragraph


@pytest.fixture
def event_case(db_session):
    _, run = create_run_with_chunks(db_session, texts=["甲入山门。", "乙跟上甲。"], chapter_ids=[11, 27])
    record, producer = add_annotation_source(db_session, run, 27)
    event_id = add_declaration(db_session, record_id=record, paragraph=first_paragraph(db_session, run, chapter_id=27))
    return run, producer, record, event_id


def test_unified_thirty_tables_and_literal_case_contract(event_case):
    assert len(Base.metadata.tables) == 30
    assert "event_declarations" not in Base.metadata.tables
    assert "event_declaration_bindings" not in Base.metadata.tables
    assert {"from", "to", "annotation_record_id"} <= set(CompleteEvent.__table__.c.keys())
    assert len(Base.metadata.tables["case"].c) == 7


@pytest.mark.parametrize("start,end", [(27, 11), (11, 99)])
def test_database_rejects_unknown_or_reversed_range(db_session, event_case, start, end):
    _, producer, record, _ = event_case
    with pytest.raises(IntegrityError), db_session.begin_nested():
        db_session.add(
            CompleteEvent(
                event_id=new_id(),
                producer_agent_id=producer,
                annotation_record_id=record,
                local_key=new_id(),
                from_chapter_id=start,
                to_chapter_id=end,
                title="父事件",
                problem="待解",
                summary="整体行动",
                event_type="行动",
                status="ongoing",
            )
        )
        db_session.flush()


def test_saved_event_body_and_range_are_immutable(db_session, event_case):
    row = db_session.get(CompleteEvent, event_case[3])
    with pytest.raises(IntegrityError), db_session.begin_nested():
        row.title = "覆盖已保存事件"
        db_session.flush()


def test_parent_range_does_not_need_to_cover_child(db_session, event_case):
    run, producer, record, child = event_case
    parent = new_id()
    parent_tree = new_id()
    db_session.add(
        NarrativeGroup(
            group_id=parent_tree,
            producer_agent_id=producer,
            kind="tree",
            title="父事件树",
            description="完整父事件树",
        )
    )
    db_session.add(
        CompleteEvent(
            event_id=parent,
            producer_agent_id=producer,
            annotation_record_id=record,
            local_key=parent,
            from_chapter_id=11,
            to_chapter_id=11,
            title="父事件",
            problem="待解",
            summary="整体行动",
            event_type="行动",
            status="ongoing",
        )
    )
    db_session.flush()
    db_session.add(NarrativeLink(
        link_id=new_id(), producer_agent_id=producer, tree_id=parent_tree,
        member_event_id=parent, position=0, reason="完整父事件树",
    ))
    db_session.flush()
    child_tree = db_session.scalar(select(NarrativeLink.tree_id).where(NarrativeLink.member_event_id == child))
    db_session.add(
        NarrativeLink(
            link_id=new_id(),
            producer_agent_id=producer,
            parent_tree_id=parent_tree,
            child_tree_id=child_tree,
            reason="独立范围的包含",
        )
    )
    db_session.flush()
    assert (
        db_session.scalar(select(NarrativeLink.parent_tree_id).where(NarrativeLink.child_tree_id == child_tree))
        == parent_tree
    )
    with pytest.raises(IntegrityError), db_session.begin_nested():
        db_session.add(
            NarrativeLink(
                link_id=new_id(),
                producer_agent_id=producer,
                parent_tree_id=child_tree,
                child_tree_id=parent_tree,
                reason="非法闭环",
            )
        )
        db_session.flush()


def test_root_cases_are_stable_and_keep_promises_after_parenting(db_session, event_case):
    run, _producer, _, child = event_case
    repo = CaseWritesRepository(run)
    child_tree = db_session.scalar(select(NarrativeLink.tree_id).where(NarrativeLink.member_event_id == child))
    rows = repo.register_unparented_trees(db_session)
    assert len(rows) == 1 and child_tree in rows[0]["description"]
    assert rows == repo.register_unparented_trees(db_session)
    assert rows[0]["case_id"] != child_tree
    assert "event_id" not in Base.metadata.tables["case"].c


def test_unparented_tree_registers_at_most_twice(db_session, event_case):
    run, producer, _, _child = event_case
    repo = CaseWritesRepository(run)
    first = repo.register_unparented_trees(db_session)
    assert len(first) == 1
    first_row = db_session.get(Case, first[0]["case_id"])
    first_row.status = "resolved"
    first_row.promised_agent_id = producer
    db_session.flush()
    second = repo.register_unparented_trees(db_session)
    pending = [row for row in second if not row["submitted"]]
    assert len(second) == 2 and len(pending) == 1
    assert pending[0]["case_id"] != first[0]["case_id"]
    second_row = db_session.get(Case, pending[0]["case_id"])
    second_row.status = "resolved"
    second_row.promised_agent_id = producer
    db_session.flush()
    third = repo.register_unparented_trees(db_session)
    assert len(third) == 2
    assert all(row["submitted"] for row in third)


def test_unparented_empty_tree_enters_case_pool(db_session, event_case):
    run, producer, _, _child = event_case
    empty_tree = new_id()
    db_session.add(
        NarrativeGroup(
            group_id=empty_tree,
            producer_agent_id=producer,
            kind="tree",
            title="空容器",
            description="尚无成员",
        )
    )
    db_session.flush()
    rows = CaseWritesRepository(run).register_unparented_trees(db_session)
    assert any(empty_tree in row["description"] for row in rows)


def test_evidence_has_single_event_owner(event_case):
    assert "event_id" not in SourceEvidence.__table__.c
    assert "complete_event_id" in SourceEvidence.__table__.c
    assert "related_complete_event_id" in SourceEvidence.__table__.c
