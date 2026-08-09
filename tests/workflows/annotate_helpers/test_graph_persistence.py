"""agent-semantic-v1 图持久化测试"""

from __future__ import annotations

import pytest
from sqlalchemy import select

from src.agents.annotation.candidates import extract_dialogue_candidates
from src.agents.annotation.schema import (
    BoundChapterAnnotation,
    BoundCharacterObservation,
    BoundChunkAnnotation,
    BoundDialogue,
    BoundEntity,
    BoundEntityDirectory,
    BoundEvent,
    BoundForeshadowing,
    BoundRelation,
    BoundState,
    ChunkMetricsInput,
)
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
from tests.support.chapter_annotation_helpers import (
    character_fact,
    create_run_with_chunks,
    evidence,
    persist_chapter_annotation,
    relation_fact,
)


def _full_annotation(text: str) -> BoundChapterAnnotation:
    """2026-08-07 用于构造覆盖四类实体与全部领域事实的完整章节标注"""
    candidates = extract_dialogue_candidates(0, text)
    dialogue_candidate = next(candidate for candidate in candidates if candidate.content == "住手")
    return BoundChapterAnnotation(
        chapter_summary="顾霜进入山门并受宗门庇护",
        chunks=[
            BoundChunkAnnotation(
                chunk_id=0,
                metrics=ChunkMetricsInput(
                    summary="顾霜进入山门",
                    emotional_valence="neutral",
                    narrative_function="铺垫",
                    pivot_moment=False,
                    cliffhanger=False,
                    confidence="high",
                    reason="进入",
                ),
                entities=BoundEntityDirectory(
                    entities=[
                        BoundEntity(
                            name="顾霜",
                            entity_type="character",
                            confidence="high",
                            reason="人物出现",
                            evidence=evidence("顾霜出现", 0),
                        ),
                        BoundEntity(
                            name="山门",
                            entity_type="location",
                            description="青石山门",
                            confidence="high",
                            reason="地点出现",
                            evidence=evidence("山门出现", 0),
                        ),
                        BoundEntity(
                            name="玄剑",
                            entity_type="item",
                            tags=["宝剑"],
                            confidence="high",
                            reason="物品出现",
                            evidence=evidence("玄剑出现", 0),
                        ),
                        BoundEntity(
                            name="天衡宗",
                            entity_type="organization",
                            confidence="high",
                            reason="组织出现",
                            evidence=evidence("天衡宗出现", 0),
                        ),
                    ]
                ),
                character_observations=[
                    BoundCharacterObservation(
                        character="顾霜",
                        role_function="主体",
                        action="进入山门",
                        action_type="移动",
                        emotion="neutral",
                        confidence="high",
                        reason="顾霜进入",
                        evidence=evidence("顾霜进入", 0),
                    )
                ],
                dialogues=[
                    BoundDialogue(
                        candidate_key=dialogue_candidate.candidate_key,
                        content=dialogue_candidate.content,
                        start=dialogue_candidate.start,
                        end=dialogue_candidate.end,
                        description="喝止住手",
                        speaker=None,
                        tone="急切",
                        is_inner_monologue=False,
                        confidence="high",
                        reason="双引号",
                        evidence=evidence("住手", 0),
                    )
                ],
                events=[
                    BoundEvent(
                        description="顾霜进入山门",
                        participants=[
                            {"entity": "顾霜", "participation": "主体"}
                        ],
                        location="山门",
                        confidence="high",
                        reason="进入事件",
                        evidence=evidence("顾霜进入山门", 0),
                    )
                ],
                relations=[
                    BoundRelation(
                        from_entity="顾霜",
                        to_entity="山门",
                        relation_type="位于",
                        change_kind="assert",
                        confidence="high",
                        reason="顾霜位于山门",
                        directionality="directed",
                        relation_semantics="ordinary",
                        evidence=evidence("顾霜位于山门", 0),
                    )
                ],
                states=[
                    BoundState(
                        entity="顾霜",
                        predicate="holds",
                        object="玄剑",
                        confidence="high",
                        reason="顾霜持有玄剑",
                        evidence=evidence("顾霜持有玄剑", 0),
                    )
                ],
                foreshadowings=[
                    BoundForeshadowing(
                        foreshadowing_type="场景",
                        setup_kind="其他",
                        setup_summary="天衡宗将庇护顾霜",
                        why_unresolved_now="本章尚未兑现",
                        expected_payoff_family="援助",
                        payoff_likelihood="high",
                        setup_status="open",
                        confidence="high",
                        reason="庇护伏笔",
                        evidence=evidence("天衡宗庇护尚待回收", 0),
                    )
                ],
            )
        ],
    )


