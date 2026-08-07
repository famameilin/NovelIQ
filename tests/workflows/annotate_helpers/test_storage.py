"""章节标注原子完成事务测试"""

from __future__ import annotations

from unittest.mock import patch

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import sessionmaker

from src.agents.annotation.schema import (
    AgentRunAudit,
    AgentRunResult,
    ChapterFinish,
    PulledResult,
    PushedCase,
    SuccessAudit,
)
from src.storage.models import (
    CasePoolCase,
    CaseResolutionMapping,
    ChapterAnnotationRecord,
    GraphFact,
    GraphVersion,
    ModelInteraction,
    TokenUsage,
)
from src.workflows.annotate_helpers.storage import complete_annotation_run, load_completion_result
from tests.support.chapter_annotation_helpers import create_run_with_chunks


def _coverage(chunk_id: int) -> dict:
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


def _finish(
    *,
    chunk_id: int,
    text: str,
    unresolved_dialogue: bool = False,
    speaker_entity: bool = False,
) -> ChapterFinish:
    """2026-08-07 用于构造含未解决对话或确认人物的完整 finish"""
    characters = []
    observations = []
    if speaker_entity:
        start = text.index("顾霜")
        characters.append(
            {
                "ref": "character_1",
                "name": "顾霜",
                "existing_entity_id": None,
                "mentions": [
                    {
                        "chunk_id": chunk_id,
                        "start": start,
                        "end": start + 2,
                        "text": "顾霜",
                    }
                ],
                "confidence": "high",
                "evidence": [{"reason": "顾霜出现", "chunk_id": chunk_id}],
            }
        )
        observations.append(
            {
                "ref": "character_observation_1",
                "confidence": "high",
                "evidence": [{"reason": "顾霜喝道", "chunk_id": chunk_id}],
                "entity_ref": "character_1",
                "role_function": "主体",
                "action": "喝道",
                "action_type": "发言",
                "emotion": "neutral",
            }
        )
    dialogues = []
    if unresolved_dialogue:
        start = text.index("住手")
        dialogues.append(
            {
                "ref": "dialogue_1",
                "confidence": "high",
                "evidence": [{"reason": "原文出现住手", "chunk_id": chunk_id}],
                "content": "住手",
                "start": start,
                "end": start + 2,
                "speaker_ref": None,
                "speaker_existing_entity_id": None,
                "tone": "急切",
                "is_inner_monologue": False,
            }
        )
    return ChapterFinish.model_validate(
        {
            "chapter_summary": text,
            "entities": {
                "characters": characters,
                "locations": [],
                "objects": [],
                "organizations": [],
            },
            "chunks": [
                {
                    "chunk_id": chunk_id,
                    "summary": text,
                    "metrics": {
                        "emotional_valence": "neutral",
                        "event_type": "铺垫",
                        "pivot_moment": False,
                        "cliffhanger": False,
                    },
                    "character_observations": observations,
                    "location_observations": [],
                    "dialogues": dialogues,
                    "events": [],
                    "relations": [],
                    "states": [],
                    "foreshadowings": [],
                }
            ],
            "coverage": [_coverage(chunk_id)],
        }
    )


def _audit(
    finish: ChapterFinish,
    *,
    authorized_chunk_ids: list[int],
    initial_case_ids: list[str] | None = None,
) -> AgentRunAudit:
    """2026-08-07 用于构造完成事务审计和可信 Token 记录"""
    return AgentRunAudit(
        allow_future_context=False,
        initial_finish=finish,
        revision_payloads=[],
        initial_case_candidate_ids=initial_case_ids or [],
        rotation_case_ids=[],
        authorized_text_chunk_ids=authorized_chunk_ids,
        visible_graph_fact_refs=[],
        visible_graph_entity_ids=[],
        visible_graph_relation_ids=[],
        success=SuccessAudit(
            attempt_number=1,
            messages=[{"role": "ai", "content": "done"}],
            tool_calls=[],
            model_name="test-model",
            model_provider="local",
            duration_ms=10,
        ),
        token_usage=[
            {
                "model": "test-model",
                "prompt_tokens": 10,
                "completion_tokens": 5,
                "total_tokens": 15,
            }
        ],
    )


def _result(
    *,
    run_id: str,
    chapter_id: int,
    finish: ChapterFinish,
    pulled_results: list[PulledResult] | None = None,
    pushed_cases: list[PushedCase] | None = None,
    authorized_chunk_ids: list[int] | None = None,
) -> AgentRunResult:
    """2026-08-07 用于构造新合同 AgentRunResult"""
    pulled = pulled_results or []
    return AgentRunResult(
        run_id=run_id,
        chapter_id=chapter_id,
        finish=finish,
        pulled_results=pulled,
        pushed_cases=pushed_cases or [],
        audit=_audit(
            finish,
            authorized_chunk_ids=authorized_chunk_ids or [finish.chunks[0].chunk_id],
            initial_case_ids=[item.case_id for item in pulled],
        ),
    )


