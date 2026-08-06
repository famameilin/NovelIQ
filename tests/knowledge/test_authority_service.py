"""数据库图 authority 现行合同测试"""

from __future__ import annotations

from sqlalchemy import delete

from src.knowledge.authority import KnowledgeGraphAuthorityService
from src.storage.models import (
    ChapterAnnotationRecord,
    GraphEntityParticipant,
    GraphRelationCurrent,
    GraphRelationEvent,
)
from src.storage.repositories.graph import persist_completion_graph
from tests.support.chapter_annotation_helpers import (
    character_fact,
    create_run_with_chunks,
    identity_relation_output,
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


def test_authority_relation_reads_do_not_depend_on_derived_relation_rows(db_session) -> None:
    """2026-08-06 用于验证关系派生表清空后 authority 仍从 graph_facts 读取"""
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


def test_representative_authority_view_projects_edges_without_changing_raw_graph(db_session) -> None:
    """2026-08-06 用于验证诊断视图解析常用节点而原始图保留全部称谓节点"""
    _novel_id, run_id = create_run_with_chunks(
        db_session,
        texts=["霜姐即顾霜，并与林渡结盟"],
        title="常用节点读侧",
    )
    annotation_id = persist_chapter_annotation(
        db_session,
        run_id=run_id,
        chapter_id=1,
        characters=[
            character_fact(chunk_id=0, name="霜姐", action="与林渡结盟"),
            character_fact(chunk_id=0, name="顾霜", action="身份揭示"),
            character_fact(chunk_id=0, name="林渡", action="接受结盟"),
        ],
        relations=[
            relation_fact(
                chunk_id=0,
                from_name="霜姐",
                to_name="林渡",
                relation_type="盟友",
            )
        ],
    )
    annotation = db_session.get(ChapterAnnotationRecord, annotation_id)
    assert annotation is not None
    persist_completion_graph(
        db_session,
        annotation=annotation,
        fact_outputs=[
            identity_relation_output(
                subject_name="霜姐",
                object_name="顾霜",
                representative_endpoint="object",
            )
        ],
    )
    db_session.flush()

    service = KnowledgeGraphAuthorityService.from_session(db_session)
    raw_view = service.build_graph_view(run_id)
    representative_view = service.build_representative_graph_view(run_id)

    assert {row.name for row in raw_view.participant_states} == {"霜姐", "顾霜", "林渡"}
    assert {row.relation_type for row in raw_view.confirmed_relations} == {"同一人物", "盟友"}
    assert {row.name for row in representative_view.participant_states} == {"顾霜", "林渡"}
    assert [
        (row.from_name, row.to_name, row.relation_type)
        for row in representative_view.confirmed_relations
    ] == [("顾霜", "林渡", "盟友")]