def _persist(
    db_session,
    *,
    run_id: str,
    chapter_id: int = 1,
    annotation: BoundChapterAnnotation | None = None,
    text: str | None = None,
):
    """2026-08-07 用于通过生产入口持久化测试章节标注"""
    if annotation is None:
        if text is None:
            raise ValueError("必须提供 annotation 或 text")
        annotation = _full_annotation(text)
    row = ChapterAnnotationRepository(db_session).add_annotation(
        run_id=run_id,
        chapter_id=chapter_id,
        annotation=annotation,
    )
    result = persist_completion_graph(
        db_session,
        annotation=row,
        resolved_cases=[],
        authorized_text_chunk_ids={chunk.chunk_id for chunk in annotation.chunks},
    )
    return row, result


def test_annotation_fact_id_uses_stable_position() -> None:
    """2026-08-07 用于验证事实 ID 按 chunk 领域序号稳定生成"""
    annotation_id = "4fb6b307-3504-445c-852d-a94353f2f2de"
    first = stable_annotation_fact_id(annotation_id, 0, "relation", 0)
    second = stable_annotation_fact_id(annotation_id, 0, "relation", 0)
    other = stable_annotation_fact_id(annotation_id, 0, "relation", 1)
    other_chunk = stable_annotation_fact_id(annotation_id, 1, "relation", 0)

    assert first == second
    assert first != other
    assert first != other_chunk


def test_persistence_creates_four_entity_types_and_all_domain_facts(db_session) -> None:
    """2026-08-07 用于验证实体目录先创建四类节点并逐领域写事实"""
    text = "顾霜进入山门，持有玄剑，受天衡宗庇护，“住手”回荡。"
    _novel_id, run_id = create_run_with_chunks(
        db_session,
        texts=[text],
        title="新合同图持久化",
    )
    row, result = _persist(db_session, run_id=run_id, text=text)
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
        "item",
        "organization",
    }
    location = next(entity for entity in entities if entity.entity_type == "location")
    assert location.attributes["description"] == "青石山门"
    sword = next(entity for entity in entities if entity.entity_type == "item")
    assert sword.tags == ["宝剑"]
    assert {fact.content["kind"] for fact in facts} == {
        "character_observation",
        "dialogue",
        "event",
        "relation",
        "state",
        "foreshadowing",
    }
    assert all(fact.source_kind == "annotation" for fact in facts)
    relation = next(fact for fact in facts if fact.content["kind"] == "relation")
    assert relation.payload_path == "chunks/0/relation/0"
    assert relation.fact_id == stable_annotation_fact_id(
        row.annotation_id,
        0,
        "relation",
        0,
    )
    dialogue = next(fact for fact in facts if fact.content["kind"] == "dialogue")
    assert dialogue.payload_path == "chunks/0/dialogue/0"
    assert dialogue.content["speaker"] is None
    assert result.dialogue_facts_by_candidate_key[dialogue.content["candidate_key"]].fact_id == (
        dialogue.fact_id
    )


def test_dialogue_fact_binds_system_original_text_and_position(db_session) -> None:
    """2026-08-07 用于验证对话原文位置与内容全部由系统候选绑定"""
    text = "顾霜进入山门，“住手”回荡。"
    _novel_id, run_id = create_run_with_chunks(
        db_session,
        texts=[text],
        title="系统对话位置",
    )
    _persist(db_session, run_id=run_id, text=text)
    db_session.commit()

    dialogue = db_session.execute(
        select(GraphFact).where(
            GraphFact.run_id == run_id,
            GraphFact.fact_type == "dialogue",
        )
    ).scalar_one()
    chunk_text = "顾霜进入山门，“住手”回荡。"
    start = int(dialogue.content["start"])
    end = int(dialogue.content["end"])
    assert chunk_text[start:end] == "住手"
    assert dialogue.content["content"] == "住手"
    assert dialogue.content["chunk_id"] == 0


