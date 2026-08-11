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
    BoundEntity,
    BoundEntityDirectory,
    BoundForeshadowing,
    ChunkMetricsInput,
    PendingCase,
    ResolvedCase,
)
from src.storage.models import (
    CasePoolCase,
    CaseResolutionMapping,
    ForeshadowingThread,
    GraphFact,
    GraphRelationVersion,
)
from src.storage.repositories import CasePoolRepository
from src.workflows.annotate_helpers.storage import complete_annotation_run
from tests.support.chapter_annotation_helpers import create_run_with_chunks, evidence


def _annotation(
    *,
    chunk_id: int,
    text: str,
    entity_names: list[str] | None = None,
    foreshadowing: BoundForeshadowing | None = None,
) -> BoundChapterAnnotation:
    """2026-08-11 用于构造含实体目录或伏笔的章节标注"""
    entities = [
        BoundEntity(
            name=name,
            entity_type="character",
            confidence="high",
            reason=f"{name}出现",
            evidence=evidence(f"{name}出现", chunk_id),
        )
        for name in (entity_names or [])
    ]
    return BoundChapterAnnotation(
        chapter_summary=text,
        chunks=[
            BoundChunkAnnotation(
                chunk_id=chunk_id,
                metrics=ChunkMetricsInput(
                    summary=text,
                    emotional_valence="neutral",
                    narrative_function="铺垫",
                    confidence="high",
                    reason="摘要",
                ),
                entities=BoundEntityDirectory(entities=entities),
                character_observations=[],
                dialogues=[],
                events=[],
                relations=[],
                states=[],
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
            write_revisions=[],
            rotation_case_ids=[],
            authorized_text_chunk_ids=[annotation.chunks[0].chunk_id],
        ),
    )


def _alias_case(
    db_session,
    *,
    run_id: str,
    annotation_id: str,
    name_a: str,
    name_b: str,
) -> CasePoolCase:
    """2026-08-11 用于直接登记疑似同一人物案例"""
    return CasePoolRepository(db_session).create_case(
        run_id=run_id,
        annotation_id=annotation_id,
        pending_case=PendingCase(
            type="entity_alias",
            chunk_id=0,
            keys=[name_a, name_b, "同一人物"],
            description=f"疑似同一人物：{name_a} 与 {name_b}",
            target_key=f"alias-{name_a}-{name_b}",
            target_ref={"kind": "entity_alias", "name_a": name_a, "name_b": name_b},
            evidence=evidence("共享邻居较高", 0),
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
            annotation=_annotation(chunk_id=0, text="顾霜与顾老同时出现", entity_names=["顾霜", "顾老"]),
        ),
        novel_id=novel_id,
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
        evidence_chunk_id=1,
        target_key=case.target_key,
        target_ref=dict(case.target_ref),
    )
    second = complete_annotation_run(
        result=_result(
            run_id=run_id,
            chapter_id=2,
            annotation=_annotation(chunk_id=1, text="顾霜自称顾老", entity_names=["顾霜"]),
            resolved_cases=[resolved],
        ),
        novel_id=novel_id,
        session_factory=sessionmaker(bind=db_session.get_bind(), expire_on_commit=False),
    )

    db_session.rollback()
    fact = db_session.execute(
        select(GraphFact).where(
            GraphFact.run_id == run_id,
            GraphFact.source_kind == "case_resolution",
        )
    ).scalar_one()
    relation_version = db_session.execute(
        select(GraphRelationVersion).where(
            GraphRelationVersion.run_id == run_id,
            GraphRelationVersion.relation_id == fact.content["relation_id"],
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
    assert relation_version.is_active is True
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
            annotation=_annotation(chunk_id=0, text="顾霜与顾老同时出现", entity_names=["顾霜", "顾老"]),
        ),
        novel_id=novel_id,
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
        evidence_chunk_id=1,
        target_key=case.target_key,
        target_ref=dict(case.target_ref),
    )
    second = complete_annotation_run(
        result=_result(
            run_id=run_id,
            chapter_id=2,
            annotation=_annotation(chunk_id=1, text="顾老实为夫妻"),
            resolved_cases=[resolved],
        ),
        novel_id=novel_id,
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
            annotation=_annotation(chunk_id=0, text="顾霜喝道", entity_names=["顾霜"]),
        ),
        novel_id=novel_id,
        session_factory=sessionmaker(bind=db_session.get_bind(), expire_on_commit=False),
    )
    db_session.rollback()
    pushed = PendingCase(
        type="dialogue_speaker",
        chunk_id=0,
        keys=["顾霜"],
        description="对话疑点",
        target_key="missing-dialogue-target",
        target_ref={"kind": "dialogue_speaker", "dialogue_id": "dlg_not_exist", "chunk_id": 0},
        evidence=evidence("对话疑点", 0),
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
        evidence_chunk_id=1,
        target_key=pushed.target_key,
        target_ref=dict(pushed.target_ref),
    )
    with pytest.raises(ValueError, match="案例目标对话记录不存在或跨 run"):
        complete_annotation_run(
            result=_result(
                run_id=run_id,
                chapter_id=2,
                annotation=_annotation(chunk_id=1, text="顾霜喝道", entity_names=["顾霜"]),
                resolved_cases=[resolved],
            ),
            novel_id=novel_id,
            session_factory=sessionmaker(bind=db_session.get_bind(), expire_on_commit=False),
        )
    db_session.rollback()
    row = db_session.get(CasePoolCase, "missing-dialogue-case")
    assert row is not None and row.state == "active"


