"""agent-semantic-v2 图持久化测试"""

from __future__ import annotations

import hashlib
from uuid import NAMESPACE_URL, uuid5

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
    ChunkMetricsInput,
    ResolvedCase,
)
from src.storage.models import (
    ChapterAnnotationRecord,
    DialogueRecord,
    EntityState,
    EventEdge,
    EventNode,
    GraphEntity,
    GraphFact,
    GraphRelation,
    RelationState,
)
from src.storage.repositories import ChapterAnnotationRepository, DialogueRecordRepository
from src.storage.repositories.graph import persist_completion_graph, stable_annotation_fact_id
from src.storage.repositories.graph.persistence import _validate_dag_acyclic
from tests.support.chapter_annotation_helpers import (
    character_fact,
    create_run_with_chunks,
    persist_chapter_annotation,
    relation_fact,
)


def _full_annotation(text: str, *, chunk_id: int = 1) -> BoundChapterAnnotation:
    """2026-08-11 用于构造覆盖四类实体与全部领域事实的完整章节标注"""
    candidates = extract_dialogue_candidates(chunk_id, text)
    dialogue_candidate = next(candidate for candidate in candidates if candidate.content == "住手")
    return BoundChapterAnnotation(
        chapter_summary="顾霜进入山门并受宗门庇护",
        chunks=[
            BoundChunkAnnotation(
                chunk_id=chunk_id,
                metrics=ChunkMetricsInput(
                    summary="顾霜进入山门",
                    emotional_valence="neutral",
                    narrative_function="铺垫",
                    pivot_moment=False,
                    cliffhanger=False,
                ),
                entities=BoundEntityDirectory(
                    entities=[
                        BoundEntity(
                            name="顾霜",
                            entity_type="character",
                        ),
                        BoundEntity(
                            name="山门",
                            entity_type="location",
                            description="青石山门",
                        ),
                        BoundEntity(
                            name="玄剑",
                            entity_type="item",
                            tags=["宝剑"],
                        ),
                        BoundEntity(
                            name="天衡宗",
                            entity_type="organization",
                        ),
                    ]
                ),
                character_observations=[
                    BoundCharacterObservation(
                        character="顾霜",
                        role_function="主体",
                        action="进入山门",
                        emotion="neutral",
                    )
                ],
                dialogues=[
                    BoundDialogue(
                        candidate_index=1,
                        candidate_key=dialogue_candidate.candidate_key,
                        content=dialogue_candidate.content,
                        start=dialogue_candidate.start,
                        end=dialogue_candidate.end,
                        speaker=None,
                        tone="紧张",
                        is_inner_monologue=False,
                    )
                ],
                events=[
                    BoundEvent(
                        description="顾霜进入山门",
                        participants=[
                            {"entity": "顾霜", "role": "主体"},
                            {"entity": "山门", "role": "地点"},
                        ],
                        anchor_paragraph_ids=[0],
                        causal_event_refs=[],
                        tree_id="tree-main",
                        cause_role="root",
                        char_start=0,
                        char_end=10,
                        text_hash=hashlib.sha256(text[:10].encode("utf-8")).hexdigest(),
                        evidence=[
                            {
                                "paragraph_ids": [0],
                                "char_start": 0,
                                "char_end": 10,
                                "text_hash": hashlib.sha256(text[:10].encode("utf-8")).hexdigest(),
                            }
                        ],
                    )
                ],
                relations=[
                    BoundRelation(
                        from_entity="顾霜",
                        to_entity="山门",
                        relation_type="位于",
                        directionality="directed",
                        relation_semantics="ordinary",
                    )
                ],
                foreshadowings=[
                    BoundForeshadowing(
                        description="天衡宗将庇护顾霜",
                        confidence="high",
                        setup_event_index=1,
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
        annotation = _full_annotation(text, chunk_id=chapter_id)
    row = ChapterAnnotationRepository(db_session).add_annotation(
        run_id=run_id,
        chapter_id=chapter_id,
        annotation=annotation,
    )
    result = persist_completion_graph(
        db_session,
        annotation=row,
        resolved_cases=[],
        authorized_text_chapter_ids={chunk.chunk_id for chunk in annotation.chunks},
    )
    for chunk in annotation.chunks:
        DialogueRecordRepository(db_session).sync_dialogues(
            run_id=run_id,
            chapter_id=chapter_id,
            dialogues=chunk.dialogues,
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
        "event",
        "relation",
        "foreshadowing",
    }
    assert all(fact.source_kind == "annotation" for fact in facts)
    relation = next(fact for fact in facts if fact.content["kind"] == "relation")
    assert relation.payload_path == "chunks/1/relation/1"
    assert relation.fact_id == stable_annotation_fact_id(
        row.annotation_id,
        1,
        "relation",
        1,
    )
    dialogue = db_session.execute(
        select(DialogueRecord).where(DialogueRecord.run_id == run_id)
    ).scalar_one()
    assert dialogue.candidate_key.startswith("dlg_")
    assert dialogue.speaker is None
    assert dialogue.chapter_id == 1
    assert dialogue.confidence == "medium"


def test_dialogue_record_binds_system_original_text_and_position(db_session) -> None:
    """2026-08-11 用于验证对话原文位置与内容全部由系统候选绑定且不写图事实"""
    text = "顾霜进入山门，“住手”回荡。"
    _novel_id, run_id = create_run_with_chunks(
        db_session,
        texts=[text],
        title="系统对话位置",
    )
    _persist(db_session, run_id=run_id, text=text)
    db_session.commit()

    dialogue = db_session.execute(
        select(DialogueRecord).where(DialogueRecord.run_id == run_id)
    ).scalar_one()
    chunk_text = "顾霜进入山门，“住手”回荡。"
    start = int(dialogue.start)
    end = int(dialogue.end)
    assert chunk_text[start:end] == "住手"
    assert dialogue.content == "住手"
    assert dialogue.chapter_id == 1
    assert dialogue.is_inner_monologue is False
    assert dialogue.confidence == "medium"
    assert db_session.execute(
        select(GraphFact).where(
            GraphFact.run_id == run_id,
            GraphFact.fact_type == "dialogue",
        )
    ).scalars().all() == []


def test_persistence_writes_state_and_relation_rows(db_session) -> None:
    """2026-08-19 用于验证观察字段与实体属性驱动当前章节状态表"""
    text = "顾霜进入山门，持有玄剑，受天衡宗庇护，“住手”回荡。"
    _novel_id, run_id = create_run_with_chunks(
        db_session,
        texts=[text],
        title="状态关系章节",
    )
    _row, result = _persist(db_session, run_id=run_id, text=text)
    db_session.commit()

    state_rows = list(
        db_session.execute(
            select(EntityState).where(
                EntityState.run_id == run_id,
                EntityState.chapter_id == result.chapter_boundary.chapter_id,
            )
        ).scalars()
    )
    relation_state = db_session.execute(
        select(RelationState).where(
            RelationState.run_id == run_id,
            RelationState.chapter_id == result.chapter_boundary.chapter_id,
        )
    ).scalar_one()
    relation_row = db_session.get(GraphRelation, relation_state.relation_id)
    relation_fact = db_session.execute(
        select(GraphFact).where(
            GraphFact.run_id == run_id,
            GraphFact.fact_type == "relation",
        )
    ).scalar_one()
    observation_fact = db_session.execute(
        select(GraphFact).where(
            GraphFact.run_id == run_id,
            GraphFact.fact_type == "character_observation",
        )
    ).scalar_one()

    assert len(state_rows) == 1
    assert state_rows[0].entity_id == observation_fact.subject_entity_id
    assert state_rows[0].state["entity_type"] == "character"
    assert state_rows[0].state["role_function"] == "主体"
    assert state_rows[0].state["action"] == "进入山门"
    assert state_rows[0].state["emotion"] == "neutral"
    assert state_rows[0].changes[0]["fact_id"] == observation_fact.fact_id
    assert relation_row.to_entity_id == next(
        entity.entity_id
        for entity in db_session.execute(
            select(GraphEntity).where(GraphEntity.run_id == run_id)
        ).scalars()
        if entity.entity_type == "location"
    )
    assert relation_state.chapter_id == result.chapter_boundary.chapter_id
    assert relation_state.changes[0]["fact_id"] == relation_fact.fact_id


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
        characters=[character_fact(chunk_id=1, name="顾霜", action="修炼")],
    )
    persist_chapter_annotation(
        db_session,
        run_id=run_id,
        chapter_id=2,
        characters=[character_fact(chunk_id=2, name="顾霜", action="出关")],
    )
    db_session.commit()

    entities = list(
        db_session.execute(
            select(GraphEntity).where(GraphEntity.run_id == run_id)
        ).scalars()
    )
    assert len(entities) == 1
    assert entities[0].canonical_name == "顾霜"
    assert entities[0].first_seen_chapter == 1
    assert entities[0].last_seen_chapter == 2


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
            character_fact(chunk_id=1, name="赤羽炽尾鸡", action="踱步")
        ],
    )
    with pytest.raises(ValueError, match="实体名称已属于其他大类"):
        persist_chapter_annotation(
            db_session,
            run_id=run_id,
            chapter_id=2,
            relations=[
                relation_fact(
                    chunk_id=2,
                    from_name="赤羽炽尾鸡",
                    to_name="山门",
                    relation_type="位于",
                    from_entity_type="item",
                    to_entity_type="location",
                )
            ],
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
        relations=[
            relation_fact(
                chunk_id=1,
                from_name="玄剑",
                to_name="山门",
                relation_type="位于",
                from_entity_type="item",
                to_entity_type="location",
            )
        ],
    )
    persist_chapter_annotation(
        db_session,
        run_id=run_id,
        chapter_id=2,
        characters=[character_fact(chunk_id=2, name="剑灵", action="开口")],
    )
    db_session.commit()

    entities = list(
        db_session.execute(
            select(GraphEntity).where(GraphEntity.run_id == run_id)
        ).scalars()
    )
    by_name = {entity.canonical_name: entity for entity in entities}
    assert {"玄剑", "剑灵"} <= set(by_name)
    assert by_name["玄剑"].entity_type == "item"
    assert by_name["剑灵"].entity_type == "character"


def test_entity_attributes_merged_across_chapters(db_session) -> None:
    """2026-08-11 用于验证已登记实体跨章按 JSON Merge Patch 合并且未提交字段沿用"""
    _novel_id, run_id = create_run_with_chunks(
        db_session,
        texts=["玄剑寒光凛冽。", "玄剑鸣啸"],
        chapter_ids=[1, 2],
        title="属性合并",
    )
    persist_chapter_annotation(
        db_session,
        run_id=run_id,
        chapter_id=1,
        entity_attributes={(1, "玄剑"): {"status": "active", "grade": "凡品"}},
    )
    persist_chapter_annotation(
        db_session,
        run_id=run_id,
        chapter_id=2,
        entity_attributes={(2, "玄剑"): {"grade": "灵品"}},
    )
    db_session.commit()

    entities = list(
        db_session.execute(
            select(GraphEntity).where(GraphEntity.run_id == run_id)
        ).scalars()
    )
    assert len(entities) == 1
    assert entities[0].attributes == {
        "entity_type": "character",
        "status": "active",
        "grade": "灵品",
    }
    attribute_facts = list(
        db_session.execute(
            select(GraphFact).where(
                GraphFact.run_id == run_id,
                GraphFact.fact_type == "entity_attribute",
            )
        ).scalars()
    )
    assert len(attribute_facts) == 1
    assert attribute_facts[0].content["kind"] == "entity_attribute"
    assert attribute_facts[0].content["field"] == "grade"
    state_rows = list(
        db_session.execute(
            select(EntityState).where(EntityState.run_id == run_id)
        ).scalars()
    )
    assert len(state_rows) == 2
    latest_state = max(state_rows, key=lambda row: row.chapter_id)
    assert latest_state.state == {
        "entity_type": "character",
        "status": "active",
        "grade": "灵品",
    }


def test_entity_attributes_deleted_and_overwritten_by_merge_patch(db_session) -> None:
    """2026-08-11 用于验证属性 null 删除与覆盖式更新并驱动章节状态"""
    _novel_id, run_id = create_run_with_chunks(
        db_session,
        texts=["玄剑寒光凛冽。", "玄剑鸣啸"],
        chapter_ids=[1, 2],
        title="属性覆盖",
    )
    persist_chapter_annotation(
        db_session,
        run_id=run_id,
        chapter_id=1,
        entity_attributes={(1, "玄剑"): {"status": "active", "grade": "凡品"}},
    )
    persist_chapter_annotation(
        db_session,
        run_id=run_id,
        chapter_id=2,
        entity_attributes={(2, "玄剑"): {"status": None, "grade": "灵品"}},
    )
    db_session.commit()

    entities = list(
        db_session.execute(
            select(GraphEntity).where(GraphEntity.run_id == run_id)
        ).scalars()
    )
    assert len(entities) == 1
    assert entities[0].attributes == {
        "entity_type": "character",
        "grade": "灵品",
    }
    attribute_facts = list(
        db_session.execute(
            select(GraphFact).where(
                GraphFact.run_id == run_id,
                GraphFact.fact_type == "entity_attribute",
            )
        ).scalars()
    )
    assert {fact.content["field"] for fact in attribute_facts} == {"status", "grade"}
    status_fact = next(
        fact for fact in attribute_facts if fact.content["field"] == "status"
    )
    assert status_fact.content["before"] == "active"
    assert status_fact.content["after"] is None
    state_rows = list(
        db_session.execute(
            select(EntityState).where(EntityState.run_id == run_id)
        ).scalars()
    )
    assert len(state_rows) == 2
    latest_state = max(state_rows, key=lambda row: row.chapter_id)
    assert latest_state.chapter_id == 2
    assert latest_state.state == {
        "entity_type": "character",
        "grade": "灵品",
    }


def test_attribute_patch_generated_once_for_multi_chunk_chapter(db_session) -> None:
    """2026-08-12 用于验证跨章属性变化事实按字段只生成一次：
    属性 patch 与 chunk 循环无关，不随同章多次引用重复写入"""
    _novel_id, run_id = create_run_with_chunks(
        db_session,
        texts=["玄剑寒光凛冽。", "玄剑鸣啸"],
        chapter_ids=[1, 2],
        title="属性 patch 去重",
    )
    # 章1 首次声明实体，不产生属性 patch
    persist_chapter_annotation(
        db_session,
        run_id=run_id,
        chapter_id=1,
        entity_attributes={(1, "玄剑"): {"status": "active"}},
    )
    db_session.commit()
    # 章2 更新属性：跨章已存在实体产生 patch，按字段各生成一条，
    # 不随同章多次引用重复写入
    persist_chapter_annotation(
        db_session,
        run_id=run_id,
        chapter_id=2,
        entity_attributes={(2, "玄剑"): {"grade": "灵品", "status": "dormant"}},
    )
    db_session.commit()

    attribute_facts = list(
        db_session.execute(
            select(GraphFact).where(
                GraphFact.run_id == run_id,
                GraphFact.fact_type == "entity_attribute",
            )
        ).scalars()
    )
    # 章2 两个字段变化各生成一条事实：grade 与 status，共 2 条
    assert len(attribute_facts) == 2
    fields = sorted(str(fact.content["field"]) for fact in attribute_facts)
    assert fields == ["grade", "status"]


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
        title="图章节事务边界",
    )
    _persist(db_session, run_id=run_id, text=text)
    assert db_session.in_transaction()
    db_session.rollback()

    assert db_session.execute(
        select(ChapterAnnotationRecord).where(ChapterAnnotationRecord.run_id == run_id)
    ).scalars().all() == []
    assert db_session.execute(
        select(GraphFact).where(GraphFact.run_id == run_id)
    ).scalars().all() == []


def test_relation_remark_in_later_chapter_keeps_chapter_history(db_session) -> None:
    """2026-08-19 用于验证后文再次提交同一关系边保留章节历史"""
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
            character_fact(chunk_id=1, name="林渡", action="迎敌"),
            character_fact(chunk_id=1, name="顾霜", action="迎敌"),
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
    persist_chapter_annotation(
        db_session,
        run_id=run_id,
        chapter_id=2,
        relations=[
            relation_fact(
                chunk_id=2,
                from_name="林渡",
                to_name="顾霜",
                relation_type="盟友",
            )
        ],
    )
    db_session.commit()

    states = list(
        db_session.execute(
            select(RelationState)
            .where(RelationState.run_id == run_id)
            .order_by(RelationState.chapter_id)
        ).scalars()
    )
    assert len(states) == 2
    assert states[0].is_active is True
    assert states[0].changes[0]["change_kind"] == "assert"


def test_same_chapter_fact_resolution_merges_into_relation_state(db_session) -> None:
    """2026-08-19 用于验证本章关系断言与案例事实合并到同一章节状态行"""
    _novel_id, run_id = create_run_with_chunks(
        db_session,
        texts=["林渡与顾霜并肩迎敌"],
        title="同章断言加案例解决",
    )
    persist_chapter_annotation(
        db_session,
        run_id=run_id,
        chapter_id=1,
        characters=[
            character_fact(chunk_id=1, name="林渡", action="迎敌"),
            character_fact(chunk_id=1, name="顾霜", action="迎敌"),
        ],
        relations=[
            relation_fact(
                chunk_id=1,
                from_name="林渡",
                to_name="顾霜",
                relation_type="盟友",
            )
        ],
        resolved_cases=[
            ResolvedCase(
                case_id="case-alias-same-person",
                action="fact",
                type="relation_change",
                reason="同一人物归并",
                target_key="target-alias",
                target_ref={"kind": "relation_change", "chunk_id": 1},
                from_entity="林渡",
                to_entity="顾霜",
                relation_type="盟友",
                change_kind="assert",
            )
        ],
    )
    db_session.commit()

    states = list(
        db_session.execute(
            select(RelationState)
            .where(RelationState.run_id == run_id)
            .order_by(RelationState.chapter_id)
        ).scalars()
    )
    assert len(states) == 1
    assert states[0].chapter_id == 1
    assert states[0].is_active is True
    assert states[0].attributes["support_count"] == 2
    assert [change["change_kind"] for change in states[0].changes] == [
        "assert",
        "assert",
    ]
    resolution_fact = db_session.execute(
        select(GraphFact).where(
            GraphFact.run_id == run_id,
            GraphFact.source_kind == "case_resolution",
        )
    ).scalar_one()
    assert states[0].changes[1]["fact_id"] == resolution_fact.fact_id


def test_same_chapter_relation_double_write_guarded_under_autoflush_false(db_session) -> None:
    """2026-08-19 用于验证生产配置（autoflush=False）下同章关系不重复写状态

    测试通过独立 autoflush=False 会话复现生产路径，确认章节复合主键约束保持稳定
    """
    from sqlalchemy.orm import sessionmaker

    engine = db_session.get_bind()
    session = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)()
    try:
        _novel_id, run_id = create_run_with_chunks(
            session,
            texts=["林渡与顾霜并肩迎敌"],
            title="同章断言加案例解决-autoflush-off",
        )
        persist_chapter_annotation(
            session,
            run_id=run_id,
            chapter_id=1,
            characters=[
                character_fact(chunk_id=1, name="林渡", action="迎敌"),
                character_fact(chunk_id=1, name="顾霜", action="迎敌"),
            ],
            relations=[
                relation_fact(
                    chunk_id=1,
                    from_name="林渡",
                    to_name="顾霜",
                    relation_type="盟友",
                )
            ],
            resolved_cases=[
                ResolvedCase(
                    case_id="case-autoflush-off",
                    action="fact",
                    type="relation_change",
                    reason="同一人物归并",
                    target_key="target-alias",
                    target_ref={"kind": "relation_change", "chunk_id": 1},
                    from_entity="林渡",
                    to_entity="顾霜",
                    relation_type="盟友",
                    change_kind="assert",
                )
            ],
        )
        # persist_chapter_annotation 已 commit；此处再确认无唯一约束冲突提交成功
        session.commit()

        states = list(
            session.execute(
                select(RelationState).where(RelationState.run_id == run_id)
            ).scalars()
        )
        assert len(states) == 1
        assert states[0].chapter_id == 1
        assert [change["change_kind"] for change in states[0].changes] == [
            "assert",
            "assert",
        ]
    finally:
        session.close()


