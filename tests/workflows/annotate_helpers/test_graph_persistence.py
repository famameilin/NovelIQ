"""ChapterFinish 图持久化测试"""

from __future__ import annotations

from sqlalchemy import select

from src.agents.annotation.schema import ChapterFinish
from src.storage.models import (
    EntityStateVersion,
    GraphEntity,
    GraphFact,
    GraphRelation,
    GraphRelationVersion,
    GraphVersion,
)
from src.storage.repositories import ChapterAnnotationRepository
from src.storage.repositories.graph import persist_completion_graph, stable_annotation_fact_id
from tests.support.chapter_annotation_helpers import create_run_with_chunks


def _span(text: str, value: str, chunk_id: int = 0) -> dict:
    """2026-08-07 用于构造精确实体 mention"""
    start = text.index(value)
    return {
        "chunk_id": chunk_id,
        "start": start,
        "end": start + len(value),
        "text": value,
    }


def _entity(
    text: str,
    *,
    ref: str,
    name: str,
    chunk_id: int = 0,
) -> dict:
    """2026-08-07 用于构造带 current mention 的实体目录项"""
    return {
        "ref": ref,
        "name": name,
        "existing_entity_id": None,
        "mentions": [_span(text, name, chunk_id)],
        "confidence": "high",
        "evidence": [{"reason": f"{name}出现", "chunk_id": chunk_id}],
    }


def _coverage(chunk_id: int = 0) -> dict:
    """2026-08-07 用于构造全领域 coverage"""
    return {
        "chunk_id": chunk_id,
        "entities": True,
        "character_observations": True,
        "location_observations": True,
        "dialogues": True,
        "events": True,
        "relations": True,
        "states": True,
        "foreshadowings": True,
    }


def _finish(text: str) -> ChapterFinish:
    """2026-08-07 用于构造覆盖四类实体与逐 chunk 事实的完整 finish"""
    return ChapterFinish.model_validate(
        {
            "chapter_summary": "顾霜进入山门并受宗门庇护",
            "entities": {
                "characters": [_entity(text, ref="character_1", name="顾霜")],
                "locations": [
                    {
                        **_entity(text, ref="location_1", name="山门"),
                        "location_type": "宗门入口",
                        "description": "青石山门",
                    }
                ],
                "objects": [
                    {
                        **_entity(text, ref="object_1", name="玄剑"),
                        "object_type": "兵器",
                    }
                ],
                "organizations": [
                    {
                        **_entity(text, ref="organization_1", name="天衡宗"),
                        "organization_type": "宗门",
                    }
                ],
            },
            "chunks": [
                {
                    "chunk_id": 0,
                    "summary": "顾霜进入山门",
                    "metrics": {
                        "emotional_valence": "neutral",
                        "event_type": "铺垫",
                        "pivot_moment": False,
                        "cliffhanger": False,
                    },
                    "character_observations": [
                        {
                            "ref": "character_observation_1",
                            "confidence": "high",
                            "evidence": [{"reason": "顾霜进入", "chunk_id": 0}],
                            "entity_ref": "character_1",
                            "role_function": "主体",
                            "action": "进入山门",
                            "action_type": "移动",
                            "emotion": "neutral",
                        }
                    ],
                    "location_observations": [
                        {
                            "ref": "location_observation_1",
                            "confidence": "high",
                            "evidence": [{"reason": "山门为宗门入口", "chunk_id": 0}],
                            "location_ref": "location_1",
                            "predicate": "status",
                            "value": "open",
                        }
                    ],
                    "dialogues": [],
                    "events": [
                        {
                            "ref": "event_1",
                            "confidence": "high",
                            "evidence": [{"reason": "顾霜进入山门", "chunk_id": 0}],
                            "event_type": "进入",
                            "summary": "顾霜进入山门",
                            "participants": [
                                {"role": "actor", "entity_ref": "character_1"}
                            ],
                            "location_ref": "location_1",
                        }
                    ],
                    "relations": [
                        {
                            "ref": "relation_1",
                            "confidence": "high",
                            "evidence": [{"reason": "顾霜位于山门", "chunk_id": 0}],
                            "from_ref": "character_1",
                            "to_ref": "location_1",
                            "relation_type": "located_at",
                            "change_kind": "assert",
                        }
                    ],
                    "states": [
                        {
                            "ref": "state_1",
                            "confidence": "high",
                            "evidence": [{"reason": "顾霜持有玄剑", "chunk_id": 0}],
                            "entity_ref": "character_1",
                            "predicate": "holds",
                            "object_ref": "object_1",
                        }
                    ],
                    "foreshadowings": [
                        {
                            "ref": "foreshadowing_1",
                            "confidence": "high",
                            "evidence": [{"reason": "天衡宗庇护尚待回收", "chunk_id": 0}],
                            "foreshadowing_type": "场景",
                            "setup_kind": "宗门庇护",
                            "setup_summary": "天衡宗将庇护顾霜",
                            "why_unresolved_now": "本章尚未兑现",
                            "expected_payoff_family": "援助",
                            "payoff_likelihood": "high",
                            "is_new_setup": True,
                            "setup_status": "open",
                        }
                    ],
                }
            ],
            "coverage": [_coverage()],
        }
    )


