"""动作式案例解决持久化集成测试（fact/foreshadowing/close）"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select
from sqlalchemy.orm import sessionmaker

from src.agents.annotation.schema import (
    AgentRunAudit,
    AgentRunResult,
    BoundChapterAnnotation,
    BoundChunkAnnotation,
    BoundDialogue,
    BoundEvent,
    ChunkMetricsInput,
    PendingCase,
    ResolvedCase,
)
from src.storage.models import (
    CasePoolCase,
    CaseResolutionMapping,
    DialogueRecord,
    EventEdge,
    EventNode,
    GraphFact,
    RelationState,
)
from src.storage.repositories import CasePoolRepository
from src.workflows.annotate_helpers.storage import complete_annotation_run
from tests.support.chapter_annotation_helpers import create_run_with_chunks


def _annotation(
    *,
    chunk_id: int,
    text: str,
    foreshadowing: bool = False,
    event_node_ids: list[str] | None = None,
) -> BoundChapterAnnotation:
    """2026-09-13 用于构造章节标注（foreshadowing=True 时附带伏笔树根事件）

    伏笔即事件树：根事件 is_foreshadow_setup=True 即伏笔树根，不再有独立伏笔载荷。
    """
    events: list[BoundEvent] = []
    for node_id in event_node_ids or []:
        events.append(
            BoundEvent(
                node_id=node_id,
                tree_id=f"tree-{node_id}",
                parent_node_id=None,
                cause_role="root",
                description=f"事件-{text[:6]}",
                participants=[],
                causal_event_refs=[],
            )
        )
    if foreshadowing:
        # EventNode.event_id 是全库主键（非按 run 隔离），测试间必须唯一，
        # 否则 persist 的 session.get 会命中上一测试的节点而静默跳过写入
        events.append(
            BoundEvent(
                node_id=f"evt-setup-{chunk_id}-{uuid.uuid4().hex[:8]}",
                tree_id=f"tree-{chunk_id}-{uuid.uuid4().hex[:8]}",
                parent_node_id=None,
                cause_role="root",
                description=f"事件-{text[:6]}",
                participants=[],
                causal_event_refs=[],
                is_foreshadow_setup=True,
                expected_payoff_family="守护",
                payoff_likelihood="high",
            )
        )
    return BoundChapterAnnotation(
        chapter_summary=text,
        chunks=[
            BoundChunkAnnotation(
                chunk_id=chunk_id,
                metrics=ChunkMetricsInput(
                    summary=text,
                    emotional_valence=0,
                    narrative_function="铺垫",
                ),
                character_observations=[],
                dialogues=[],
                events=events,
            )
        ],
    )


def _result(
    *,
    run_id: str,
    chapter_id: int,
    annotation: BoundChapterAnnotation,
    resolved_cases: list[ResolvedCase] | None = None,
    pushed_cases: list[PendingCase] | None = None,
    authorized_chunk_ids: list[int] | None = None,
    entity_names: list[str] | None = None,
) -> AgentRunResult:
    """2026-08-11 用于构造完成事务 AgentRunResult

    2026-09-04 单一写面：实体经 entity_ops 走操作日志（不再有 payload 图副本）。
    """
    return AgentRunResult(
        run_id=run_id,
        chapter_id=chapter_id,
        annotation=annotation,
        resolved_cases=resolved_cases or [],
        pushed_cases=pushed_cases or [],
        entity_ops=[
            {
                "name": name,
                "entity_type": "character",
                "tags": [],
                "description": None,
                "attributes": {},
                "chapter_id": chapter_id,
            }
            for name in entity_names or []
        ],
        audit=AgentRunAudit(
            allow_future_context=False,
            write_records=[],
            authorized_chapter_ids=authorized_chunk_ids or [annotation.chunks[0].chunk_id],
            authorized_text_paragraph_ids=[],
        ),
    )


def _alias_case(
    db_session,
    *,
    run_id: str,
    annotation_id: str,
    name_a: str,
    name_b: str,
    chunk_id: int = 1,
) -> CasePoolCase:
    """2026-08-11 用于直接登记疑似同一人物案例"""
    return CasePoolRepository(db_session).create_case(
        run_id=run_id,
        annotation_id=annotation_id,
        pending_case=PendingCase(
            type="entity_alias",
            chunk_id=chunk_id,
            keys=[name_a, name_b, "同一人物"],
            description=f"疑似同一人物：{name_a} 与 {name_b}",
            target_key=f"alias-{name_a}-{name_b}",
            target_ref={
                "kind": "entity_alias",
                "name_a": name_a,
                "name_b": name_b,
                "chunk_id": chunk_id,
            },
        ),
    )


def test_fact_action_asserts_same_character_relation(db_session) -> None:
    """2026-08-11 用于验证 fact 动作把别名确认写成同一人物关系事实与版本"""
    novel_id, run_id = create_run_with_chunks(
        db_session,
        texts=["顾霜与顾老同时出现", "顾霜自称顾老"],
        chapter_ids=[1, 2],
        title="别名解决",
    )
    first = complete_annotation_run(
        result=_result(
            run_id=run_id,
            chapter_id=1,
            annotation=_annotation(chunk_id=1, text="顾霜与顾老同时出现"),
            entity_names=["顾霜", "顾老"],
        ),
        session_factory=sessionmaker(bind=db_session.get_bind(), expire_on_commit=False),
    )
    db_session.rollback()
    case = _alias_case(
        db_session,
        run_id=run_id,
        annotation_id=first.annotation_id,
        name_a="顾霜",
        name_b="顾老",
    )
    db_session.commit()
    resolved = ResolvedCase(
        case_id=case.id,
        action="fact",
        type=case.case_type,
        from_entity="顾霜",
        to_entity="顾老",
        relation_type="同一人物",
        change_kind="assert",
        reason="姓名指向同一人",
        target_key=case.target_key,
        target_ref=dict(case.target_ref),
    )
    second = complete_annotation_run(
        result=_result(
            run_id=run_id,
            chapter_id=2,
            annotation=_annotation(chunk_id=2, text="顾霜自称顾老"),
            entity_names=["顾霜"],
            resolved_cases=[resolved],
            authorized_chunk_ids=[1, 2],
        ),
        session_factory=sessionmaker(bind=db_session.get_bind(), expire_on_commit=False),
    )

    db_session.rollback()
    fact = db_session.execute(
        select(GraphFact).where(
            GraphFact.run_id == run_id,
            GraphFact.source_kind == "case_resolution",
        )
    ).scalar_one()
    relation_state = db_session.execute(
        select(RelationState).where(
            RelationState.run_id == run_id,
            RelationState.relation_id == fact.content["relation_id"],
            RelationState.chapter_id == fact.chapter_id,
        )
    ).scalar_one()
    mapping = db_session.execute(
        select(CaseResolutionMapping).where(
            CaseResolutionMapping.run_id == run_id,
            CaseResolutionMapping.case_id == case.id,
        )
    ).scalar_one()

    assert fact.fact_type == "relation"
    assert fact.predicate == "同一人物"
    assert fact.content["change_kind"] == "assert"
    assert relation_state.is_active is True
    assert mapping.target_fact_id == fact.fact_id
    assert mapping.resolution["action"] == "fact"
    assert second.resolved_cases[0].action == "fact"
    assert second.resolved_cases[0].target_fact_id == fact.fact_id


def test_close_action_only_closes_case_without_graph_change(db_session) -> None:
    """2026-08-11 用于验证 close 动作只关闭案例不产生任何事实"""
    novel_id, run_id = create_run_with_chunks(
        db_session,
        texts=["顾霜与顾老同时出现", "顾老实为夫妻"],
        chapter_ids=[1, 2],
        title="关闭案例",
    )
    first = complete_annotation_run(
        result=_result(
            run_id=run_id,
            chapter_id=1,
            annotation=_annotation(chunk_id=1, text="顾霜与顾老同时出现"),
            entity_names=["顾霜", "顾老"],
        ),
        session_factory=sessionmaker(bind=db_session.get_bind(), expire_on_commit=False),
    )
    db_session.rollback()
    case = _alias_case(
        db_session,
        run_id=run_id,
        annotation_id=first.annotation_id,
        name_a="顾霜",
        name_b="顾老",
    )
    db_session.commit()
    resolved = ResolvedCase(
        case_id=case.id,
        action="close",
        type=case.case_type,
        reason="夫妻关系非同一人物",
        target_key=case.target_key,
        target_ref=dict(case.target_ref),
    )
    second = complete_annotation_run(
        result=_result(
            run_id=run_id,
            chapter_id=2,
            annotation=_annotation(chunk_id=2, text="顾老实为夫妻"),
            resolved_cases=[resolved],
            authorized_chunk_ids=[1, 2],
        ),
        session_factory=sessionmaker(bind=db_session.get_bind(), expire_on_commit=False),
    )

    db_session.rollback()
    resolved_case = db_session.get(CasePoolCase, case.id)
    mapping = db_session.execute(
        select(CaseResolutionMapping).where(
            CaseResolutionMapping.run_id == run_id,
            CaseResolutionMapping.case_id == case.id,
        )
    ).scalar_one()
    assert resolved_case is not None and resolved_case.state == "resolved"
    assert mapping.target_fact_id is None
    assert mapping.target_dialogue_id is None
    assert mapping.target_root_event_id is None
    assert mapping.resolution["action"] == "close"
    assert second.resolved_cases[0].action == "close"


def test_fact_action_current_chapter_chunk_without_explicit_authorization(db_session) -> None:
    """2026-08-11 用于验证本章 chunk 案例解决无需显式读取授权（原文在本章上下文）"""
    novel_id, run_id = create_run_with_chunks(
        db_session,
        texts=["顾霜与顾老同时出现", "顾霜自称顾老"],
        chapter_ids=[1, 2],
        title="本章案例免授权",
    )
    first = complete_annotation_run(
        result=_result(
            run_id=run_id,
            chapter_id=1,
            annotation=_annotation(chunk_id=1, text="顾霜与顾老同时出现"),
            entity_names=["顾霜", "顾老"],
        ),
        session_factory=sessionmaker(bind=db_session.get_bind(), expire_on_commit=False),
    )
    db_session.rollback()
    case = _alias_case(
        db_session,
        run_id=run_id,
        annotation_id=first.annotation_id,
        name_a="顾霜",
        name_b="顾老",
        chunk_id=2,
    )
    db_session.commit()
    resolved = ResolvedCase(
        case_id=case.id,
        action="fact",
        type=case.case_type,
        from_entity="顾霜",
        to_entity="顾老",
        relation_type="同一人物",
        change_kind="assert",
        reason="姓名指向同一人",
        target_key=case.target_key,
        target_ref=dict(case.target_ref),
    )
    complete_annotation_run(
        result=_result(
            run_id=run_id,
            chapter_id=2,
            annotation=_annotation(chunk_id=2, text="顾霜自称顾老"),
            entity_names=["顾霜"],
            resolved_cases=[resolved],
            authorized_chunk_ids=[2],
        ),
        session_factory=sessionmaker(bind=db_session.get_bind(), expire_on_commit=False),
    )
    db_session.rollback()
    fact = db_session.execute(
        select(GraphFact).where(
            GraphFact.run_id == run_id,
            GraphFact.source_kind == "case_resolution",
        )
    ).scalar_one()
    assert fact.content["kind"] == "relation"


def test_fact_action_rejects_unauthorized_foreign_chunk(db_session) -> None:
    """2026-08-11 用于验证既非本章也未经读取授权的旧 chunk 案例解决仍被拒绝"""
    novel_id, run_id = create_run_with_chunks(
        db_session,
        texts=["顾霜与顾老同时出现", "顾霜自称顾老"],
        chapter_ids=[1, 2],
        title="旧章案例需授权",
    )
    first = complete_annotation_run(
        result=_result(
            run_id=run_id,
            chapter_id=1,
            annotation=_annotation(chunk_id=1, text="顾霜与顾老同时出现"),
            entity_names=["顾霜", "顾老"],
        ),
        session_factory=sessionmaker(bind=db_session.get_bind(), expire_on_commit=False),
    )
    db_session.rollback()
    case = _alias_case(
        db_session,
        run_id=run_id,
        annotation_id=first.annotation_id,
        name_a="顾霜",
        name_b="顾老",
    )
    db_session.commit()
    resolved = ResolvedCase(
        case_id=case.id,
        action="fact",
        type=case.case_type,
        from_entity="顾霜",
        to_entity="顾老",
        relation_type="同一人物",
        change_kind="assert",
        reason="姓名指向同一人",
        target_key=case.target_key,
        target_ref=dict(case.target_ref),
    )
    with pytest.raises(ValueError, match="未经系统读取授权"):
        complete_annotation_run(
            result=_result(
                run_id=run_id,
                chapter_id=2,
                annotation=_annotation(chunk_id=2, text="顾霜自称顾老"),
                entity_names=["顾霜"],
                resolved_cases=[resolved],
                authorized_chunk_ids=[2],
            ),
            session_factory=sessionmaker(bind=db_session.get_bind(), expire_on_commit=False),
        )
    db_session.rollback()


def test_dialogue_action_rejects_unknown_dialogue_target(db_session) -> None:
    """2026-08-11 用于验证 dialogue 动作目标不存在时整体回滚"""
    novel_id, run_id = create_run_with_chunks(
        db_session,
        texts=["顾霜喝道", "顾霜再喝"],
        chapter_ids=[1, 2],
        title="对话目标缺失",
    )
    first = complete_annotation_run(
        result=_result(
            run_id=run_id,
            chapter_id=1,
            annotation=_annotation(chunk_id=1, text="顾霜喝道"),
            entity_names=["顾霜"],
        ),
        session_factory=sessionmaker(bind=db_session.get_bind(), expire_on_commit=False),
    )
    db_session.rollback()
    pushed = PendingCase(
        type="dialogue_speaker",
        chunk_id=1,
        keys=["顾霜"],
        description="对话疑点",
        target_key="missing-dialogue-target",
        target_ref={"kind": "dialogue_speaker", "dialogue_id": "dlg_not_exist", "chunk_id": 1},
    )
    row = CasePoolRepository(db_session).create_case(
        run_id=run_id,
        annotation_id=first.annotation_id,
        pending_case=pushed,
    )
    row.id = "missing-dialogue-case"
    db_session.commit()
    resolved = ResolvedCase(
        case_id="missing-dialogue-case",
        action="dialogue",
        type="dialogue_speaker",
        speaker="顾霜",
        reason="后文点明",
        target_key=pushed.target_key,
        target_ref=dict(pushed.target_ref),
    )
    with pytest.raises(ValueError, match="案例目标对话记录不存在"):
        complete_annotation_run(
            result=_result(
                run_id=run_id,
                chapter_id=2,
                annotation=_annotation(chunk_id=2, text="顾霜喝道"),
                entity_names=["顾霜"],
                resolved_cases=[resolved],
                authorized_chunk_ids=[1, 2],
            ),
            session_factory=sessionmaker(bind=db_session.get_bind(), expire_on_commit=False),
        )
    db_session.rollback()
    row = db_session.get(CasePoolCase, "missing-dialogue-case")
    assert row is not None and row.state == "active"


def test_foreshadowing_action_binds_event_into_tree(db_session) -> None:
    """2026-09-13 用于验证 foreshadowing 动作把本章事件挂进伏笔树（foreshadowing 边）"""
    novel_id, run_id = create_run_with_chunks(
        db_session,
        texts=["顾霜立誓", "顾霜屡次立誓"],
        chapter_ids=[1, 2],
        title="伏笔解决",
    )
    first = complete_annotation_run(
        result=_result(
            run_id=run_id,
            chapter_id=1,
            annotation=_annotation(
                chunk_id=1,
                text="顾霜立誓",
                foreshadowing=True,
            ),
        ),
        session_factory=sessionmaker(bind=db_session.get_bind(), expire_on_commit=False),
    )
    db_session.rollback()
    root = db_session.execute(
        select(EventNode).where(
            EventNode.run_id == run_id,
            EventNode.is_foreshadowing_root.is_(True),
        )
    ).scalar_one()
    assert root.foreshadowing_status == "open"
    assert root.expected_payoff_family == "守护"
    assert root.payoff_likelihood == "high"
    pushed = PendingCase(
        type="foreshadowing_suspect",
        chunk_id=1,
        keys=["护佑山门"],
        description="伏笔疑点",
        target_key="pushed-foreshadowing",
        target_ref={
            "kind": "foreshadowing_suspect",
            "chunk_id": 1,
        },
    )
    row = CasePoolRepository(db_session).create_case(
        run_id=run_id,
        annotation_id=first.annotation_id,
        pending_case=pushed,
    )
    row.id = "foreshadowing-case"
    db_session.commit()
    bind_event_id = f"evt-ch2-bind-{uuid.uuid4().hex[:8]}"
    resolved = ResolvedCase(
        case_id="foreshadowing-case",
        action="foreshadowing",
        type="foreshadowing_suspect",
        foreshadowing_action="reinforce",
        foreshadowing_root_event_id=root.event_id,
        foreshadowing_event_id=bind_event_id,
        payoff_likelihood="high",
        reason="后续章节强化承诺",
        target_key=pushed.target_key,
        target_ref=dict(pushed.target_ref),
    )
    second = complete_annotation_run(
        result=_result(
            run_id=run_id,
            chapter_id=2,
            annotation=_annotation(chunk_id=2, text="顾霜屡次立誓", event_node_ids=[bind_event_id]),
            resolved_cases=[resolved],
            authorized_chunk_ids=[1, 2],
        ),
        session_factory=sessionmaker(bind=db_session.get_bind(), expire_on_commit=False),
    )

    db_session.rollback()
    updated = db_session.get(EventNode, root.event_id)
    edge = db_session.execute(
        select(EventEdge).where(
            EventEdge.run_id == run_id,
            EventEdge.edge_type == "foreshadowing",
        )
    ).scalar_one()
    mapping = db_session.execute(
        select(CaseResolutionMapping).where(
            CaseResolutionMapping.run_id == run_id,
            CaseResolutionMapping.case_id == "foreshadowing-case",
        )
    ).scalar_one()
    assert updated.foreshadowing_status == "reinforced"
    assert edge.source_event_id == root.event_id
    assert edge.target_event_id == bind_event_id
    assert mapping.target_root_event_id == root.event_id
    assert mapping.target_event_id == bind_event_id
    assert mapping.resolution["foreshadowing_action"] == "reinforce"
    assert second.resolved_cases[0].target_root_event_id == root.event_id


def test_foreshadowing_same_completion_replays_without_duplicate_edges(db_session) -> None:
    """2026-09-13 用于验证同章完成事务重放（load_completion_result 命中）不重复建根/挂边"""
    novel_id, run_id = create_run_with_chunks(
        db_session,
        texts=["顾霜立誓"],
        chapter_ids=[1],
        title="伏笔去重",
    )
    factory = sessionmaker(bind=db_session.get_bind(), expire_on_commit=False)
    for _ in range(2):
        complete_annotation_run(
            result=_result(
                run_id=run_id,
                chapter_id=1,
                annotation=_annotation(
                    chunk_id=1,
                    text="顾霜立誓",
                    foreshadowing=True,
                ),
            ),
            session_factory=factory,
        )
        db_session.rollback()

    roots = list(
        db_session.execute(
            select(EventNode).where(
                EventNode.run_id == run_id,
                EventNode.is_foreshadowing_root.is_(True),
            )
        ).scalars()
    )
    assert len(roots) == 1
    assert roots[0].foreshadowing_status == "open"


def test_foreshadowing_payoff_resolution_closes_tree(db_session) -> None:
    """2026-09-13 用于验证回收动作把伏笔树收束为 likely_paid_off 并记录映射"""
    novel_id, run_id = create_run_with_chunks(
        db_session,
        texts=["白芷立下守护之誓", "誓言兑现挡下袭击"],
        chapter_ids=[1, 2],
        title="疑点确认挂树",
    )
    factory = sessionmaker(bind=db_session.get_bind(), expire_on_commit=False)
    first = complete_annotation_run(
        result=_result(
            run_id=run_id,
            chapter_id=1,
            annotation=_annotation(
                chunk_id=1,
                text="白芷立下守护之誓",
                foreshadowing=True,
            ),
        ),
        session_factory=factory,
    )
    db_session.rollback()
    root = db_session.execute(
        select(EventNode).where(
            EventNode.run_id == run_id,
            EventNode.is_foreshadowing_root.is_(True),
        )
    ).scalar_one()
    pushed = PendingCase(
        type="foreshadowing_suspect",
        chunk_id=1,
        keys=["白芷", "守护之誓"],
        description="白芷誓言疑点",
        target_key="pushed-threadless",
        target_ref={"kind": "foreshadowing_suspect", "chunk_id": 1},
    )
    row = CasePoolRepository(db_session).create_case(
        run_id=run_id,
        annotation_id=first.annotation_id,
        pending_case=pushed,
    )
    row.id = "threadless-case"
    db_session.commit()
    payoff_event_id = f"evt-ch2-payoff-{uuid.uuid4().hex[:8]}"
    resolved = ResolvedCase(
        case_id="threadless-case",
        action="foreshadowing",
        type="foreshadowing_suspect",
        foreshadowing_action="payoff",
        foreshadowing_root_event_id=root.event_id,
        foreshadowing_event_id=payoff_event_id,
        reason="本章誓言兑现挡下袭击，疑点证实为伏笔回收",
        target_key=pushed.target_key,
        target_ref=dict(pushed.target_ref),
    )
    second = complete_annotation_run(
        result=_result(
            run_id=run_id,
            chapter_id=2,
            annotation=_annotation(chunk_id=2, text="誓言兑现挡下袭击", event_node_ids=[payoff_event_id]),
            resolved_cases=[resolved],
            authorized_chunk_ids=[1, 2],
        ),
        session_factory=factory,
    )

    db_session.rollback()
    updated = db_session.get(EventNode, root.event_id)
    edge = db_session.execute(
        select(EventEdge).where(
            EventEdge.run_id == run_id,
            EventEdge.edge_type == "foreshadowing",
        )
    ).scalar_one()
    mapping = db_session.execute(
        select(CaseResolutionMapping).where(
            CaseResolutionMapping.run_id == run_id,
            CaseResolutionMapping.case_id == "threadless-case",
        )
    ).scalar_one()
    assert updated.foreshadowing_status == "likely_paid_off"
    assert edge.target_event_id == payoff_event_id
    assert mapping.target_root_event_id == root.event_id
    assert mapping.resolution["foreshadowing_action"] == "payoff"
    assert second.resolved_cases[0].target_event_id == payoff_event_id
    assert novel_id


def test_completion_binds_dialogue_event_id_by_span(db_session) -> None:
    """2026-08-18 P3 用于验证 complete_annotation_run 落下对话事件弱关联"""
    novel_id, run_id = create_run_with_chunks(
        db_session,
        texts=["顾霜拔剑喝止，我们走。"],
        title="对话事件端到端",
    )
    annotation = BoundChapterAnnotation(
        chapter_summary="顾霜拔剑喝止",
        chunks=[
            BoundChunkAnnotation(
                chunk_id=1,
                metrics=ChunkMetricsInput(
                    summary="顾霜拔剑喝止",
                    emotional_valence=0,
                    narrative_function="冲突",
                ),
                character_observations=[],
                dialogues=[
                    BoundDialogue(
                        candidate_index=1,
                        candidate_key="dlg_001",
                        content="我们走",
                        start=7,
                        end=10,
                        speaker="顾霜",
                        tone="平静",
                    )
                ],
                events=[
                    BoundEvent(
                        node_id="evt-dialogue-anchor",
                        tree_id="tree-main",
                        parent_node_id=None,
                        cause_role="root",
                        description="顾霜拔剑喝止",
                        participants=[],
                        causal_event_refs=[],
                    )
                ],
            )
        ],
    )
    complete_annotation_run(
        result=_result(run_id=run_id, chapter_id=1, annotation=annotation, entity_names=["顾霜"]),
        session_factory=sessionmaker(bind=db_session.get_bind(), expire_on_commit=False),
    )
    db_session.rollback()

    row = db_session.execute(select(DialogueRecord).where(DialogueRecord.run_id == run_id)).scalar_one()
    expected_eid = "evt-dialogue-anchor"
    assert row.event_id == expected_eid