def test_persist_writes_event_shadow_node_with_deterministic_id(db_session) -> None:
    """2026-08-18 用于验证持久化在同一事务写入 EventNode 影子行且 event_id 确定性生成"""
    text = "顾霜进入山门，持有玄剑，受天衡宗庇护，“住手”回荡。"
    _novel_id, run_id = create_run_with_chunks(
        db_session,
        texts=[text],
        title="事件影子写入",
    )
    _persist(db_session, run_id=run_id, text=text)
    db_session.commit()

    nodes = list(
        db_session.execute(
            select(EventNode).where(EventNode.run_id == run_id)
        ).scalars()
    )
    assert len(nodes) == 1
    node = nodes[0]
    expected_eid = str(uuid5(NAMESPACE_URL, f"noveliq:event:{run_id}:1:1"))
    assert node.event_id == expected_eid
    assert node.chapter_id == 1
    assert node.chapter_order == 1
    assert node.description == "顾霜进入山门"
    assert node.char_start == 0
    assert node.char_end == 10
    assert node.anchor_paragraph_ids == [0]
    assert node.causal_event_refs == []
    assert node.tree_id == "tree-main"
    assert node.cause_role == "root"
    assert node.source_kind == "annotation"
    assert node.payload_path == "chunks/1/events/1"
    assert len(node.evidence) == 1
    assert node.evidence[0]["paragraph_ids"] == [0]


