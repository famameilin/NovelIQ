"""动作式案例解决持久化集成测试（fact/foreshadowing/close）"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select
from sqlalchemy.orm import sessionmaker

from src.agents.annotation.candidates import extract_dialogue_candidates
from src.agents.annotation.schema import (
    AgentRunAudit,
    AgentRunResult,
    BoundChapterAnnotation,
    BoundDialogue,
    BoundEvent,
    ChapterMetricsInput,
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
    chapter_id: int,
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
            )
        )
    if foreshadowing:
        # EventNode.event_id 是全库主键（非按 run 隔离），测试间必须唯一，
        # 否则 persist 的 session.get 会命中上一测试的节点而静默跳过写入
        events.append(
            BoundEvent(
                node_id=f"evt-setup-{chapter_id}-{uuid.uuid4().hex[:8]}",
                tree_id=f"tree-{chapter_id}-{uuid.uuid4().hex[:8]}",
                parent_node_id=None,
                cause_role="root",
                description=f"事件-{text[:6]}",
                participants=[],
                is_foreshadow_setup=True,
                payoff_likelihood="high",
            )
        )
    return BoundChapterAnnotation(
                metrics=ChapterMetricsInput(
                    summary=text,
                    emotional_valence=0,
                    narrative_function="铺垫",
                ),
                character_observations=[],
                dialogues=[],
                events=events,
    )


def _result(
    *,
    run_id: str,
    chapter_id: int,
    annotation: BoundChapterAnnotation,
    resolved_cases: list[ResolvedCase] | None = None,
    pushed_cases: list[PendingCase] | None = None,
    authorized_chapter_ids: list[int] | None = None,
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
            authorized_chapter_ids=authorized_chapter_ids or [chapter_id],
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
    chapter_id: int = 1,
) -> CasePoolCase:
    """2026-08-11 用于直接登记疑似同一人物案例

    2026-09-13 登记即进池后案例行 id 就是 target_key，而 id 是全库主键：
    target_key 加 uuid 后缀，避免跨用例复用同一名称组合时撞主键。
    """
    return CasePoolRepository(db_session).create_case(
        run_id=run_id,
        annotation_id=annotation_id,
        pending_case=PendingCase(
            type="entity_alias",
            chapter_id=chapter_id,
            keys=[name_a, name_b, "同一人物"],
            description=f"疑似同一人物：{name_a} 与 {name_b}",
            target_key=f"alias-{name_a}-{name_b}-{uuid.uuid4().hex[:8]}",
            target_ref={
                "kind": "entity_alias",
                "name_a": name_a,
                "name_b": name_b,
                "chapter_id": chapter_id,
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
            annotation=_annotation(chapter_id=1, text="顾霜与顾老同时出现"),
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
            annotation=_annotation(chapter_id=2, text="顾霜自称顾老"),
            entity_names=["顾霜"],
            resolved_cases=[resolved],
            authorized_chapter_ids=[1, 2],
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
            annotation=_annotation(chapter_id=1, text="顾霜与顾老同时出现"),
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
            annotation=_annotation(chapter_id=2, text="顾老实为夫妻"),
            resolved_cases=[resolved],
            authorized_chapter_ids=[1, 2],
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


def test_fact_action_current_chapter_without_explicit_authorization(db_session) -> None:
    """2026-08-11 用于验证本章案例解决无需显式读取授权（原文在本章上下文）"""
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
            annotation=_annotation(chapter_id=1, text="顾霜与顾老同时出现"),
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
        chapter_id=2,
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
            annotation=_annotation(chapter_id=2, text="顾霜自称顾老"),
            entity_names=["顾霜"],
            resolved_cases=[resolved],
            authorized_chapter_ids=[2],
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


def test_fact_action_rejects_unauthorized_foreign_chapter(db_session) -> None:
    """2026-08-11 用于验证既非本章也未经读取授权的旧章案例解决仍被拒绝"""
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
            annotation=_annotation(chapter_id=1, text="顾霜与顾老同时出现"),
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
    with pytest.raises(ValueError):
        complete_annotation_run(
            result=_result(
                run_id=run_id,
                chapter_id=2,
                annotation=_annotation(chapter_id=2, text="顾霜自称顾老"),
                entity_names=["顾霜"],
                resolved_cases=[resolved],
                authorized_chapter_ids=[2],
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
            annotation=_annotation(chapter_id=1, text="顾霜喝道"),
            entity_names=["顾霜"],
        ),
        session_factory=sessionmaker(bind=db_session.get_bind(), expire_on_commit=False),
    )
    db_session.rollback()
    pushed = PendingCase(
        type="dialogue_speaker",
        chapter_id=1,
        keys=["顾霜"],
        description="对话疑点",
        target_key="missing-dialogue-target",
        target_ref={"kind": "dialogue_speaker", "dialogue_id": "dlg_not_exist", "chapter_id": 1},
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
    with pytest.raises(ValueError):
        complete_annotation_run(
            result=_result(
                run_id=run_id,
                chapter_id=2,
                annotation=_annotation(chapter_id=2, text="顾霜喝道"),
                entity_names=["顾霜"],
                resolved_cases=[resolved],
                authorized_chapter_ids=[1, 2],
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
                chapter_id=1,
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
    # 2026-09-14 expected_payoff_family 列退役：伏笔根属性合同只剩三档 payoff_likelihood
    assert root.payoff_likelihood == "high"
    pushed = PendingCase(
        type="foreshadowing_suspect",
        chapter_id=1,
        keys=["护佑山门"],
        description="伏笔疑点",
        target_key="pushed-foreshadowing",
        target_ref={
            "kind": "foreshadowing_suspect",
            "chapter_id": 1,
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
            annotation=_annotation(chapter_id=2, text="顾霜屡次立誓", event_node_ids=[bind_event_id]),
            resolved_cases=[resolved],
            authorized_chapter_ids=[1, 2],
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
    # 2026-09-14 裁决携带的三档置信度写入根属性（family 更新路径退役后的对等覆盖）
    assert updated.payoff_likelihood == "high"
    assert edge.source_event_id == root.event_id
    assert edge.target_event_id == bind_event_id
    assert mapping.target_root_event_id == root.event_id
    assert mapping.target_event_id == bind_event_id
    assert mapping.resolution["foreshadowing_action"] == "reinforce"
    assert second.resolved_cases[0].target_root_event_id == root.event_id


def test_caseless_foreshadowing_attach_updates_root_attributes(db_session) -> None:
    """2026-09-19 写入路径挂边更新根属性：无案例的 foreshadowing 解决项带 payoff_likelihood/strength

    案例面收窄后本条目是唯一能改树根回收预期/强度的入口（`resolve_foreshadowing_case` 已删），
    落库层早就按这两个字段改根，此前写入路径不传值、等于没人喂；这里断言根列真的变了，
    且无案例条目照旧不写解决映射。
    """
    novel_id, run_id = create_run_with_chunks(
        db_session,
        texts=["顾霜立誓", "顾霜屡次立誓"],
        chapter_ids=[1, 2],
        title="写入路径挂边",
    )
    complete_annotation_run(
        result=_result(
            run_id=run_id,
            chapter_id=1,
            annotation=_annotation(chapter_id=1, text="顾霜立誓", foreshadowing=True),
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
    assert root.payoff_likelihood == "high"
    bind_event_id = f"evt-ch2-attach-{uuid.uuid4().hex[:8]}"
    second = complete_annotation_run(
        result=_result(
            run_id=run_id,
            chapter_id=2,
            annotation=_annotation(chapter_id=2, text="顾霜屡次立誓", event_node_ids=[bind_event_id]),
            resolved_cases=[
                ResolvedCase(
                    action="foreshadowing",
                    type="",
                    reason="本章回收预期下降",
                    target_key="",
                    target_ref={"chapter_id": 2},
                    foreshadowing_action="reinforce",
                    foreshadowing_root_event_id=root.event_id,
                    foreshadowing_event_id=bind_event_id,
                    payoff_likelihood="low",
                    strength="high",
                )
            ],
            authorized_chapter_ids=[1, 2],
        ),
        session_factory=sessionmaker(bind=db_session.get_bind(), expire_on_commit=False),
    )

    db_session.rollback()
    updated = db_session.get(EventNode, root.event_id)
    assert updated.payoff_likelihood == "low"
    assert updated.strength == "high"
    assert updated.foreshadowing_status == "reinforced"
    assert (
        db_session.execute(
            select(CaseResolutionMapping).where(CaseResolutionMapping.run_id == run_id)
        ).scalar_one_or_none()
        is None
    )
    assert second.resolved_cases == []


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
                    chapter_id=1,
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
                chapter_id=1,
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
        chapter_id=1,
        keys=["白芷", "守护之誓"],
        description="白芷誓言疑点",
        target_key="pushed-threadless",
        target_ref={"kind": "foreshadowing_suspect", "chapter_id": 1},
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
            annotation=_annotation(chapter_id=2, text="誓言兑现挡下袭击", event_node_ids=[payoff_event_id]),
            resolved_cases=[resolved],
            authorized_chapter_ids=[1, 2],
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
                metrics=ChapterMetricsInput(
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


def test_completion_binds_dialogue_only_to_event_in_its_paragraph(db_session) -> None:
    text = "顾霜拔剑。\n“我们走。”顾霜说道。"
    _novel_id, run_id = create_run_with_chunks(db_session, texts=[text], title="精确对话事件关联")
    candidate = extract_dialogue_candidates(1, text)[0]
    first_id = f"evt-first-{uuid.uuid4().hex[:8]}"
    second_id = f"evt-second-{uuid.uuid4().hex[:8]}"
    annotation = BoundChapterAnnotation(
        metrics=ChapterMetricsInput(summary="顾霜离开", emotional_valence=0, narrative_function="转折"),
        character_observations=[],
        dialogues=[
            BoundDialogue(
                candidate_index=1,
                candidate_key=candidate.candidate_key,
                content=candidate.content,
                start=candidate.start,
                end=candidate.end,
                speaker=None,
                tone=None,
            )
        ],
        events=[
            BoundEvent(
                node_id=first_id,
                tree_id="tree-dialogue-paragraph",
                parent_node_id=None,
                cause_role="root",
                description="顾霜拔剑",
                evidence_paragraph_id=0,
            ),
            BoundEvent(
                node_id=second_id,
                tree_id="tree-dialogue-paragraph",
                parent_node_id=first_id,
                cause_role="main",
                description="顾霜邀同行",
                evidence_paragraph_id=1,
            ),
        ],
    )
    complete_annotation_run(
        result=_result(run_id=run_id, chapter_id=1, annotation=annotation),
        session_factory=sessionmaker(bind=db_session.get_bind(), expire_on_commit=False),
    )
    db_session.rollback()

    row = db_session.execute(select(DialogueRecord).where(DialogueRecord.run_id == run_id)).scalar_one()
    assert row.event_id == second_id


def test_case_pushed_and_resolved_within_same_chapter(db_session) -> None:
    """2026-09-13 登记即进池：本章内 push_case 登记的案例可当章解决并落库为 resolved

    覆盖完成事务重排（先建推入案例的行、再锁行校验稳定目标）与"行 id 即 target_key"
    的标识一致性：解决映射的 case_id 直接指向该行，整条链无需任何 id 重映射。
    """
    novel_id, run_id = create_run_with_chunks(
        db_session,
        texts=["贺铮误认林立果为子"],
        chapter_ids=[1],
        title="同章推入即解决",
    )
    pushed = PendingCase(
        type="关系修正",
        chapter_id=1,
        keys=["贺铮", "林立果", "家族"],
        description="误建关系：二人并非父子，需解除该边",
        target_key="pushed-in-chapter-1",
        target_ref={"kind": "关系修正", "chapter_id": 1, "keys": ["贺铮", "林立果", "家族"]},
    )
    resolved = ResolvedCase(
        case_id=pushed.target_key,
        action="fact",
        type=pushed.type,
        from_entity="贺铮",
        to_entity="林立果",
        relation_type="家族",
        change_kind="assert",
        reason="同章内确认父子关系",
        target_key=pushed.target_key,
        target_ref=dict(pushed.target_ref),
    )

    completion = complete_annotation_run(
        result=_result(
            run_id=run_id,
            chapter_id=1,
            annotation=_annotation(chapter_id=1, text="贺铮误认林立果为子"),
            entity_names=["贺铮", "林立果"],
            pushed_cases=[pushed],
            resolved_cases=[resolved],
            authorized_chapter_ids=[1],
        ),
        session_factory=sessionmaker(bind=db_session.get_bind(), expire_on_commit=False),
    )

    db_session.rollback()
    case = db_session.execute(select(CasePoolCase).where(CasePoolCase.run_id == run_id)).scalar_one()
    fact = db_session.execute(
        select(GraphFact).where(
            GraphFact.run_id == run_id,
            GraphFact.source_kind == "case_resolution",
        )
    ).scalar_one()
    mapping = db_session.execute(
        select(CaseResolutionMapping).where(
            CaseResolutionMapping.run_id == run_id,
            CaseResolutionMapping.case_id == case.id,
        )
    ).scalar_one()

    # 推入的案例当章即被解决：行 id 就是 target_key，状态直接落 resolved
    assert case.id == pushed.target_key
    assert case.state == "resolved"
    assert fact.fact_type == "relation"
    assert fact.predicate == "家族"
    assert mapping.target_fact_id == fact.fact_id
    assert mapping.resolution["action"] == "fact"
    # 完成结果同时汇报"创建的案例"与"解决的案例"
    assert [item.id for item in completion.created_cases] == [pushed.target_key]
    assert [item.case_id for item in completion.resolved_cases] == [pushed.target_key]


def test_write_path_relation_changes_persist_as_caseless_facts(db_session) -> None:
    """2026-09-18 无案例的关系变化逐条落成关系事实，且每条的 fact_id 互异

    写入路径自发的变更（`ResolvedCase.case_id == ""`）没有案例 id 可做唯一键：键若仍按
    case_id 派生，同一章两条变更会撞同一个 fact_id（主键冲突=整章落库失败）。键里带该章
    变更日志序号后两条都在，来源标记为 write_path（不是案例裁决），且不写解决映射。
    """
    _novel_id, run_id = create_run_with_chunks(
        db_session,
        texts=["顾霜与顾老同场"],
        chapter_ids=[1],
        title="无案例变更",
    )
    changes = [
        ResolvedCase(
            case_id="",
            action="fact",
            type="",
            from_entity="顾霜",
            to_entity="顾老",
            relation_type="师徒",
            change_kind=change_kind,
            reason=f"本章正文确认的关系变化：{change_kind}",
            target_key="",
            target_ref={"chapter_id": 1, "change_index": index},
        )
        for index, change_kind in enumerate(("reinforce", "weaken"))
    ]
    complete_annotation_run(
        result=_result(
            run_id=run_id,
            chapter_id=1,
            annotation=_annotation(chapter_id=1, text="顾霜与顾老同场"),
            entity_names=["顾霜", "顾老"],
            resolved_cases=changes,
            authorized_chapter_ids=[1],
        ),
        session_factory=sessionmaker(bind=db_session.get_bind(), expire_on_commit=False),
    )

    db_session.rollback()
    facts = list(
        db_session.execute(
            select(GraphFact).where(
                GraphFact.run_id == run_id,
                GraphFact.source_kind == "write_path",
            )
        ).scalars()
    )
    assert len(facts) == 2
    assert len({fact.fact_id for fact in facts}) == 2
    assert {fact.predicate for fact in facts} == {"师徒"}
    assert {fact.content["change_kind"] for fact in facts} == {"reinforce", "weaken"}
    assert {fact.payload_path for fact in facts} == {"relation_change/1/0", "relation_change/1/1"}
    # 无案例的变更不写解决映射（只有案例裁决才有映射行）
    assert db_session.execute(
        select(CaseResolutionMapping).where(CaseResolutionMapping.run_id == run_id)
    ).scalars().all() == []
