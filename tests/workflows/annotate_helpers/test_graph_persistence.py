"""章节事实数据库图持久化测试"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select

from src.knowledge.graph import search_fact_graph
from src.storage.models import (
    ChapterAnnotationRecord,
    GraphEntity,
    GraphEntityParticipant,
    GraphFact,
    GraphFactSource,
    GraphRelationCurrent,
    GraphRelationEvent,
)
from src.storage.repositories.graph import GraphRepository, persist_completion_graph, stable_annotation_fact_id
from tests.support.chapter_annotation_helpers import (
    character_fact,
    create_run_with_chunks,
    identity_relation_output,
    persist_chapter_annotation,
    relation_fact,
)


def test_annotation_fact_id_is_deterministic() -> None:
    """2026-08-05 用于验证 annotation_id 与 payload 路径稳定生成同一图节点键"""
    first = stable_annotation_fact_id("annotation-1", "relations/0")
    second = stable_annotation_fact_id("annotation-1", "relations/0")
    other = stable_annotation_fact_id("annotation-1", "relations/1")
    assert first == second
    assert first != other


def test_annotation_persistence_writes_graph_nodes_edges_and_properties(db_session) -> None:
    """2026-08-06 用于验证正式标注直接形成数据库图节点关系与属性"""
    _novel_id, run_id = create_run_with_chunks(
        db_session,
        texts=["林渡与顾霜并肩迎敌"],
        title="数据库图持久化",
    )
    annotation_id = persist_chapter_annotation(
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

    facts = list(
        db_session.execute(
            select(GraphFact)
            .where(GraphFact.run_id == run_id)
            .order_by(GraphFact.graph_fact_id)
        )
        .scalars()
        .all()
    )
    sources = list(
        db_session.execute(
            select(GraphFactSource).where(GraphFactSource.run_id == run_id)
        )
        .scalars()
        .all()
    )
    relation_source = next(
        row
        for row in sources
        if row.stable_fact_id == stable_annotation_fact_id(annotation_id, "relations/0")
    )
    relation_fact_row = next(row for row in facts if row.graph_fact_id == relation_source.graph_fact_id)

    assert len(facts) == 4
    assert {row.source_kind for row in sources} == {"chapter_annotation"}
    assert relation_fact_row.content["kind"] == "relations"
    assert relation_fact_row.content["directionality"] == "directed"
    assert len(
        db_session.execute(
            select(GraphRelationEvent).where(GraphRelationEvent.run_id == run_id)
        )
        .scalars()
        .all()
    ) == 1
    assert len(
        db_session.execute(
            select(GraphRelationCurrent).where(GraphRelationCurrent.run_id == run_id)
        )
        .scalars()
        .all()
    ) == 1
    participants = list(
        db_session.execute(
            select(GraphEntityParticipant).where(GraphEntityParticipant.run_id == run_id)
        )
        .scalars()
        .all()
    )
    assert len(participants) == 2
    assert {row.relation_event_count for row in participants} == {1}


def test_persist_completion_graph_only_flushes_caller_transaction(db_session) -> None:
    """2026-08-06 用于验证图持久化不会自行提交调用方事务"""
    _novel_id, run_id = create_run_with_chunks(
        db_session,
        texts=["顾霜进入山门"],
        title="图持久化事务边界",
    )
    annotation = ChapterAnnotationRecord(
        annotation_id=str(uuid.uuid4()),
        run_id=run_id,
        chapter_id=1,
        payload={
            "chapter_summary": "顾霜进入山门",
            "segments": [
                {
                    "chunk_id": 0,
                    "summary": "顾霜进入山门",
                    "emotional_valence": "neutral",
                    "event_type": "铺垫",
                    "pivot_moment": False,
                    "cliffhanger": False,
                }
            ],
            "characters": [],
            "locations": [],
            "dialogues": [],
            "events": [],
            "relations": [],
            "states": [],
        },
        initial_finish_payload={},
        revision_payload={},
    )
    db_session.add(annotation)
    db_session.flush()

    persist_completion_graph(
        db_session,
        annotation=annotation,
        fact_outputs=[],
    )
    assert db_session.in_transaction()
    db_session.rollback()

    assert db_session.execute(
        select(GraphFact).where(GraphFact.run_id == run_id)
    ).scalars().all() == []


def test_fact_graph_search_traverses_entity_relation_to_unmatched_fact(db_session) -> None:
    """2026-08-06 用于验证图查询沿实体关系命中不含查询文本的目标事实"""
    _novel_id, run_id = create_run_with_chunks(
        db_session,
        texts=["顾霜与贺重明结盟，贺重明守住山门"],
        title="结构图检索",
    )
    annotation_id = persist_chapter_annotation(
        db_session,
        run_id=run_id,
        chapter_id=1,
        characters=[
            character_fact(chunk_id=0, name="顾霜", action="与贺重明结盟"),
            character_fact(chunk_id=0, name="贺重明", action="守住山门"),
        ],
        relations=[
            relation_fact(
                chunk_id=0,
                from_name="顾霜",
                to_name="贺重明",
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
    db_session.commit()
    source_entity = db_session.execute(
        select(GraphEntity).where(
            GraphEntity.run_id == run_id,
            GraphEntity.canonical_name == "霜姐",
        )
    ).scalar_one()

    target_graph_node_key = stable_annotation_fact_id(annotation_id, "characters/0")
    matches = search_fact_graph(run_id, "霜姐", session=db_session, max_hops=3)
    target = next(item for item in matches if item.target_node_id == f"fact:{target_graph_node_key}")

    assert target.path[0] == f"entity:{source_entity.entity_id}"
    assert target.path[-1] == f"fact:{target_graph_node_key}"
    assert [edge["edge_kind"] for edge in target.matched_edges] == ["relation", "subject"]
    assert target.matched_edges[0]["properties"]["relation_type"] == "同一人物"
    assert target.matched_edges[0]["properties"]["relation_semantics"] == "same_character"
    assert f"entity:{source_entity.entity_id}" in target.path


def test_identity_component_reselects_one_existing_character_node(db_session) -> None:
    """2026-08-06 用于验证同一人物连通分量保留全部节点并重选唯一常用节点"""
    _novel_id, run_id = create_run_with_chunks(
        db_session,
        texts=["霜姐、顾霜与顾姑娘是同一人物的不同称谓"],
        title="常用人物节点选举",
    )
    annotation_id = persist_chapter_annotation(
        db_session,
        run_id=run_id,
        chapter_id=1,
        characters=[
            character_fact(chunk_id=0, name="霜姐", action="现身"),
            character_fact(chunk_id=0, name="顾霜", action="被点明本名"),
            character_fact(chunk_id=0, name="顾姑娘", action="被人称呼"),
        ],
    )
    annotation = db_session.get(ChapterAnnotationRecord, annotation_id)
    assert annotation is not None
    entities_by_name = {
        row.canonical_name: row
        for row in db_session.execute(
            select(GraphEntity).where(GraphEntity.run_id == run_id)
        )
        .scalars()
        .all()
    }

    persist_completion_graph(
        db_session,
        annotation=annotation,
        fact_outputs=[
            identity_relation_output(
                subject_name="霜姐",
                object_name="顾霜",
                representative_endpoint="object",
            ),
            identity_relation_output(
                subject_name="霜姐",
                object_name="顾姑娘",
                representative_node_id=f"entity:{entities_by_name['顾霜'].entity_id}",
            ),
            identity_relation_output(
                subject_name="顾霜",
                object_name="顾姑娘",
                representative_endpoint="object",
            ),
        ],
    )
    db_session.flush()

    entities = list(
        db_session.execute(
            select(GraphEntity)
            .where(GraphEntity.run_id == run_id)
            .order_by(GraphEntity.entity_id)
        )
        .scalars()
        .all()
    )
    assert {row.canonical_name for row in entities} == {"霜姐", "顾霜", "顾姑娘"}
    assert [row.canonical_name for row in entities if row.is_representative] == ["顾姑娘"]
    assert [
        row.canonical_name
        for row in GraphRepository(db_session).fetch_representative_entities(
            run_id,
            entity_type="character",
        )
    ] == ["顾姑娘"]


def test_identity_component_rejects_representative_outside_component(db_session) -> None:
    """2026-08-06 用于验证代表人物节点必须属于已确认同一人物连通分量"""
    _novel_id, run_id = create_run_with_chunks(
        db_session,
        texts=["霜姐与顾霜身份确认，林渡是另一人"],
        title="常用人物节点边界",
    )
    annotation_id = persist_chapter_annotation(
        db_session,
        run_id=run_id,
        chapter_id=1,
        characters=[
            character_fact(chunk_id=0, name="霜姐", action="现身"),
            character_fact(chunk_id=0, name="顾霜", action="身份揭示"),
            character_fact(chunk_id=0, name="林渡", action="旁观"),
        ],
    )
    annotation = db_session.get(ChapterAnnotationRecord, annotation_id)
    assert annotation is not None
    outside_entity = db_session.execute(
        select(GraphEntity).where(
            GraphEntity.run_id == run_id,
            GraphEntity.canonical_name == "林渡",
        )
    ).scalar_one()

    with pytest.raises(ValueError, match="代表节点不属于同一人物连通分量"):
        persist_completion_graph(
            db_session,
            annotation=annotation,
            fact_outputs=[
                identity_relation_output(
                    subject_name="霜姐",
                    object_name="顾霜",
                    representative_node_id=f"entity:{outside_entity.entity_id}",
                )
            ],
        )


def test_identity_component_rejects_representative_from_other_run(db_session) -> None:
    """2026-08-06 用于验证常用节点 ID 必须属于当前数据库图运行"""
    _foreign_novel_id, foreign_run_id = create_run_with_chunks(
        db_session,
        texts=["外部运行人物"],
        title="外部人物节点",
    )
    persist_chapter_annotation(
        db_session,
        run_id=foreign_run_id,
        chapter_id=1,
        characters=[character_fact(chunk_id=0, name="林渡", action="旁观")],
    )
    foreign_entity = db_session.execute(
        select(GraphEntity).where(
            GraphEntity.run_id == foreign_run_id,
            GraphEntity.canonical_name == "林渡",
        )
    ).scalar_one()

    _novel_id, run_id = create_run_with_chunks(
        db_session,
        texts=["霜姐即顾霜"],
        title="当前人物节点",
    )
    annotation_id = persist_chapter_annotation(
        db_session,
        run_id=run_id,
        chapter_id=1,
        characters=[
            character_fact(chunk_id=0, name="霜姐", action="现身"),
            character_fact(chunk_id=0, name="顾霜", action="身份揭示"),
        ],
    )
    annotation = db_session.get(ChapterAnnotationRecord, annotation_id)
    assert annotation is not None

    with pytest.raises(ValueError, match="常用节点不属于当前 run_id"):
        persist_completion_graph(
            db_session,
            annotation=annotation,
            fact_outputs=[
                identity_relation_output(
                    subject_name="霜姐",
                    object_name="顾霜",
                    representative_node_id=f"entity:{foreign_entity.entity_id}",
                )
            ],
        )


def test_negated_identity_fact_closes_edge_and_preserves_nodes(db_session) -> None:
    """2026-08-06 用于验证否定同一人物事实关闭当前边并保留历史节点"""
    _novel_id, run_id = create_run_with_chunks(
        db_session,
        texts=["霜姐被认为是顾霜", "后来确认霜姐并非顾霜"],
        chapter_ids=[1, 2],
        title="同一人物关系否定",
    )
    first_annotation_id = persist_chapter_annotation(
        db_session,
        run_id=run_id,
        chapter_id=1,
        characters=[
            character_fact(chunk_id=0, name="霜姐", action="现身"),
            character_fact(chunk_id=0, name="顾霜", action="被提及"),
        ],
    )
    first_annotation = db_session.get(ChapterAnnotationRecord, first_annotation_id)
    assert first_annotation is not None
    persist_completion_graph(
        db_session,
        annotation=first_annotation,
        fact_outputs=[
            identity_relation_output(
                subject_name="霜姐",
                object_name="顾霜",
                representative_endpoint="object",
            )
        ],
    )
    db_session.commit()

    second_annotation_id = persist_chapter_annotation(
        db_session,
        run_id=run_id,
        chapter_id=2,
        characters=[
            character_fact(
                chunk_id=1,
                name="霜姐",
                action="确认与顾霜不是同一人物",
                chapter_id=2,
            )
        ],
    )
    second_annotation = db_session.get(ChapterAnnotationRecord, second_annotation_id)
    assert second_annotation is not None
    persist_completion_graph(
        db_session,
        annotation=second_annotation,
        fact_outputs=[
            identity_relation_output(
                subject_name="霜姐",
                object_name="顾霜",
                assertion="negated",
                chapter_id=2,
            )
        ],
    )
    db_session.flush()

    repository = GraphRepository(db_session)
    assert repository.fetch_current_relations(run_id, active_only=True) == []
    assert [row.change_type for row in repository.fetch_relation_events(run_id)] == ["断裂", "新建"]
    entities = repository.fetch_entities(run_id, entity_type="character")
    assert {row.canonical_name for row in entities} == {"霜姐", "顾霜"}
    assert all(row.is_representative for row in entities)