def test_persist_writes_causal_edge_between_events(db_session) -> None:
    """2026-08-19 用于验证全局 event_id 因果引用写入 EventEdge causal 边（契约 v3）"""
    text = "顾霜进入山门。\n顾霜拔剑。"
    _novel_id, run_id = create_run_with_chunks(
        db_session,
        texts=[text],
        title="因果边写入",
    )
    eid1 = str(uuid5(NAMESPACE_URL, f"noveliq:event:{run_id}:1:1"))
    persist_chapter_annotation(
        db_session,
        run_id=run_id,
        chapter_id=1,
        events=[
            {
                "description": "顾霜进入山门",
                "participants": ["顾霜"],
                "anchor_paragraph_ids": [0],
                "tree_id": "gate-entry",
                "cause_role": "root",
            },
            {
                "description": "顾霜拔剑",
                "participants": ["顾霜"],
                "anchor_paragraph_ids": [1],
                "causal_event_refs": [eid1],
                "tree_id": "gate-entry",
                "cause_role": "main",
            },
        ],
    )
    db_session.commit()

    edges = list(
        db_session.execute(
            select(EventEdge).where(
                EventEdge.run_id == run_id,
                EventEdge.edge_type == "causal",
            )
        ).scalars()
    )
    assert len(edges) == 1
    edge = edges[0]
    eid2 = str(uuid5(NAMESPACE_URL, f"noveliq:event:{run_id}:1:2"))
    assert edge.source_event_id == eid1
    assert edge.target_event_id == eid2
    assert edge.is_active == 1
    assert edge.source_chapter_id == 1
    assert edge.target_chapter_id == 1

    # 事件事实也应链接 event_id
    event_facts = list(
        db_session.execute(
            select(GraphFact).where(
                GraphFact.run_id == run_id,
                GraphFact.fact_type == "event",
            )
        ).scalars()
    )
    assert len(event_facts) == 2
    assert {fact.event_id for fact in event_facts} == {eid1, eid2}