def test_persistence_writes_state_and_relation_versions(db_session) -> None:
    """2026-08-07 用于验证观察状态和关系仍驱动下游版本表"""
    text = "顾霜进入山门，持有玄剑，受天衡宗庇护，“住手”回荡。"
    _novel_id, run_id = create_run_with_chunks(
        db_session,
        texts=[text],
        title="状态关系版本",
    )
    _row, result = _persist(db_session, run_id=run_id, text=text)
    db_session.commit()

    state_rows = list(
        db_session.execute(
            select(EntityStateVersion).where(
                EntityStateVersion.graph_version_id
                == result.graph_version.graph_version_id
            )
        ).scalars()
    )
    relation_version = db_session.execute(
        select(GraphRelationVersion).where(
            GraphRelationVersion.graph_version_id
            == result.graph_version.graph_version_id
        )
    ).scalar_one()
    relation_row = db_session.get(GraphRelation, relation_version.relation_id)
    relation_fact = db_session.execute(
        select(GraphFact).where(
            GraphFact.run_id == run_id,
            GraphFact.fact_type == "relation",
        )
    ).scalar_one()

    assert len(state_rows) == 1
    assert relation_row.to_entity_id == next(
        entity.entity_id
        for entity in db_session.execute(
            select(GraphEntity).where(GraphEntity.run_id == run_id)
        ).scalars()
        if entity.entity_type == "location"
    )
    assert relation_version.relation_revision == 1
    assert relation_version.changes[0]["fact_id"] == relation_fact.fact_id


def test_entity_resolution_merges_existing_and_extends_seen_bounds(db_session) -> None:
    """2026-08-07 用于验证既有实体按规范化名称合并并扩展出现边界"""
    _novel_id, run_id = create_run_with_chunks(
        db_session,
        texts=["顾霜在山门修炼。", "顾霜继续修炼"],
        chapter_ids=[1, 2],
        title="实体合并",
    )
    persist_chapter_annotation(
        db_session,
        run_id=run_id,
        chapter_id=1,
        characters=[character_fact(chunk_id=0, name="顾霜", action="修炼")],
    )
    persist_chapter_annotation(
        db_session,
        run_id=run_id,
        chapter_id=2,
        characters=[character_fact(chunk_id=1, name="顾霜", action="出关")],
    )
    db_session.commit()

    entities = list(
        db_session.execute(
            select(GraphEntity).where(GraphEntity.run_id == run_id)
        ).scalars()
    )
    assert len(entities) == 1
    assert entities[0].canonical_name == "顾霜"
    assert entities[0].first_seen_chunk == 0
    assert entities[0].last_seen_chunk == 1


def test_entity_type_change_rejected_as_identity_reuse(db_session) -> None:
    """2026-08-08 用于验证同一名称跨章变更大类按身份复用报错而非静默合并"""
    _novel_id, run_id = create_run_with_chunks(
        db_session,
        texts=["赤羽炽尾鸡昂首踱步。", "赤羽炽尾鸡张开双翼"],
        chapter_ids=[1, 2],
        title="身份复用拒绝",
    )
    persist_chapter_annotation(
        db_session,
        run_id=run_id,
        chapter_id=1,
        characters=[
            character_fact(chunk_id=0, name="赤羽炽尾鸡", action="踱步")
        ],
    )
    item_fact = {
        "chunk_id": 1,
        "entity": "赤羽炽尾鸡",
        "predicate": "possesses",
        "value": "灵火",
        "confidence": "high",
        "reason": "持有灵火",
        "_entity_specs": [{"name": "赤羽炽尾鸡", "entity_type": "item"}],
    }
    with pytest.raises(ValueError, match="实体名称已属于其他大类"):
        persist_chapter_annotation(
            db_session,
            run_id=run_id,
            chapter_id=2,
            states=[item_fact],
        )


def test_sword_and_sword_spirit_are_distinct_entities(db_session) -> None:
    """2026-08-08 用于验证器物与寄宿灵体使用区分性名称并存为两个节点"""
    _novel_id, run_id = create_run_with_chunks(
        db_session,
        texts=["玄剑悬于墙上。", "剑灵在玄剑中开口"],
        chapter_ids=[1, 2],
        title="剑灵拆分",
    )
    persist_chapter_annotation(
        db_session,
        run_id=run_id,
        chapter_id=1,
        states=[
            {
                "chunk_id": 0,
                "entity": "玄剑",
                "predicate": "status",
                "value": "active",
                "confidence": "high",
                "reason": "状态",
                "_entity_specs": [
                    {"name": "玄剑", "entity_type": "item", "tags": ["法宝"]}
                ],
            }
        ],
    )
    persist_chapter_annotation(
        db_session,
        run_id=run_id,
        chapter_id=2,
        states=[
            {
                "chunk_id": 1,
                "entity": "剑灵",
                "predicate": "resides_in",
                "object": "玄剑",
                "confidence": "high",
                "reason": "寄宿于玄剑",
                "_entity_specs": [
                    {"name": "剑灵", "entity_type": "character"},
                    {"name": "玄剑", "entity_type": "item"},
                ],
            }
        ],
    )
    db_session.commit()

    entities = list(
        db_session.execute(
            select(GraphEntity).where(GraphEntity.run_id == run_id)
        ).scalars()
    )
    assert {entity.canonical_name for entity in entities} == {"玄剑", "剑灵"}
    assert {entity.entity_type for entity in entities} == {"item", "character"}


