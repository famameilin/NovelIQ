"""章节标注原子完成事务测试"""

from __future__ import annotations

import hashlib
from unittest.mock import patch

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import sessionmaker

from src.agents.annotation.candidates import extract_dialogue_candidates
from src.agents.annotation.schema import (
    AgentRunAudit,
    AgentRunResult,
    BoundChapterAnnotation,
    BoundChunkAnnotation,
    BoundDialogue,
    BoundEntity,
    BoundEntityDirectory,
    ChunkMetricsInput,
    PendingCase,
    ResolvedCase,
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
from tests.support.chapter_annotation_helpers import create_run_with_chunks, evidence


def _annotation(
    *,
    chunk_id: int,
    text: str,
    unresolved_dialogue: bool = False,
    speaker_entity: bool = False,
) -> BoundChapterAnnotation:
    """2026-08-07 用于构造含未解决对话或确认人物的系统绑定章节标注"""
    characters: list[BoundEntity] = []
    if speaker_entity:
        characters.append(
            BoundEntity(
                name="顾霜",
                confidence="high",
                reason="顾霜出现",
                evidence=evidence("顾霜出现", chunk_id),
            )
        )
    dialogues: list[BoundDialogue] = []
    if unresolved_dialogue:
        candidate = next(
            item for item in extract_dialogue_candidates(chunk_id, text) if item.content == "住手"
        )
        dialogues.append(
            BoundDialogue(
                candidate_key=candidate.candidate_key,
                content=candidate.content,
                start=candidate.start,
                end=candidate.end,
                description="喝止住手",
                speaker=None,
                tone="急切",
                is_inner_monologue=False,
                confidence="high",
                reason="双引号",
                evidence=evidence("住手出现", chunk_id),
            )
        )
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
                entities=BoundEntityDirectory(
                    characters=characters,
                ),
                character_observations=[],
                dialogues=dialogues,
                events=[],
                relations=[],
                states=[],
                foreshadowings=[],
            )
        ],
    )


