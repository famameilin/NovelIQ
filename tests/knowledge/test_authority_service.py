"""数据库图 authority 现行合同测试"""

from __future__ import annotations

from sqlalchemy import delete

from src.knowledge.authority import KnowledgeGraphAuthorityService
from src.storage.models import GraphEntityParticipant, GraphRelationCurrent, GraphRelationEvent
from tests.support.chapter_annotation_helpers import (
    character_fact,
    create_run_with_chunks,
    persist_chapter_annotation,
    relation_fact,
)


def _seed_authority_graph(db_session) -> str:
    """2026-08-05 用于通过章节事实建立 authority 测试数据库图"""
    _novel_id, run_id = create_run_with_chunks(
        db_session,
        texts=["林渡与顾霜并肩迎敌"],
        title="数据库图 authority",
    )
    persist_chapter_annotation(
        db_session,
        run_id=run_id,
        chapter_id=1,
        characters=[
            character_fact(chunk_id=0, name="林渡", action="迎敌", role_function="主体"),
            character_fact(chunk_id=0, name="顾霜", action="协助", role_function="助手"),
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
    return run_id


def test_authority_views_expose_graph_fact_contracts_for_each_consumer(db_session) -> None:
    """2026-08-05 用于验证各 authority 视图共享同一数据库图事实来源"""
    run_id = _seed_authority_graph(db_session)
    service = KnowledgeGraphAuthorityService.from_session(db_session)

    level1 = service.build_level1_snapshot(run_id)
    timeline = service.build_timeline_view(run_id)
    graph_view = service.build_graph_view(run_id)
    export_view = service.build_export_view(run_id)
    report = service.build_graph_report(run_id)

    assert {row.name for row in level1.canonical_entities} == {"林渡", "顾霜"}
    assert [(row.from_name, row.to_name, row.source) for row in level1.confirmed_relations] == [
        ("林渡", "顾霜", "graph_facts")
    ]
    assert [(row.chunk_id, row.source) for row in timeline.relation_events] == [(0, "graph_facts")]
    assert {row.name for row in graph_view.participant_states} == {"林渡", "顾霜"}
    assert {row.source for row in graph_view.participant_states} == {"graph_facts"}
    assert export_view.current_relations[0].source == "graph_facts"
    assert report.summary.node_count == 2
    assert report.summary.edge_count == 1


def test_authority_relation_reads_do_not_depend_on_retained_projection_rows(db_session) -> None:
    """2026-08-05 用于验证 retained 关系投影清空后 authority 仍从 graph_facts 读取"""
    run_id = _seed_authority_graph(db_session)
    for model in (GraphEntityParticipant, GraphRelationCurrent, GraphRelationEvent):
        db_session.execute(delete(model).where(model.run_id == run_id))
    db_session.commit()

    graph_view = KnowledgeGraphAuthorityService.from_session(db_session).build_graph_view(run_id)

    assert [(row.from_name, row.to_name, row.relation_type) for row in graph_view.confirmed_relations] == [
        ("林渡", "顾霜", "盟友")
    ]
    assert [(row.chunk_id, row.change_type) for row in graph_view.relation_events] == [(0, "新建")]
    assert {row.name for row in graph_view.participant_states} == {"林渡", "顾霜"}