def test_persist_does_not_materialize_contains_edges(db_session) -> None:
    """2026-08-19 用于验证契约 v3：contains 不再落表，event_edges 只有 causal 边"""
    text = "顾霜进入山门。\n顾霜拔剑。"
    _novel_id, run_id = create_run_with_chunks(
        db_session,
        texts=[text],
        title="contains 派生化",
    )
    eid1 = str(uuid5(NAMESPACE_URL, f"noveliq:event:{run_id}:1:1"))
    persist_chapter_annotation(
        db_session,
        run_id=run_id,
        chapter_id=1,
        events=[
            {
                "description": "顾霜进入山门",
                "participants": ["顾霜"],
                "anchor_paragraph_ids": [0],
                "tree_id": "gate-entry",
                "cause_role": "root",
            },
            {
                "description": "顾霜拔剑",
                "participants": ["顾霜"],
                "anchor_paragraph_ids": [1],
                "causal_event_refs": [eid1],
                "tree_id": "gate-entry",
                "cause_role": "main",
            },
        ],
    )
    db_session.commit()

    edge_types = set(
        db_session.execute(
            select(EventEdge.edge_type).where(EventEdge.run_id == run_id)
        ).scalars()
    )
    assert edge_types == {"causal"}
    assert "contains" not in edge_types