def test_foreshadowing_action_updates_thread_by_setup_id(db_session) -> None:
    """2026-08-11 用于验证 foreshadowing 动作按 setup_id 更新线程字段"""
    novel_id, run_id = create_run_with_chunks(
        db_session,
        texts=["顾霜立誓", "顾霜屡次立誓"],
        chapter_ids=[1, 2],
        title="伏笔解决",
    )
    foreshadowing = BoundForeshadowing(
        foreshadowing_type="对话",
        setup_kind="明确承诺",
        setup_summary="顾霜承诺护佑山门",
        why_unresolved_now="本章尚未兑现",
        expected_payoff_family="守护",
        payoff_likelihood="medium",
        setup_status="open",
        confidence="high",
        reason="承诺伏笔",
        evidence=evidence("承诺尚待兑现", 0),
    )
    first = complete_annotation_run(
        result=_result(
            run_id=run_id,
            chapter_id=1,
            annotation=_annotation(
                chunk_id=0,
                text="顾霜立誓",
                foreshadowing=foreshadowing,
            ),
        ),
        novel_id=novel_id,
        session_factory=sessionmaker(bind=db_session.get_bind(), expire_on_commit=False),
    )
    db_session.rollback()
    thread = db_session.execute(
        select(ForeshadowingThread).where(ForeshadowingThread.run_id == run_id)
    ).scalar_one()
    pushed = PendingCase(
        type="foreshadowing_suspect",
        chunk_id=0,
        keys=["护佑山门"],
        description="伏笔疑点",
        target_key="pushed-foreshadowing",
        target_ref={"kind": "foreshadowing_suspect", "setup_id": thread.setup_id},
        evidence=evidence("伏笔疑点", 0),
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
        evidence_chunk_id=1,
        target_key=pushed.target_key,
        target_ref=dict(pushed.target_ref),
    )
    second = complete_annotation_run(
        result=_result(
            run_id=run_id,
            chapter_id=2,
            annotation=_annotation(chunk_id=1, text="顾霜屡次立誓"),
            resolved_cases=[resolved],
        ),
        novel_id=novel_id,
        session_factory=sessionmaker(bind=db_session.get_bind(), expire_on_commit=False),
    )

    db_session.rollback()
    updated = db_session.execute(
        select(ForeshadowingThread).where(ForeshadowingThread.run_id == run_id)
    ).scalar_one()
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