def _pushed_case() -> PushedCase:
    """2026-08-07 用于构造绑定 dialogue_1 的暂存后案例"""
    return PushedCase(
        description="该句住手由谁说出",
        keys=["住手", "说话人"],
        type="dialogue_speaker",
        chunkid=0,
        target_key="target-dialogue-1",
        target_anchor={
            "chunk_id": 0,
            "start": 1,
            "end": 3,
            "text": "住手",
        },
        target_ref={
            "kind": "dialogue",
            "item_ref": "dialogue_1",
            "chunk_id": 0,
            "start": 1,
            "end": 3,
            "text": "住手",
        },
    )


def _count(session, model, run_id: str) -> int:
    """2026-08-07 用于按 run 统计完成事务相关持久化行数"""
    return int(
        session.execute(
            select(func.count()).select_from(model).where(model.run_id == run_id)
        ).scalar_one()
    )


def test_complete_annotation_run_commits_finish_push_and_is_idempotent(db_session) -> None:
    """2026-08-07 用于验证 finish 与 push 同时提交且重复完成保持幂等"""
    novel_id, run_id = create_run_with_chunks(
        db_session,
        texts=["“住手”回荡"],
        title="完成事务成功",
    )
    factory = sessionmaker(bind=db_session.get_bind(), expire_on_commit=False)
    finish = _finish(chunk_id=0, text="“住手”回荡", unresolved_dialogue=True)
    result = _result(
        run_id=run_id,
        chapter_id=1,
        finish=finish,
        pushed_cases=[_pushed_case()],
    )

    first = complete_annotation_run(
        result=result,
        novel_id=novel_id,
        session_factory=factory,
    )
    second = complete_annotation_run(
        result=result,
        novel_id=novel_id,
        session_factory=factory,
    )

    db_session.rollback()
    case = db_session.execute(
        select(CasePoolCase).where(CasePoolCase.run_id == run_id)
    ).scalar_one()
    dialogue = db_session.execute(
        select(GraphFact).where(
            GraphFact.run_id == run_id,
            GraphFact.fact_type == "dialogue",
        )
    ).scalar_one()

    assert first == second
    assert first.pushed_cases[0].id == case.id
    assert case.case_type == "dialogue_speaker"
    assert case.chunk_id == 0
    assert case.target_ref["fact_id"] == dialogue.fact_id
    assert case.target_ref["fact_revision"] == 1
    assert _count(db_session, ChapterAnnotationRecord, run_id) == 1
    assert _count(db_session, GraphVersion, run_id) == 1
    assert _count(db_session, ModelInteraction, run_id) == 1
    assert _count(db_session, TokenUsage, run_id) == 1


def test_pull_resolution_revises_historical_dialogue_in_same_new_graph_version(db_session) -> None:
    """2026-08-07 用于验证 pull 按案例类型修订历史对话并解决案例"""
    novel_id, run_id = create_run_with_chunks(
        db_session,
        texts=["“住手”回荡", "顾霜喝道"],
        chapter_ids=[1, 2],
        title="后文确认说话人",
    )
    factory = sessionmaker(bind=db_session.get_bind(), expire_on_commit=False)
    first_finish = _finish(chunk_id=0, text="“住手”回荡", unresolved_dialogue=True)
    first = complete_annotation_run(
        result=_result(
            run_id=run_id,
            chapter_id=1,
            finish=first_finish,
            pushed_cases=[_pushed_case()],
        ),
        novel_id=novel_id,
        session_factory=factory,
    )
    db_session.rollback()
    case = db_session.get(CasePoolCase, first.pushed_cases[0].id)
    assert case is not None
    pulled = PulledResult(
        case_id=case.id,
        type="dialogue_speaker",
        resolution={
            "speaker": {"name": "顾霜", "entity_type": "character"},
            "evidence_chunkid": 1,
        },
        target_key=case.target_key,
        target_ref=dict(case.target_ref),
    )
    second_finish = _finish(chunk_id=1, text="顾霜喝道", speaker_entity=True)
    second = complete_annotation_run(
        result=_result(
            run_id=run_id,
            chapter_id=2,
            finish=second_finish,
            pulled_results=[pulled],
            authorized_chunk_ids=[1],
        ),
        novel_id=novel_id,
        session_factory=factory,
    )

    db_session.rollback()
    revisions = list(
        db_session.execute(
            select(GraphFact)
            .where(
                GraphFact.run_id == run_id,
                GraphFact.fact_id == case.target_ref["fact_id"],
            )
            .order_by(GraphFact.fact_revision)
        ).scalars()
    )
    resolved_case = db_session.get(CasePoolCase, case.id)
    mapping = db_session.execute(
        select(CaseResolutionMapping).where(
            CaseResolutionMapping.run_id == run_id,
            CaseResolutionMapping.case_id == case.id,
        )
    ).scalar_one()

    assert [row.fact_revision for row in revisions] == [1, 2]
    assert revisions[0].content["speaker"] is None
    assert revisions[1].content["speaker"]["name"] == "顾霜"
    assert revisions[1].source_kind == "case_resolution"
    assert revisions[1].graph_version_id == second.graph_version_id
    assert resolved_case is not None and resolved_case.state == "resolved"
    assert mapping.target_fact_revision == 2
    assert second.pulled_results[0].case_id == case.id