def test_entity_tags_merged_and_deduplicated_across_chapters(db_session) -> None:
    """2026-08-08 用于验证实体标签跨章合并且去重"""
    _novel_id, run_id = create_run_with_chunks(
        db_session,
        texts=["玄剑寒光凛冽。", "玄剑鸣啸"],
        chapter_ids=[1, 2],
        title="标签合并",
    )
    for chapter_id, chunk_id in ((1, 0), (2, 1)):
        persist_chapter_annotation(
            db_session,
            run_id=run_id,
            chapter_id=chapter_id,
            states=[
                {
                    "chunk_id": chunk_id,
                    "entity": "玄剑",
                    "predicate": "status",
                    "value": "active",
                    "confidence": "high",
                    "reason": "状态",
                    "_entity_specs": [
                        {
                            "name": "玄剑",
                            "entity_type": "item",
                            "tags": ["宝剑"],
                        }
                    ],
                }
            ],
        )
    db_session.commit()

    entities = list(
        db_session.execute(
            select(GraphEntity).where(GraphEntity.run_id == run_id)
        ).scalars()
    )
    assert len(entities) == 1
    assert entities[0].entity_type == "item"
    assert entities[0].tags == ["宝剑"]


def test_unknown_fact_endpoint_entity_rejected(db_session) -> None:
    """2026-08-07 用于验证事实端点未在实体目录声明时直接失败"""
    text = "顾霜在山门修炼，“住手”回荡。"
    _novel_id, run_id = create_run_with_chunks(
        db_session,
        texts=[text],
        title="未解析端点",
    )
    annotation = _full_annotation(text)
    annotation.chunks[0].entities.entities[0].name = "无名客"
    with pytest.raises(ValueError, match="事实端点实体未被系统解析"):
        _persist(db_session, run_id=run_id, annotation=annotation)


def test_persist_completion_graph_only_flushes_caller_transaction(db_session) -> None:
    """2026-08-07 用于验证图写入由外层完成事务统一提交或回滚"""
    text = "顾霜进入山门，持有玄剑，受天衡宗庇护，“住手”回荡。"
    _novel_id, run_id = create_run_with_chunks(
        db_session,
        texts=[text],
        title="图版本事务边界",
    )
    _persist(db_session, run_id=run_id, text=text)
    assert db_session.in_transaction()
    db_session.rollback()

    assert db_session.execute(
        select(GraphVersion).where(GraphVersion.run_id == run_id)
    ).scalars().all() == []
    assert db_session.execute(
        select(GraphFact).where(GraphFact.run_id == run_id)
    ).scalars().all() == []


def test_relation_break_resolves_same_stable_relation_in_later_chapter(db_session) -> None:
    """2026-08-07 用于验证后文 break 按端点类型解析同一稳定关系"""
    _novel_id, run_id = create_run_with_chunks(
        db_session,
        texts=["林渡与顾霜并肩迎敌", "两人此后分道扬镳"],
        chapter_ids=[1, 2],
        title="稳定关系解析",
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
    persist_chapter_annotation(
        db_session,
        run_id=run_id,
        chapter_id=2,
        relations=[
            relation_fact(
                chunk_id=1,
                from_name="林渡",
                to_name="顾霜",
                relation_type="盟友",
                change_kind="break",
            )
        ],
    )
    db_session.commit()

    versions = list(
        db_session.execute(
            select(GraphRelationVersion)
            .where(GraphRelationVersion.run_id == run_id)
            .order_by(GraphRelationVersion.relation_revision)
        ).scalars()
    )
    assert len(versions) == 2
    assert [version.relation_revision for version in versions] == [1, 2]
    assert versions[0].is_active is True
    assert versions[1].is_active is False
    assert versions[1].changes[0]["change_kind"] == "break"
