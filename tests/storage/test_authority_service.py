"""章节级图 authority 合同测试"""

from __future__ import annotations

from typing import Any

from src.fact_graph.read import KnowledgeGraphAuthorityService
from src.storage.repositories import GraphRepository
from tests.support.chapter_annotation_helpers import (
    character_fact,
    commit_test_annotation,
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
) -> None:
    """为 authority 视图写入章节图数据"""
    persist_chapter_annotation(
        session,
        run_id=run_id,
        chapter_id=chapter_id,
        characters=characters,
        relations=relations,
    )


def _retract_relation(
    session,
    *,
    run_id: str,
    chapter_id: int,
    from_name: str,
    to_name: str,
    relation_type: str,
    reason: str,
) -> None:
    """关系撤回经正式 work 保存入口写图事实（不手拼旧图行）"""
    from src.agents.annotation.output_models import BoundChapterAnnotation
    from src.fact_graph.inputs import ChapterMetricsInput

    commit_test_annotation(
        session,
        run_id=run_id,
        chapter_id=chapter_id,
        annotation=BoundChapterAnnotation(
            metrics=ChapterMetricsInput(summary="关系变化", emotional_valence=0, narrative_function="转折"),
            character_observations=[],
            dialogues=[],
            events=[],
        ),
        relation_assert_ops=[
            {
                "from_entity": from_name,
                "to_entity": to_name,
                "relation_type": relation_type,
                "chapter_id": chapter_id,
                "change_kind": "retract",
                "reason": reason,
            }
        ],
    )


def _relation_id(session, run_id: str, from_name: str, to_name: str, relation_type: str) -> str:
    """按正式关系读面定位唯一关系身份（关系行的 run 从端点实体取得）"""
    rows = [
        row
        for row in GraphRepository(session).fetch_latest_relations(run_id, active_only=False)
        if row.relation_type == relation_type and {str(row.from_name), str(row.to_name)} == {from_name, to_name}
    ]
    if len(rows) != 1:
        raise ValueError(f"测试夹具未唯一定位关系: {from_name}/{to_name}/{relation_type}")
    return str(rows[0].relation_id)


def test_authority_views_project_chapter_history_and_graph_changes(db_session) -> None:
    """验证 authority 从章节快照输出实体关系和变化合同"""
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
            character_fact(chapter_id=1, name="林渡", action="迎敌", role_function="主体"),
            character_fact(chapter_id=1, name="顾霜", action="协助", role_function="帮助者"),
        ],
        relations=[
            relation_fact(
                chapter_id=1,
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
    graph_view = service.build_representative_graph_view(run_id)
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
    """验证当前关系消失后 authority 仍保留章节关系变化历史"""
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
            character_fact(chapter_id=1, name="林渡", action="结盟"),
            character_fact(chapter_id=1, name="顾霜", action="结盟"),
        ],
        relations=[
            relation_fact(
                chapter_id=1,
                from_name="林渡",
                to_name="顾霜",
                relation_type="盟友",
            )
        ],
    )
    db_session.commit()
    relation_id = _relation_id(db_session, run_id, "林渡", "顾霜", "盟友")
    _retract_relation(
        db_session,
        run_id=run_id,
        chapter_id=2,
        from_name="林渡",
        to_name="顾霜",
        relation_type="盟友",
        reason="分道扬镳",
    )
    db_session.commit()

    graph_view = KnowledgeGraphAuthorityService.from_session(db_session).build_representative_graph_view(run_id)
    export_view = KnowledgeGraphAuthorityService.from_session(db_session).build_export_view(run_id)

    assert graph_view.confirmed_relations == []
    relation_changes = [row for row in graph_view.graph_changes if row.change_kind == "relation"]
    assert [(row.chapter_id, row.relation_id) for row in relation_changes] == [
        (2, relation_id),
        (1, relation_id),
    ]
    assert relation_changes[0].changes[0]["change_kind"] == "retract"
    assert [(row.relation_id, row.is_active) for row in export_view.current_relations] == [(relation_id, False)]


def test_authority_merges_same_character_aliases_in_views(db_session) -> None:
    """验证同一人物关系在 authority 视图中归并别名实体"""
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
            character_fact(chapter_id=1, name="伯安", action="同游"),
            character_fact(chapter_id=1, name="贺重明", action="同游"),
            character_fact(chapter_id=1, name="猴子", action="同游"),
            character_fact(chapter_id=1, name="侯飞白", action="同游"),
        ],
        relations=[
            relation_fact(
                chapter_id=1,
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
    graph_view = service.build_representative_graph_view(run_id)
    representative = service.build_representative_graph_view(run_id)

    canonical_rows = level1.canonical_entities
    # 代表名由 uuid5(entity_id) 字典序选举决定，随 run 随机；representative 视图
    # 的实体取活跃非身份边的端点（原始名，不按选举折叠）。因此只断言各视图
    # 的合并语义：两个"同一人物"分量各收敛到一个名字，别名归并完整。
    assert len(canonical_rows) == 2
    for row in canonical_rows:
        assert {row.name, *row.aliases} in ({"伯安", "贺重明"}, {"猴子", "侯飞白"})
    assert [(row.relation_type,) for row in level1.confirmed_relations] == [("友情",)]
    friendship = level1.confirmed_relations[0]
    assert friendship.from_name in {"伯安", "贺重明"}
    assert friendship.to_name in {"猴子", "侯飞白"}
    for view_names in (
        {row.name for row in graph_view.participant_states},
        {row.name for row in representative.canonical_entities},
    ):
        assert len(view_names) == 2
        assert len(view_names & {"伯安", "贺重明"}) == 1
        assert len(view_names & {"猴子", "侯飞白"}) == 1