def _persist_finish(db_session, *, run_id: str, finish: ChapterFinish):
    """2026-08-07 用于通过生产入口持久化测试 finish"""
    annotation = ChapterAnnotationRepository(db_session).add_annotation(
        run_id=run_id,
        chapter_id=1,
        finish=finish,
        initial_finish=finish,
        revision_payloads=[],
    )
    result = persist_completion_graph(
        db_session,
        annotation=annotation,
        pulled_results=[],
        authorized_text_chunk_ids={0},
        visible_graph_fact_refs=set(),
        visible_relation_ids=set(),
        visible_graph_entity_ids=set(),
    )
    return annotation, result


def test_annotation_fact_id_uses_stable_item_ref() -> None:
    """2026-08-07 用于验证事实 ID 不再依赖数组下标"""
    first = stable_annotation_fact_id("annotation-1", "relation_1")
    second = stable_annotation_fact_id("annotation-1", "relation_1")
    other = stable_annotation_fact_id("annotation-1", "relation_2")

    assert first == second
    assert first != other


def test_finish_persistence_creates_four_entity_types_and_ref_facts(db_session) -> None:
    """2026-08-07 用于验证实体目录先创建四类节点并逐 chunk 写事实"""
    text = "顾霜进入山门，持有玄剑，受天衡宗庇护"
    _novel_id, run_id = create_run_with_chunks(
        db_session,
        texts=[text],
        title="新合同图持久化",
    )
    annotation, result = _persist_finish(
        db_session,
        run_id=run_id,
        finish=_finish(text),
    )
    db_session.commit()

    entities = list(
        db_session.execute(
            select(GraphEntity)
            .where(GraphEntity.run_id == run_id)
            .order_by(GraphEntity.entity_type)
        ).scalars()
    )
    facts = list(
        db_session.execute(
            select(GraphFact)
            .where(GraphFact.run_id == run_id)
            .order_by(GraphFact.payload_path)
        ).scalars()
    )
    assert {entity.entity_type for entity in entities} == {
        "character",
        "location",
        "object",
        "organization",
    }
    location = next(entity for entity in entities if entity.entity_type == "location")
    assert location.attributes["location_type"] == "宗门入口"
    assert {fact.content["kind"] for fact in facts} == {
        "character_observation",
        "location_observation",
        "event",
        "relation",
        "state",
        "foreshadowing",
    }
    assert result.finish_facts_by_ref["relation_1"].fact_id == stable_annotation_fact_id(
        annotation.annotation_id,
        "relation_1",
    )
    assert all(fact.source_kind == "chapter_finish" for fact in facts)


def test_finish_persistence_writes_state_and_relation_versions(db_session) -> None:
    """2026-08-07 用于验证观察状态和关系仍驱动下游版本表"""
    text = "顾霜进入山门，持有玄剑，受天衡宗庇护"
    _novel_id, run_id = create_run_with_chunks(
        db_session,
        texts=[text],
        title="状态关系版本",
    )
    _annotation, result = _persist_finish(
        db_session,
        run_id=run_id,
        finish=_finish(text),
    )
    db_session.commit()

    state_rows = list(
        db_session.execute(
            select(EntityStateVersion).where(
                EntityStateVersion.graph_version_id
                == result.graph_version.graph_version_id
            )
        ).scalars()
    )
    relation = db_session.execute(
        select(GraphRelation).where(GraphRelation.run_id == run_id)
    ).scalar_one()
    relation_version = db_session.execute(
        select(GraphRelationVersion).where(
            GraphRelationVersion.graph_version_id
            == result.graph_version.graph_version_id
        )
    ).scalar_one()

    assert len(state_rows) == 2
    assert relation.to_entity_id == next(
        entity.entity_id
        for entity in db_session.execute(
            select(GraphEntity).where(GraphEntity.run_id == run_id)
        ).scalars()
        if entity.entity_type == "location"
    )
    assert relation_version.relation_revision == 1
    assert relation_version.changes[0]["fact_id"] == result.finish_facts_by_ref["relation_1"].fact_id


def test_persist_completion_graph_only_flushes_caller_transaction(db_session) -> None:
    """2026-08-07 用于验证图写入由外层完成事务统一提交或回滚"""
    text = "顾霜进入山门，持有玄剑，受天衡宗庇护"
    _novel_id, run_id = create_run_with_chunks(
        db_session,
        texts=[text],
        title="图版本事务边界",
    )
    _persist_finish(db_session, run_id=run_id, finish=_finish(text))
    assert db_session.in_transaction()
    db_session.rollback()

    assert db_session.execute(
        select(GraphVersion).where(GraphVersion.run_id == run_id)
    ).scalars().all() == []
    assert db_session.execute(
        select(GraphFact).where(GraphFact.run_id == run_id)
    ).scalars().all() == []
