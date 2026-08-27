"""动作式案例解决持久化集成测试（fact/foreshadowing/close）"""

from __future__ import annotations

import pytest
from sqlalchemy import select
from sqlalchemy.orm import sessionmaker

from src.agents.annotation.schema import (
    AgentRunAudit,
    AgentRunResult,
    BoundChapterAnnotation,
    BoundChunkAnnotation,
    BoundDialogue,
    BoundEntity,
    BoundEntityDirectory,
    BoundEvent,
    BoundForeshadowing,
    ChunkMetricsInput,
    PendingCase,
    ResolvedCase,
)
from src.storage.models import (
    CasePoolCase,
    CaseResolutionMapping,
    DialogueRecord,
    ForeshadowingThread,
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
    entity_names: list[str] | None = None,
    foreshadowing: BoundForeshadowing | None = None,
) -> BoundChapterAnnotation:
    """2026-08-11 用于构造含实体目录或伏笔的章节标注

    2026-08-18：伏笔需要绑定 setup 事件，因此当 foreshadowing 非 None 时
    自动构造一个锚定整个 chunk 文本的 BoundEvent；2026-08-22 下
    伏笔 setup_node_id 直接指向该事件节点 id。
    """
    entities = [
        BoundEntity(
            name=name,
            entity_type="character",
        )
        for name in (entity_names or [])
    ]
    events: list[BoundEvent] = []
    if foreshadowing is not None:
        # setup_node_id 直接指向本章事件节点 id
        setup_node_id = f"evt-setup-{chunk_id}"
        events.append(
            BoundEvent(
                node_id=setup_node_id,
                tree_id=f"tree-{chunk_id}",
                parent_node_id=None,
                cause_role="root",
                description=f"事件-{text[:6]}",
                participants=[],
                causal_event_refs=[],
            )
        )
        foreshadowing = foreshadowing.model_copy(update={"setup_node_id": setup_node_id})
    return BoundChapterAnnotation(
        chapter_summary=text,
        chunks=[
            BoundChunkAnnotation(
                chunk_id=chunk_id,
                metrics=ChunkMetricsInput(
                    summary=text,
                    emotional_valence="neutral",
                    narrative_function="铺垫",
                ),
                entities=BoundEntityDirectory(entities=entities),
                character_observations=[],
                dialogues=[],
                events=events,
                relations=[],
                foreshadowings=[foreshadowing] if foreshadowing is not None else [],
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
) -> AgentRunResult:
    """2026-08-11 用于构造完成事务 AgentRunResult"""
    return AgentRunResult(
        run_id=run_id,
        chapter_id=chapter_id,
        annotation=annotation,
        resolved_cases=resolved_cases or [],
        pushed_cases=pushed_cases or [],
        audit=AgentRunAudit(
            allow_future_context=False,
            write_records=[],
            rotation_case_ids=[],
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
            annotation=_annotation(chunk_id=1, text="顾霜与顾老同时出现", entity_names=["顾霜", "顾老"]),
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
            annotation=_annotation(chunk_id=2, text="顾霜自称顾老", entity_names=["顾霜"]),
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
            annotation=_annotation(chunk_id=1, text="顾霜与顾老同时出现", entity_names=["顾霜", "顾老"]),
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
    assert mapping.target_setup_id is None
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
            annotation=_annotation(chunk_id=1, text="顾霜与顾老同时出现", entity_names=["顾霜", "顾老"]),
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
            annotation=_annotation(chunk_id=2, text="顾霜自称顾老", entity_names=["顾霜"]),
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
            annotation=_annotation(chunk_id=1, text="顾霜与顾老同时出现", entity_names=["顾霜", "顾老"]),
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
                annotation=_annotation(chunk_id=2, text="顾霜自称顾老", entity_names=["顾霜"]),
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
            annotation=_annotation(chunk_id=1, text="顾霜喝道", entity_names=["顾霜"]),
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
                annotation=_annotation(chunk_id=2, text="顾霜喝道", entity_names=["顾霜"]),
                resolved_cases=[resolved],
                authorized_chunk_ids=[1, 2],
            ),
            session_factory=sessionmaker(bind=db_session.get_bind(), expire_on_commit=False),
        )
    db_session.rollback()
    row = db_session.get(CasePoolCase, "missing-dialogue-case")
    assert row is not None and row.state == "active"


def test_foreshadowing_action_updates_thread_by_setup_id(db_session) -> None:
    """2026-08-11 用于验证伏笔线程默认字段与 foreshadowing 动作按 setup_id 更新"""
    novel_id, run_id = create_run_with_chunks(
        db_session,
        texts=["顾霜立誓", "顾霜屡次立誓"],
        chapter_ids=[1, 2],
        title="伏笔解决",
    )
    foreshadowing = BoundForeshadowing(
        description="顾霜承诺护佑山门",
        confidence="high",
        setup_node_id="evt-setup-1",
    )
    first = complete_annotation_run(
        result=_result(
            run_id=run_id,
            chapter_id=1,
            annotation=_annotation(
                chunk_id=1,
                text="顾霜立誓",
                foreshadowing=foreshadowing,
            ),
        ),
        session_factory=sessionmaker(bind=db_session.get_bind(), expire_on_commit=False),
    )
    db_session.rollback()
    thread = db_session.execute(select(ForeshadowingThread).where(ForeshadowingThread.run_id == run_id)).scalar_one()
    assert thread.setup_summary == "顾霜承诺护佑山门"
    # P3：create_event(isforeshadowing) 仅写 description+confidence，其余枚举不再填哨兵默认值
    assert thread.foreshadowing_type is None
    assert thread.setup_kind is None
    assert thread.expected_payoff_family is None
    assert thread.payoff_likelihood is None
    assert thread.confidence == "high"
    assert thread.status == "open"
    assert thread.active is True
    pushed = PendingCase(
        type="foreshadowing_suspect",
        chunk_id=1,
        keys=["护佑山门"],
        description="伏笔疑点",
        target_key="pushed-foreshadowing",
        target_ref={
            "kind": "foreshadowing_suspect",
            "setup_id": thread.setup_id,
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
    resolved = ResolvedCase(
        case_id="foreshadowing-case",
        action="foreshadowing",
        type="foreshadowing_suspect",
        setup_status="reinforced",
        payoff_likelihood="high",
        reason="后续章节强化承诺",
        target_key=pushed.target_key,
        target_ref=dict(pushed.target_ref),
    )
    second = complete_annotation_run(
        result=_result(
            run_id=run_id,
            chapter_id=2,
            annotation=_annotation(chunk_id=2, text="顾霜屡次立誓"),
            resolved_cases=[resolved],
            authorized_chunk_ids=[1, 2],
        ),
        session_factory=sessionmaker(bind=db_session.get_bind(), expire_on_commit=False),
    )

    db_session.rollback()
    updated = db_session.execute(select(ForeshadowingThread).where(ForeshadowingThread.run_id == run_id)).scalar_one()
    mapping = db_session.execute(
        select(CaseResolutionMapping).where(
            CaseResolutionMapping.run_id == run_id,
            CaseResolutionMapping.case_id == "foreshadowing-case",
        )
    ).scalar_one()
    assert updated.setup_id == thread.setup_id
    assert updated.status == "reinforced"
    assert updated.payoff_likelihood == "high"
    assert mapping.target_setup_id == thread.setup_id
    assert mapping.resolution["action"] == "foreshadowing"
    assert second.resolved_cases[0].target_setup_id == thread.setup_id


def test_foreshadowing_same_setup_event_creates_single_thread(db_session) -> None:
    """2026-08-18 用于验证同章同 setup_event_id 重复 sync 只建一条线程（去重键=setup_event_id）

    新合同去重键从 description casefold 改为 setup_event_id：两章各自独立标注的
    setup 事件（chunk_id 不同 → setup_event_id 不同）是不同线程，不再按描述去重。
    此测试验证同章同事件重复 sync 的幂等行为。
    """
    novel_id, run_id = create_run_with_chunks(
        db_session,
        texts=["顾霜立誓", "顾霜再誓"],
        chapter_ids=[1, 2],
        title="伏笔去重",
    )
    factory = sessionmaker(bind=db_session.get_bind(), expire_on_commit=False)
    foreshadowing = BoundForeshadowing(
        description="顾霜承诺护佑山门",
        confidence="high",
        setup_node_id="evt-setup-1",
    )
    # 章 1 同一伏笔连续两次完成事务（模拟重跑）：setup_event_id 相同 → 只建一条线程
    for _ in range(2):
        complete_annotation_run(
            result=_result(
                run_id=run_id,
                chapter_id=1,
                annotation=_annotation(
                    chunk_id=1,
                    text="顾霜立誓",
                    foreshadowing=foreshadowing,
                ),
            ),
            session_factory=factory,
        )
        db_session.rollback()

    threads = list(
        db_session.execute(select(ForeshadowingThread).where(ForeshadowingThread.run_id == run_id)).scalars()
    )
    assert len(threads) == 1
    assert threads[0].setup_summary == "顾霜承诺护佑山门"
    assert threads[0].foreshadowing_type is None
    assert threads[0].status == "open"


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
                    emotional_valence="neutral",
                    narrative_function="冲突",
                ),
                entities=BoundEntityDirectory(entities=[BoundEntity(name="顾霜", entity_type="character")]),
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
                relations=[],
                foreshadowings=[],
            )
        ],
    )
    complete_annotation_run(
        result=_result(run_id=run_id, chapter_id=1, annotation=annotation),
        session_factory=sessionmaker(bind=db_session.get_bind(), expire_on_commit=False),
    )
    db_session.rollback()

    row = db_session.execute(select(DialogueRecord).where(DialogueRecord.run_id == run_id)).scalar_one()
    expected_eid = "evt-dialogue-anchor"
    assert row.event_id == expected_eid
