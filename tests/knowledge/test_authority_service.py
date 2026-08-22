"""章节级图 authority 合同测试"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select

from src.agents.annotation.schema import ResolvedCase
from src.knowledge.authority import KnowledgeGraphAuthorityService
from src.storage.models import GraphRelation
from tests.support.chapter_annotation_helpers import (
    character_fact,
    create_run_with_chunks,
    identity_relation_output,
    persist_chapter_annotation,
    relation_fact,
)


def _persist_authority_chapter(
    session,
    *,
    run_id: str,
    chapter_id: int,
    characters: list[dict[str, Any]] | None = None,
    relations: list[dict[str, Any]] | None = None,
    resolved_cases: list[Any] | None = None,
) -> None:
    """2026-08-19 用于为 authority 视图写入章节图数据"""
    persist_chapter_annotation(
        session,
        run_id=run_id,
        chapter_id=chapter_id,
        characters=characters,
        relations=relations,
        resolved_cases=resolved_cases,
    )


def test_authority_views_project_chapter_history_and_graph_changes(db_session) -> None:
    """2026-08-07 用于验证 authority 从章节快照输出实体关系和变化合同"""
    _novel_id, run_id = create_run_with_chunks(
        db_session,
        texts=["林渡与顾霜并肩迎敌"],
        title="章节图 authority",
    )
    _persist_authority_chapter(
        db_session,
        run_id=run_id,
        chapter_id=1,
        characters=[
            character_fact(chunk_id=1, name="林渡", action="迎敌", role_function="主体"),
            character_fact(chunk_id=1, name="顾霜", action="协助", role_function="帮助者"),
        ],
        relations=[
            relation_fact(
                chunk_id=1,
                from_name="林渡",
                to_name="顾霜",
                relation_type="盟友",
            )
        ],
    )
    db_session.commit()

    service = KnowledgeGraphAuthorityService.from_session(db_session)
    level1 = service.build_level1_snapshot(run_id)
    timeline = service.build_timeline_view(run_id)
    graph_view = service.build_graph_view(run_id)
    export_view = service.build_export_view(run_id)
    report = service.build_graph_report(run_id)

    assert {row.name for row in level1.canonical_entities} == {"林渡", "顾霜"}
    assert [(row.from_name, row.to_name, row.source) for row in level1.confirmed_relations] == [
        ("林渡", "顾霜", "relation_states")
    ]
    assert {row.change_kind for row in timeline.graph_changes} == {"state", "relation"}
    assert all(row.fact_id and row.chapter_id == 1 for row in timeline.graph_changes)
    assert all(row.changes for row in graph_view.graph_changes)
    assert {row.name for row in graph_view.participant_states} == {"林渡", "顾霜"}
    assert export_view.current_relations[0].relation_id
    assert export_view.current_relations[0].source == "relation_states"
    assert report.summary.node_count == 2
    assert report.summary.edge_count == 1


def test_authority_keeps_relation_change_history_after_break(db_session) -> None:
    """2026-08-07 用于验证当前关系消失后 authority 仍保留章节关系变化历史"""
    _novel_id, run_id = create_run_with_chunks(
        db_session,
        texts=["林渡与顾霜结盟", "两人分道扬镳"],
        chapter_ids=[1, 2],
        title="authority 关系历史",
    )
    _persist_authority_chapter(
        db_session,
        run_id=run_id,
        chapter_id=1,
        characters=[
            character_fact(chunk_id=1, name="林渡", action="结盟"),
            character_fact(chunk_id=1, name="顾霜", action="结盟"),
        ],
        relations=[
            relation_fact(
                chunk_id=1,
                from_name="林渡",
                to_name="顾霜",
                relation_type="盟友",
            )
        ],
    )
    db_session.commit()
    relation_id = db_session.execute(
        select(GraphRelation.relation_id).where(GraphRelation.run_id == run_id)
    ).scalar_one()
    _persist_authority_chapter(
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
                target_ref={"kind": "relation_change", "chunk_id": 2},
                from_entity="林渡",
                to_entity="顾霜",
                relation_type="盟友",
                change_kind="break",
            )
        ],
    )
    db_session.commit()

    graph_view = KnowledgeGraphAuthorityService.from_session(db_session).build_graph_view(run_id)
    export_view = KnowledgeGraphAuthorityService.from_session(db_session).build_export_view(run_id)

    assert graph_view.confirmed_relations == []
    relation_changes = [row for row in graph_view.graph_changes if row.change_kind == "relation"]
    assert [(row.chapter_id, row.relation_id) for row in relation_changes] == [
        (2, relation_id),
        (1, relation_id),
    ]
    assert relation_changes[0].changes[0]["change_kind"] == "break"
    assert [(row.relation_id, row.is_active) for row in export_view.current_relations] == [(relation_id, False)]


def test_authority_merges_same_character_aliases_in_views(db_session) -> None:
    """2026-08-09 用于验证同一人物关系在 authority 视图中归并别名实体"""
    _novel_id, run_id = create_run_with_chunks(
        db_session,
        texts=["伯安与猴子同游"],
        title="authority 消歧合并",
    )
    _persist_authority_chapter(
        db_session,
        run_id=run_id,
        chapter_id=1,
        characters=[
            character_fact(chunk_id=1, name="伯安", action="同游"),
            character_fact(chunk_id=1, name="贺重明", action="同游"),
            character_fact(chunk_id=1, name="猴子", action="同游"),
            character_fact(chunk_id=1, name="侯飞白", action="同游"),
        ],
        relations=[
            relation_fact(
                chunk_id=1,
                from_name="伯安",
                to_name="猴子",
                relation_type="友情",
            ),
            identity_relation_output(subject_name="伯安", object_name="贺重明", effective_chapter_id=1),
            identity_relation_output(subject_name="猴子", object_name="侯飞白", effective_chapter_id=1),
        ],
    )
    db_session.commit()

    service = KnowledgeGraphAuthorityService.from_session(db_session)
    level1 = service.build_level1_snapshot(run_id)
    graph_view = service.build_graph_view(run_id)
    representative = service.build_representative_graph_view(run_id)

    canonical_names = {row.name for row in level1.canonical_entities}
    assert canonical_names == {"伯安", "猴子"}
    by_name = {row.name: row for row in level1.canonical_entities}
    assert by_name["伯安"].aliases == ["贺重明"]
    assert by_name["猴子"].aliases == ["侯飞白"]
    assert [(row.from_name, row.to_name, row.relation_type) for row in level1.confirmed_relations] == [
        ("伯安", "猴子", "友情")
    ]
    assert {row.name for row in graph_view.participant_states} == {"伯安", "猴子"}
    assert {row.name for row in representative.canonical_entities} == {"伯安", "猴子"}
