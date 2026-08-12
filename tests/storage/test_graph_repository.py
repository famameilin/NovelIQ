"""章节级图版本查询仓储测试"""

from __future__ import annotations

from sqlalchemy import select

from src.agents.annotation.schema import ResolvedCase
from src.storage.models import GraphRelation
from src.storage.repositories import GraphRepository
from tests.support.chapter_annotation_helpers import (
    character_fact,
    create_run_with_chunks,
    persist_chapter_annotation,
    relation_fact,
)


def test_graph_repository_returns_frozen_chapter_snapshots_and_changes(db_session) -> None:
    """2026-08-07 用于验证章节快照继承状态并按事实原因返回关系变化"""
    _novel_id, run_id = create_run_with_chunks(
        db_session,
        texts=["林渡与顾霜并肩迎敌", "两人此后分道扬镳"],
        chapter_ids=[1, 2],
        title="图快照查询",
    )
    persist_chapter_annotation(
        db_session,
        run_id=run_id,
        chapter_id=1,
        characters=[
            character_fact(chunk_id=0, name="林渡", action="迎敌"),
            character_fact(chunk_id=0, name="顾霜", action="迎敌"),
        ],
        relations=[
            relation_fact(
                chunk_id=0,
                from_name="林渡",
                to_name="顾霜",
                relation_type="盟友",
            )
        ],
    )
    db_session.commit()
    first_version = GraphRepository(db_session).resolve_graph_version(run_id, chapter_id=1)
    assert first_version is not None
    first_version_id = first_version.graph_version_id
    relation_id = db_session.execute(
        select(GraphRelation.relation_id).where(GraphRelation.run_id == run_id)
    ).scalar_one()
    persist_chapter_annotation(
        db_session,
        run_id=run_id,
        chapter_id=2,
        resolved_cases=[
            ResolvedCase(
                case_id="case-break",
                action="fact",
                type="relation_change",
                reason="分道扬镳",
                target_key="target-break",
                target_ref={"kind": "relation_change", "chunk_id": 1},
                from_entity="林渡",
                to_entity="顾霜",
                relation_type="盟友",
                change_kind="break",
            )
        ],
    )
    db_session.commit()
    second_version = GraphRepository(db_session).resolve_graph_version(run_id, chapter_id=2)
    assert second_version is not None
    second_version_id = second_version.graph_version_id

    repository = GraphRepository(db_session)
    first_snapshot = repository.fetch_snapshot(run_id, graph_version_id=first_version_id)
    second_snapshot = repository.fetch_snapshot(run_id, graph_version_id=second_version_id)
    changes, total = repository.fetch_changes(run_id)

    assert first_snapshot is not None
    assert second_snapshot is not None
    assert [(row.from_name, row.to_name, row.is_active) for row in first_snapshot.relations] == [
        ("林渡", "顾霜", True)
    ]
    assert second_snapshot.relations == []
    assert {(entity.name, entity.state_revision) for entity in second_snapshot.entities} == {
        ("林渡", 1),
        ("顾霜", 1),
    }
    assert total == len(changes)
    relation_changes = [row for row in changes if row.change_kind == "relation"]
    assert [(row.chapter_id, row.relation_id, row.fact_revision) for row in relation_changes] == [
        (2, relation_id, 1),
        (1, relation_id, 1),
    ]
    assert relation_changes[0].changes[0]["change_kind"] == "break"
    assert relation_changes[0].effective_chunk_id == 1


def test_graph_repository_keeps_parallel_stable_relations_for_same_entity_pair(db_session) -> None:
    """2026-08-07 用于验证同一实体对可并行保存不同关系语义"""
    _novel_id, run_id = create_run_with_chunks(
        db_session,
        texts=["林渡与顾霜既是盟友也是师徒"],
        title="并行稳定关系",
    )
    persist_chapter_annotation(
        db_session,
        run_id=run_id,
        chapter_id=1,
        characters=[
            character_fact(chunk_id=0, name="林渡", action="授艺"),
            character_fact(chunk_id=0, name="顾霜", action="学习"),
        ],
        relations=[
            relation_fact(
                chunk_id=0,
                from_name="林渡",
                to_name="顾霜",
                relation_type="盟友",
            ),
            relation_fact(
                chunk_id=0,
                from_name="林渡",
                to_name="顾霜",
                relation_type="师徒",
            ),
        ],
    )
    db_session.commit()

    snapshot = GraphRepository(db_session).fetch_snapshot(run_id, chapter_id=1)

    assert snapshot is not None
    assert len({row.relation_id for row in snapshot.relations}) == 2
    assert {row.relation_type for row in snapshot.relations} == {"盟友", "师徒"}
    assert all(row.relation_revision == 1 for row in snapshot.relations)