def test_complete_annotation_run_rolls_back_finish_pull_push_when_audit_fails(db_session) -> None:
    """2026-08-07 用于验证完成事务任一步失败时全部结果同时回滚"""
    novel_id, run_id = create_run_with_chunks(
        db_session,
        texts=["“住手”回荡"],
        title="完成事务回滚",
    )
    factory = sessionmaker(bind=db_session.get_bind(), expire_on_commit=False)
    finish = _finish(chunk_id=0, text="“住手”回荡", unresolved_dialogue=True)

    with patch(
        "src.workflows.annotate_helpers.storage._save_success_audit",
        side_effect=RuntimeError("audit failed"),
    ):
        with pytest.raises(RuntimeError, match="audit failed"):
            complete_annotation_run(
                result=_result(
                    run_id=run_id,
                    chapter_id=1,
                    finish=finish,
                    pushed_cases=[_pushed_case()],
                ),
                novel_id=novel_id,
                session_factory=factory,
            )

    db_session.rollback()
    for model in (
        ChapterAnnotationRecord,
        CasePoolCase,
        CaseResolutionMapping,
        GraphVersion,
        GraphFact,
        ModelInteraction,
        TokenUsage,
    ):
        assert _count(db_session, model, run_id) == 0


def test_load_completion_result_reads_existing_chapter_without_writes(db_session) -> None:
    """2026-08-07 用于验证已冻结章节可回读同一完成结果而不新增版本"""
    novel_id, run_id = create_run_with_chunks(
        db_session,
        texts=["顾霜喝道"],
        title="完成结果回读",
    )
    factory = sessionmaker(bind=db_session.get_bind(), expire_on_commit=False)
    finish = _finish(chunk_id=0, text="顾霜喝道", speaker_entity=True)
    expected = complete_annotation_run(
        result=_result(run_id=run_id, chapter_id=1, finish=finish),
        novel_id=novel_id,
        session_factory=factory,
    )

    db_session.rollback()
    actual = load_completion_result(db_session, run_id=run_id, chapter_id=1)

    assert actual == expected
    assert _count(db_session, ChapterAnnotationRecord, run_id) == 1
    assert _count(db_session, GraphVersion, run_id) == 1


def test_missing_pulled_case_rolls_back_before_finish_write(db_session) -> None:
    """2026-08-07 用于验证无法锁定 pulled 案例时不写任何章节结果"""
    novel_id, run_id = create_run_with_chunks(
        db_session,
        texts=["顾霜喝道"],
        title="来源案例锁定失败",
    )
    factory = sessionmaker(bind=db_session.get_bind(), expire_on_commit=False)
    finish = _finish(chunk_id=0, text="顾霜喝道", speaker_entity=True)
    pulled = PulledResult(
        case_id="missing-case",
        type="dialogue_speaker",
        resolution={
            "speaker": {"name": "顾霜", "entity_type": "character"},
            "evidence_chunkid": 0,
        },
        target_key="missing-target",
        target_ref={
            "kind": "dialogue",
            "item_ref": "dialogue_1",
            "chunk_id": 0,
            "start": 0,
            "end": 2,
            "text": "住手",
            "fact_id": "missing-fact",
            "fact_revision": 1,
        },
    )

    with pytest.raises(ValueError, match="无法锁定全部 pulled 案例"):
        complete_annotation_run(
            result=_result(
                run_id=run_id,
                chapter_id=1,
                finish=finish,
                pulled_results=[pulled],
            ),
            novel_id=novel_id,
            session_factory=factory,
        )

    db_session.rollback()
    assert _count(db_session, ChapterAnnotationRecord, run_id) == 0
    assert _count(db_session, GraphVersion, run_id) == 0