def test_persist_writes_cross_chapter_causal_edge(db_session) -> None:
    """2026-08-19 用于验证跨章事件引用写入跨章 causal 边（契约 v3 树间/树内跨章）"""
    _novel_id, run_id = create_run_with_chunks(
        db_session,
        texts=["顾霜立誓。", "顾霜兑现承诺。"],
        chapter_ids=[1, 2],
        title="跨章因果边",
    )
    eid1 = str(uuid5(NAMESPACE_URL, f"noveliq:event:{run_id}:1:1"))
    eid2 = str(uuid5(NAMESPACE_URL, f"noveliq:event:{run_id}:2:1"))
    persist_chapter_annotation(
        db_session,
        run_id=run_id,
        chapter_id=1,
        events=[
            {
                "description": "顾霜立誓",
                "participants": ["顾霜"],
                "anchor_paragraph_ids": [0],
                "tree_id": "oath",
                "cause_role": "root",
            },
        ],
    )
    persist_chapter_annotation(
        db_session,
        run_id=run_id,
        chapter_id=2,
        events=[
            {
                "description": "顾霜兑现承诺",
                "participants": ["顾霜"],
                "anchor_paragraph_ids": [0],
                "causal_event_refs": [eid1],
                "tree_id": "oath",
                "cause_role": "main",
            },
        ],
    )
    db_session.commit()

    edges = list(
        db_session.execute(
            select(EventEdge).where(
                EventEdge.run_id == run_id,
                EventEdge.edge_type == "causal",
            )
        ).scalars()
    )
    assert len(edges) == 1
    assert edges[0].source_event_id == eid1
    assert edges[0].target_event_id == eid2
    assert edges[0].source_chapter_id == 1
    assert edges[0].target_chapter_id == 2


def test_dag_acyclic_validation_rejects_cycle() -> None:
    """2026-08-19 用于验证因果边成环时 DAG 无环校验抛 ValueError（契约 v3：event_id 引用）"""
    event_metas = [
        {"event_id": "e1", "causal_event_refs": ["e2"]},
        {"event_id": "e2", "causal_event_refs": ["e1"]},
    ]
    with pytest.raises(ValueError, match="DAG 无环校验失败"):
        _validate_dag_acyclic(event_metas)


def test_dag_acyclic_validation_passes_for_acyclic() -> None:
    """2026-08-19 用于验证无环因果图通过 DAG 校验（含多因节点）"""
    event_metas = [
        {"event_id": "e1", "causal_event_refs": []},
        {"event_id": "e2", "causal_event_refs": ["e1"]},
        {"event_id": "e3", "causal_event_refs": ["e1", "e2"]},
    ]
    _validate_dag_acyclic(event_metas)
