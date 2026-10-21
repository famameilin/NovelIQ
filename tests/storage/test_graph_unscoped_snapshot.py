"""无章节归属图事实的当前状态读取测试"""

from __future__ import annotations

import json

from src.storage.repositories import GraphRepository
from tests.support.chapter_annotation_helpers import (
    create_run_with_chunks,
    persist_chapter_annotation,
    relation_fact,
)


def _save_unscoped_facts(session, run_id: str) -> None:
    """按诊断案例的无章节归属贡献经 FactWriter 写入实体与关系"""
    from src.fact_graph.contributions import FactContribution
    from src.fact_graph.graph import FactGraph
    from src.fact_graph.inputs import BoundRelationInput, EntityInput
    from src.storage import new_id
    from src.storage.models import Agent
    from src.storage.repositories.fact_writes import FactWriter

    author = new_id()
    session.add(Agent(id=author, run_id=run_id, type="case", status="running"))
    session.flush()

    graph = FactGraph(run_scope=run_id)
    entities = [
        EntityInput(name="无章角色", entity_type="character", tags=["书级"]),
        EntityInput(name="无章地点", entity_type="location"),
    ]
    assigned = graph.register_entities(entities)
    graph.begin(author, 0, "case")
    with graph.author(author):
        graph.record_entity_ops(entities, chapter_id=0)
        graph.record_relation_asserts(
            [BoundRelationInput(from_entity="无章角色", to_entity="无章地点", relation_type="位于")],
            chapter_id=0,
        )
    facts = graph.drain_ops(author)
    name_to_key = {display: key for key, display in graph.entity_names.items()}
    for op in facts["relation_assert_ops"]:
        op["from_entity"] = name_to_key[str(op["from_entity"])]
        op["to_entity"] = name_to_key[str(op["to_entity"])]
    facts["entities"] = {
        entity_id: {"entity_id": entity_id, "name": entity.name, "entity_type": str(entity.entity_type)}
        for entity, (entity_id, _name) in zip(entities, assigned, strict=True)
    }
    graph.reference_entities(author, list(facts["entities"].values()))
    frozen = FactContribution(run_id, author, None, (), json.dumps(facts, ensure_ascii=False), "[]")
    FactWriter(run_id).save_work(session, graph.prepare_save(frozen), "")
    session.flush()


def test_latest_graph_state_contains_unscoped_facts_but_default_snapshot_excludes_them(db_session) -> None:
    """无章节归属的正式图事实只进入当前全书状态，默认章节快照不包含它们"""
    _novel_id, run_id = create_run_with_chunks(
        db_session,
        texts=["林渡与顾霜结盟。"],
        chapter_ids=[1],
        title="无章节归属图事实",
    )
    persist_chapter_annotation(
        db_session,
        run_id=run_id,
        chapter_id=1,
        relations=[relation_fact(chapter_id=1, from_name="林渡", to_name="顾霜", relation_type="盟友")],
    )
    _save_unscoped_facts(db_session, run_id)
    db_session.commit()

    repository = GraphRepository(db_session)
    boundary = repository.resolve_chapter_boundary(run_id, chapter_id=1)
    assert boundary is not None

    latest_entities = {row.name: row for row in repository.fetch_latest_entity_rows(run_id)}
    assert {"无章角色", "无章地点"} <= set(latest_entities)
    assert latest_entities["无章角色"].state_chapter_id is None
    assert latest_entities["无章角色"].first_seen_chapter is None
    assert latest_entities["无章角色"].last_seen_chapter is None

    latest_relations = repository.fetch_latest_relations(run_id)
    unscoped_relation = next(
        row
        for row in latest_relations
        if (row.from_name, row.to_name, row.relation_type) == ("无章角色", "无章地点", "位于")
    )
    assert unscoped_relation.chapter_id is None
    assert unscoped_relation.first_seen_chapter is None
    assert unscoped_relation.last_seen_chapter is None

    assert {row.name for row in repository.fetch_entity_snapshots(boundary)} == {"林渡", "顾霜"}
    scoped_relations = repository.fetch_relation_snapshots(boundary)
    assert len(scoped_relations) == 1
    assert {scoped_relations[0].from_name, scoped_relations[0].to_name} == {"林渡", "顾霜"}
    assert scoped_relations[0].relation_type == "盟友"
