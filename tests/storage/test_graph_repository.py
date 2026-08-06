"""数据库图事实读侧仓储测试"""

from __future__ import annotations

from src.storage.repositories import GraphRepository
from tests.support.chapter_annotation_helpers import (
    character_fact,
    create_run_with_chunks,
    persist_chapter_annotation,
    relation_fact,
)


def _seed_relation_graph(db_session, *, close_relation: bool = False) -> str:
    """2026-08-06 用于通过正式章节标注直接建立数据库关系图"""
    texts = ["林渡与顾霜并肩迎敌", "两人此后分道扬镳"] if close_relation else ["林渡与顾霜并肩迎敌"]
    _novel_id, run_id = create_run_with_chunks(
        db_session,
        texts=texts,
        chapter_ids=[1] * len(texts),
        title="数据库图读侧",
    )
    relations = [
        relation_fact(
            chunk_id=0,
            from_name="林渡",
            to_name="顾霜",
            relation_type="盟友",
        )
    ]
    if close_relation:
        relations.append(
            relation_fact(
                chunk_id=1,
                from_name="林渡",
                to_name="顾霜",
                relation_type="盟友",
                change_kind="break",
            )
        )
    persist_chapter_annotation(
        db_session,
        run_id=run_id,
        chapter_id=1,
        characters=[
            character_fact(chunk_id=0, name="林渡", action="迎敌"),
            character_fact(chunk_id=0, name="顾霜", action="迎敌"),
        ],
        relations=relations,
    )
    return run_id


def test_graph_repository_derives_relations_and_participants_from_graph_facts(db_session) -> None:
    """2026-08-05 用于验证数据库图读侧统一从通用事实生成实体关系与参与者"""
    run_id = _seed_relation_graph(db_session)
    graph_repo = GraphRepository(db_session)

    events = graph_repo.fetch_relation_events(run_id)
    current = graph_repo.fetch_current_relations(run_id)
    participants = graph_repo.fetch_participant_entities(run_id)

    assert [(row.from_name, row.to_name, row.relation_type, row.change_type) for row in events] == [
        ("林渡", "顾霜", "盟友", "新建")
    ]
    assert len(current) == 1
    assert current[0].support_count == 1
    assert current[0].is_active is True
    assert {row.name for row in participants} == {"林渡", "顾霜"}
    assert {row.current_degree for row in participants} == {1}


def test_graph_repository_keeps_history_when_latest_relation_fact_breaks_edge(db_session) -> None:
    """2026-08-05 用于验证断裂事实关闭当前关系但完整保留关系历史"""
    run_id = _seed_relation_graph(db_session, close_relation=True)
    graph_repo = GraphRepository(db_session)

    assert graph_repo.fetch_current_relations(run_id, active_only=True) == []
    current = graph_repo.fetch_current_relations(run_id, active_only=False)
    events = graph_repo.fetch_relation_events(run_id)
    participants = graph_repo.fetch_participant_entities(run_id)

    assert len(current) == 1
    assert current[0].is_active is False
    assert current[0].change_count == 1
    assert [(row.chunk_id, row.change_type) for row in events] == [(1, "断裂"), (0, "新建")]
    assert {row.current_degree for row in participants} == {0}
    assert {row.historical_degree for row in participants} == {1}