def _audit(
    *,
    authorized_chunk_ids: list[int],
) -> AgentRunAudit:
    """2026-08-07 用于构造完成事务审计和可信 Token 记录"""
    return AgentRunAudit(
        allow_future_context=False,
        write_revisions=[],
        rotation_case_ids=[],
        authorized_text_chunk_ids=authorized_chunk_ids,
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


def _pending_cases_for(annotation: BoundChapterAnnotation) -> list[PendingCase]:
    """2026-08-07 用于从 speaker 为空的系统对话构造自动案例"""
    pending: list[PendingCase] = []
    for chunk in annotation.chunks:
        for dialogue in chunk.dialogues:
            if dialogue.speaker is not None:
                continue
            target_key = hashlib.sha256(
                f"{chunk.chunk_id}:{dialogue.start}:{dialogue.end}".encode()
            ).hexdigest()
            pending.append(
                PendingCase(
                    type="dialogue_speaker",
                    chunk_id=chunk.chunk_id,
                    keys=[dialogue.content, "说话人"],
                    description=f"确认对话“{dialogue.content[:40]}”的说话人",
                    target_key=target_key,
                    target_ref={
                        "kind": "dialogue",
                        "candidate_key": dialogue.candidate_key,
                        "chunk_id": chunk.chunk_id,
                        "start": dialogue.start,
                        "end": dialogue.end,
                        "text": dialogue.content,
                    },
                    evidence=dialogue.evidence,
                )
            )
    return pending


def _result(
    *,
    run_id: str,
    chapter_id: int,
    annotation: BoundChapterAnnotation,
    resolved_cases: list[ResolvedCase] | None = None,
    pending_cases: list[PendingCase] | None = None,
    authorized_chunk_ids: list[int] | None = None,
) -> AgentRunResult:
    """2026-08-07 用于构造新合同 AgentRunResult"""
    return AgentRunResult(
        run_id=run_id,
        chapter_id=chapter_id,
        annotation=annotation,
        resolved_cases=resolved_cases or [],
        pending_cases=pending_cases or _pending_cases_for(annotation),
        audit=_audit(
            authorized_chunk_ids=authorized_chunk_ids
            or [annotation.chunks[0].chunk_id],
        ),
    )


def _count(session, model, run_id: str) -> int:
    """2026-08-07 用于按 run 统计完成事务相关持久化行数"""
    return int(
        session.execute(
            select(func.count()).select_from(model).where(model.run_id == run_id)
        ).scalar_one()
    )


def test_complete_annotation_run_commits_case_and_is_idempotent(db_session) -> None:
    """2026-08-07 用于验证标注与自动案例同时提交且重复完成保持幂等"""
    novel_id, run_id = create_run_with_chunks(
        db_session,
        texts=["“住手”回荡"],
        title="完成事务成功",
    )
    factory = sessionmaker(bind=db_session.get_bind(), expire_on_commit=False)
    annotation = _annotation(chunk_id=0, text="“住手”回荡", unresolved_dialogue=True)
    result = _result(
        run_id=run_id,
        chapter_id=1,
        annotation=annotation,
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
    assert first.created_cases[0].id == case.id
    assert case.case_type == "dialogue_speaker"
    assert case.chunk_id == 0
    assert case.target_ref["fact_id"] == dialogue.fact_id
    assert case.target_ref["fact_revision"] == 1
    assert _count(db_session, ChapterAnnotationRecord, run_id) == 1
    assert _count(db_session, GraphVersion, run_id) == 1
    assert _count(db_session, ModelInteraction, run_id) == 1
    assert _count(db_session, TokenUsage, run_id) == 1


def test_case_resolution_revises_historical_dialogue_in_same_new_graph_version(
    db_session,
) -> None:
    """2026-08-07 用于验证后文解决案例修订历史对话并保持正式 speaker=null"""
    novel_id, run_id = create_run_with_chunks(
        db_session,
        texts=["“住手”回荡", "顾霜喝道"],
        chapter_ids=[1, 2],
        title="后文确认说话人",
    )
    factory = sessionmaker(bind=db_session.get_bind(), expire_on_commit=False)
    first_annotation = _annotation(
        chunk_id=0,
        text="“住手”回荡",
        unresolved_dialogue=True,
    )
    first = complete_annotation_run(
        result=_result(
            run_id=run_id,
            chapter_id=1,
            annotation=first_annotation,
        ),
        novel_id=novel_id,
        session_factory=factory,
    )
    db_session.rollback()
    case = db_session.get(CasePoolCase, first.created_cases[0].id)
    assert case is not None
    resolved = ResolvedCase(
        case_id=case.id,
        type="dialogue_speaker",
        speaker="顾霜",
        reason="后文点明顾霜",
        evidence_chunk_id=1,
        target_key=case.target_key,
        target_ref=dict(case.target_ref),
    )
    second_annotation = _annotation(
        chunk_id=1,
        text="顾霜喝道",
        speaker_entity=True,
    )
    second = complete_annotation_run(
        result=_result(
            run_id=run_id,
            chapter_id=2,
            annotation=second_annotation,
            resolved_cases=[resolved],
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
    assert second.resolved_cases[0].case_id == case.id


def test_complete_annotation_run_rolls_back_everything_when_audit_fails(db_session) -> None:
    """2026-08-07 用于验证完成事务任一步失败时全部结果同时回滚"""
    novel_id, run_id = create_run_with_chunks(
        db_session,
        texts=["“住手”回荡"],
        title="完成事务回滚",
    )
    factory = sessionmaker(bind=db_session.get_bind(), expire_on_commit=False)
    annotation = _annotation(chunk_id=0, text="“住手”回荡", unresolved_dialogue=True)

    with patch(
        "src.workflows.annotate_helpers.storage._save_success_audit",
        side_effect=RuntimeError("audit failed"),
    ):
        with pytest.raises(RuntimeError, match="audit failed"):
            complete_annotation_run(
                result=_result(
                    run_id=run_id,
                    chapter_id=1,
                    annotation=annotation,
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
    annotation = _annotation(chunk_id=0, text="顾霜喝道", speaker_entity=True)
    expected = complete_annotation_run(
        result=_result(run_id=run_id, chapter_id=1, annotation=annotation),
        novel_id=novel_id,
        session_factory=factory,
    )

    db_session.rollback()
    actual = load_completion_result(db_session, run_id=run_id, chapter_id=1)

    assert actual == expected
    assert _count(db_session, ChapterAnnotationRecord, run_id) == 1
    assert _count(db_session, GraphVersion, run_id) == 1


def test_missing_resolved_case_rolls_back_before_annotation_write(db_session) -> None:
    """2026-08-07 用于验证无法锁定 resolved 案例时不写任何章节结果"""
    novel_id, run_id = create_run_with_chunks(
        db_session,
        texts=["顾霜喝道"],
        title="来源案例锁定失败",
    )
    factory = sessionmaker(bind=db_session.get_bind(), expire_on_commit=False)
    annotation = _annotation(chunk_id=0, text="顾霜喝道", speaker_entity=True)
    missing = ResolvedCase(
        case_id="missing-case",
        type="dialogue_speaker",
        speaker="顾霜",
        reason="后文点明",
        evidence_chunk_id=0,
        target_key="missing-target",
        target_ref={
            "kind": "dialogue",
            "candidate_key": "candidate-1",
            "chunk_id": 0,
            "start": 0,
            "end": 2,
            "text": "住手",
            "fact_id": "missing-fact",
            "fact_revision": 1,
        },
    )

    with pytest.raises(ValueError, match="无法锁定全部 resolved cases"):
        complete_annotation_run(
            result=_result(
                run_id=run_id,
                chapter_id=1,
                annotation=annotation,
                resolved_cases=[missing],
            ),
            novel_id=novel_id,
            session_factory=factory,
        )

    db_session.rollback()
    assert _count(db_session, ChapterAnnotationRecord, run_id) == 0
    assert _count(db_session, GraphVersion, run_id) == 0
