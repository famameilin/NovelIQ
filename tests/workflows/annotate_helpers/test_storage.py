"""章节标注唯一完成事务测试"""

from __future__ import annotations

from unittest.mock import patch

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import sessionmaker

from src.agents.annotation.schema import (
    AgentRunResult,
    ChapterAnnotation,
    FactPushOutput,
    SuccessAudit,
)
from src.storage.models import (
    CaseResolutionMapping,
    ChapterAnnotationRecord,
    ContinuityFact,
    GraphFact,
    GraphFactSource,
    ModelInteraction,
    TokenUsage,
)
from src.workflows.annotate_helpers.storage import complete_annotation_run, load_completion_result
from tests.support.chapter_annotation_helpers import create_run_with_chunks


def _annotation() -> ChapterAnnotation:
    """2026-08-05 用于构造唯一完成事务的章节正式标注"""
    return ChapterAnnotation.model_validate(
        {
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
            "characters": [
                {
                    "chunk_id": 0,
                    "evidence": {"reason": "顾霜进入山门", "chapterid": 1},
                    "confidence": "high",
                    "entity": {"name": "顾霜", "entity_type": "character"},
                    "role_function": "主体",
                    "action": "进入山门",
                    "action_type": "移动",
                    "emotion": "neutral",
                }
            ],
            "locations": [],
            "dialogues": [],
            "events": [],
            "relations": [],
            "states": [],
        }
    )


def _result(run_id: str) -> AgentRunResult:
    """2026-08-05 用于构造含连续性事实输出的完整 AgentRunResult"""
    annotation = _annotation()
    return AgentRunResult(
        run_id=run_id,
        chapter_id=1,
        final_annotation=annotation,
        initial_finish=annotation,
        after_chapter_ids=[2],
        revision_payload={},
        initial_case_candidate_ids=[],
        rotation_case_ids=[],
        pulled_case_ids=[],
        staged_outputs=[
            FactPushOutput.model_validate(
                {
                    "output_kind": "fact",
                    "source_case_ids": [],
                    "evidence": {"reason": "顾霜属于山门", "chapterid": 1},
                    "payload": {
                        "fact_type": "membership",
                        "subject": {"name": "顾霜", "entity_type": "character"},
                        "predicate": "belongs_to",
                        "object": {"name": "山门", "entity_type": "location"},
                        "value": None,
                        "participants": [],
                        "scope": "novel",
                        "story_time": None,
                        "assertion": "affirmed",
                        "change_kind": "assert",
                        "linked_fact_id": None,
                        "confidence": "high",
                    },
                }
            )
        ],
        success_audit=SuccessAudit(
            attempt_number=3,
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


def _count(session, model, run_id: str) -> int:
    """2026-08-05 用于按 run 统计完成事务相关 ORM 行"""
    return int(
        session.execute(
            select(func.count()).select_from(model).where(model.run_id == run_id)
        ).scalar_one()
    )


def test_complete_annotation_run_commits_all_results_once(db_session) -> None:
    """2026-08-05 用于验证章节业务结果图审计与 Token 用量一次提交"""
    novel_id, run_id = create_run_with_chunks(
        db_session,
        texts=["顾霜进入山门"],
        title="完成事务成功",
    )
    factory = sessionmaker(bind=db_session.get_bind(), expire_on_commit=False)

    completion = complete_annotation_run(
        result=_result(run_id),
        novel_id=novel_id,
        session_factory=factory,
    )

    db_session.rollback()
    assert completion.chapter_id == 1
    assert len(completion.facts) == 1
    assert _count(db_session, ChapterAnnotationRecord, run_id) == 1
    assert _count(db_session, ContinuityFact, run_id) == 1
    assert _count(db_session, CaseResolutionMapping, run_id) == 1
    assert _count(db_session, GraphFact, run_id) == 3
    assert _count(db_session, GraphFactSource, run_id) == 3
    assert _count(db_session, ModelInteraction, run_id) == 1
    assert _count(db_session, TokenUsage, run_id) == 1
    interaction = db_session.execute(
        select(ModelInteraction).where(ModelInteraction.run_id == run_id)
    ).scalar_one()
    assert interaction.attempt_number == 3


def test_complete_annotation_run_rolls_back_everything_when_audit_fails(db_session) -> None:
    """2026-08-05 用于验证事务末端失败后章节输出图和审计全部回滚"""
    novel_id, run_id = create_run_with_chunks(
        db_session,
        texts=["顾霜进入山门"],
        title="完成事务回滚",
    )
    factory = sessionmaker(bind=db_session.get_bind(), expire_on_commit=False)

    with patch(
        "src.workflows.annotate_helpers.storage._save_success_audit",
        side_effect=RuntimeError("audit failed"),
    ):
        with pytest.raises(RuntimeError, match="audit failed"):
            complete_annotation_run(
                result=_result(run_id),
                novel_id=novel_id,
                session_factory=factory,
            )

    db_session.rollback()
    for model in (
        ChapterAnnotationRecord,
        ContinuityFact,
        CaseResolutionMapping,
        GraphFact,
        GraphFactSource,
        ModelInteraction,
        TokenUsage,
    ):
        assert _count(db_session, model, run_id) == 0


def test_load_completion_result_reads_existing_chapter_without_writes(db_session) -> None:
    """2026-08-05 用于验证已提交章节可以直接回读同一个 CompletionResult"""
    novel_id, run_id = create_run_with_chunks(
        db_session,
        texts=["顾霜进入山门"],
        title="完成结果回读",
    )
    factory = sessionmaker(bind=db_session.get_bind(), expire_on_commit=False)
    expected = complete_annotation_run(
        result=_result(run_id),
        novel_id=novel_id,
        session_factory=factory,
    )

    db_session.rollback()
    actual = load_completion_result(db_session, run_id=run_id, chapter_id=1)

    assert actual == expected
    assert _count(db_session, ChapterAnnotationRecord, run_id) == 1
