"""章节标注唯一完成事务测试"""

from __future__ import annotations

from unittest.mock import patch

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import sessionmaker

from src.agents.annotation.schema import (
    AgentRunResult,
    CasePushOutput,
    ChapterAnnotation,
    FactPushOutput,
    RejectedPushOutput,
    SuccessAudit,
)
from src.storage.models import (
    CasePoolCase,
    CaseResolutionMapping,
    ChapterAnnotationRecord,
    GraphFact,
    GraphFactSource,
    ModelInteraction,
    TokenUsage,
)
from src.workflows.annotate_helpers.storage import complete_annotation_run, load_completion_result
from tests.support.chapter_annotation_helpers import create_run_with_chunks


def _annotation(*, chapter_id: int = 1, chunk_id: int = 0) -> ChapterAnnotation:
    """2026-08-05 用于构造唯一完成事务的章节正式标注"""
    return ChapterAnnotation.model_validate(
        {
            "chapter_summary": "顾霜进入山门",
            "segments": [
                {
                    "chunk_id": chunk_id,
                    "summary": "顾霜进入山门",
                    "emotional_valence": "neutral",
                    "event_type": "铺垫",
                    "pivot_moment": False,
                    "cliffhanger": False,
                }
            ],
            "characters": [
                {
                    "chunk_id": chunk_id,
                    "evidence": {"reason": "顾霜进入山门", "chapterid": chapter_id},
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
    """2026-08-06 用于构造含 Agent 图结果输出的完整 AgentRunResult"""
    annotation = _annotation()
    return AgentRunResult(
        run_id=run_id,
        chapter_id=1,
        final_annotation=annotation,
        initial_finish=annotation,
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
    assert completion.facts[0].graph_node_id.startswith("fact:")
    assert _count(db_session, ChapterAnnotationRecord, run_id) == 1
    assert _count(db_session, CaseResolutionMapping, run_id) == 1
    assert _count(db_session, GraphFact, run_id) == 3
    assert _count(db_session, GraphFactSource, run_id) == 3
    assert _count(db_session, ModelInteraction, run_id) == 1
    assert _count(db_session, TokenUsage, run_id) == 1
    interaction = db_session.execute(
        select(ModelInteraction).where(ModelInteraction.run_id == run_id)
    ).scalar_one()
    mapping = db_session.execute(
        select(CaseResolutionMapping).where(CaseResolutionMapping.run_id == run_id)
    ).scalar_one()
    graph_source = db_session.execute(
        select(GraphFactSource).where(
            GraphFactSource.run_id == run_id,
            GraphFactSource.stable_fact_id
            == completion.facts[0].graph_node_id.removeprefix("fact:"),
        )
    ).scalar_one()
    assert interaction.attempt_number == 3
    assert mapping.target_graph_node_id == completion.facts[0].graph_node_id
    assert graph_source.source_kind == "agent_resolution"
    assert graph_source.annotation_id == completion.annotation_id


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


def _case_result(
    run_id: str,
    *,
    chapter_id: int,
    chunk_id: int,
    source_case_ids: list[str],
) -> AgentRunResult:
    """2026-08-06 用于构造新建或重新推入案例的完成结果"""
    annotation = _annotation(chapter_id=chapter_id, chunk_id=chunk_id)
    return AgentRunResult(
        run_id=run_id,
        chapter_id=chapter_id,
        final_annotation=annotation,
        initial_finish=annotation,
        revision_payload={},
        initial_case_candidate_ids=list(source_case_ids),
        rotation_case_ids=[],
        pulled_case_ids=list(source_case_ids),
        staged_outputs=[
            CasePushOutput.model_validate(
                {
                    "output_kind": "case",
                    "source_case_ids": source_case_ids,
                    "evidence": {"reason": "身份仍需继续确认", "chapterid": chapter_id},
                    "payload": {
                        "keys": ["顾霜", "身份"],
                        "description": "顾霜身份仍待后续章节确认",
                    },
                }
            )
        ],
        success_audit=SuccessAudit(
            attempt_number=1,
            messages=[],
            tool_calls=[],
            model_provider="local",
            duration_ms=1,
        ),
    )


def test_requeued_case_uses_new_uuid_and_consumes_source(db_session) -> None:
    """2026-08-06 用于验证同内容案例重推后来源消耗且目标使用全新 UUID"""
    novel_id, run_id = create_run_with_chunks(
        db_session,
        texts=["顾霜身份成谜", "身份仍未揭晓"],
        chapter_ids=[1, 2],
        title="案例重新入池",
    )
    factory = sessionmaker(bind=db_session.get_bind(), expire_on_commit=False)
    first = complete_annotation_run(
        result=_case_result(
            run_id,
            chapter_id=1,
            chunk_id=0,
            source_case_ids=[],
        ),
        novel_id=novel_id,
        session_factory=factory,
    )
    source_case_id = first.cases[0].id
    second = complete_annotation_run(
        result=_case_result(
            run_id,
            chapter_id=2,
            chunk_id=1,
            source_case_ids=[source_case_id],
        ),
        novel_id=novel_id,
        session_factory=factory,
    )
    target_case_id = second.cases[0].id

    db_session.rollback()
    rows = list(
        db_session.execute(
            select(CasePoolCase)
            .where(CasePoolCase.id.in_([source_case_id, target_case_id]))
            .order_by(CasePoolCase.created_at, CasePoolCase.id)
        )
        .scalars()
        .all()
    )
    mapping = db_session.execute(
        select(CaseResolutionMapping).where(
            CaseResolutionMapping.run_id == run_id,
            CaseResolutionMapping.source_case_id == source_case_id,
            CaseResolutionMapping.target_case_id == target_case_id,
        )
    ).scalar_one()

    assert source_case_id != target_case_id
    assert {row.id: row.state for row in rows} == {
        source_case_id: "consumed",
        target_case_id: "active",
    }
    assert mapping.result_kind == "case"


def _resolved_case_result(
    run_id: str,
    *,
    chapter_id: int,
    chunk_id: int,
    source_case_id: str,
) -> AgentRunResult:
    """2026-08-06 用于构造把来源案例解决为数据库图结果的完成结果"""
    annotation = _annotation(chapter_id=chapter_id, chunk_id=chunk_id)
    return AgentRunResult(
        run_id=run_id,
        chapter_id=chapter_id,
        final_annotation=annotation,
        initial_finish=annotation,
        revision_payload={},
        initial_case_candidate_ids=[source_case_id],
        rotation_case_ids=[],
        pulled_case_ids=[source_case_id],
        staged_outputs=[
            FactPushOutput.model_validate(
                {
                    "output_kind": "fact",
                    "source_case_ids": [source_case_id],
                    "evidence": {"reason": "后文确认顾霜属于山门", "chapterid": chapter_id},
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
                        "confidence": "high",
                    },
                }
            )
        ],
        success_audit=SuccessAudit(
            attempt_number=1,
            messages=[],
            tool_calls=[],
            model_provider="local",
            duration_ms=1,
        ),
    )


def test_resolved_pulled_case_becomes_graph_result_and_is_consumed(db_session) -> None:
    """2026-08-06 用于验证已解决来源案例退出池并映射到数据库图节点"""
    novel_id, run_id = create_run_with_chunks(
        db_session,
        texts=["顾霜身份成谜", "顾霜属于山门"],
        chapter_ids=[1, 2],
        title="案例解决入图",
    )
    factory = sessionmaker(bind=db_session.get_bind(), expire_on_commit=False)
    first = complete_annotation_run(
        result=_case_result(
            run_id,
            chapter_id=1,
            chunk_id=0,
            source_case_ids=[],
        ),
        novel_id=novel_id,
        session_factory=factory,
    )
    source_case_id = first.cases[0].id
    resolved = complete_annotation_run(
        result=_resolved_case_result(
            run_id,
            chapter_id=2,
            chunk_id=1,
            source_case_id=source_case_id,
        ),
        novel_id=novel_id,
        session_factory=factory,
    )

    db_session.rollback()
    source_case = db_session.get(CasePoolCase, source_case_id)
    mapping = db_session.execute(
        select(CaseResolutionMapping).where(
            CaseResolutionMapping.run_id == run_id,
            CaseResolutionMapping.source_case_id == source_case_id,
            CaseResolutionMapping.result_kind == "fact",
        )
    ).scalar_one()
    graph_source = db_session.execute(
        select(GraphFactSource).where(
            GraphFactSource.run_id == run_id,
            GraphFactSource.stable_fact_id
            == resolved.facts[0].graph_node_id.removeprefix("fact:"),
        )
    ).scalar_one()

    assert source_case is not None
    assert source_case.state == "consumed"
    assert resolved.cases == []
    assert mapping.target_graph_node_id == resolved.facts[0].graph_node_id
    assert graph_source.source_kind == "agent_resolution"


def test_rejected_pulled_case_exits_without_graph_resolution(db_session) -> None:
    """2026-08-06 用于验证被否定来源案例退出池且不产生 Agent 图结果"""
    novel_id, run_id = create_run_with_chunks(
        db_session,
        texts=["顾霜身份成谜", "旧推断被否定"],
        chapter_ids=[1, 2],
        title="案例拒绝",
    )
    factory = sessionmaker(bind=db_session.get_bind(), expire_on_commit=False)
    first = complete_annotation_run(
        result=_case_result(
            run_id,
            chapter_id=1,
            chunk_id=0,
            source_case_ids=[],
        ),
        novel_id=novel_id,
        session_factory=factory,
    )
    source_case_id = first.cases[0].id
    annotation = _annotation(chapter_id=2, chunk_id=1)
    rejected_result = AgentRunResult(
        run_id=run_id,
        chapter_id=2,
        final_annotation=annotation,
        initial_finish=annotation,
        revision_payload={},
        initial_case_candidate_ids=[source_case_id],
        rotation_case_ids=[],
        pulled_case_ids=[source_case_id],
        staged_outputs=[
            RejectedPushOutput.model_validate(
                {
                    "output_kind": "rejected",
                    "source_case_ids": [source_case_id],
                    "evidence": {"reason": "后文明确否定旧推断", "chapterid": 2},
                    "payload": {
                        "reason_code": "contradicted",
                        "rejected_assumptions": ["顾霜身份未知"],
                    },
                }
            )
        ],
        success_audit=SuccessAudit(
            attempt_number=1,
            messages=[],
            tool_calls=[],
            model_provider="local",
            duration_ms=1,
        ),
    )
    completion = complete_annotation_run(
        result=rejected_result,
        novel_id=novel_id,
        session_factory=factory,
    )

    db_session.rollback()
    source_case = db_session.get(CasePoolCase, source_case_id)
    mapping = db_session.execute(
        select(CaseResolutionMapping).where(
            CaseResolutionMapping.run_id == run_id,
            CaseResolutionMapping.source_case_id == source_case_id,
            CaseResolutionMapping.result_kind == "rejected",
        )
    ).scalar_one()
    agent_sources = list(
        db_session.execute(
            select(GraphFactSource).where(
                GraphFactSource.run_id == run_id,
                GraphFactSource.annotation_id == completion.annotation_id,
                GraphFactSource.source_kind == "agent_resolution",
            )
        )
        .scalars()
        .all()
    )

    assert source_case is not None
    assert source_case.state == "rejected"
    assert completion.facts == []
    assert completion.rejected_source_case_ids == [source_case_id]
    assert mapping.target_graph_node_id is None
    assert agent_sources == []


def test_completion_revalidates_pulled_case_coverage_before_writes(db_session) -> None:
    """2026-08-06 用于验证完成事务拒绝未被 staged output 覆盖的来源案例"""
    novel_id, run_id = create_run_with_chunks(
        db_session,
        texts=["顾霜身份成谜"],
        title="完成事务来源复核",
    )
    factory = sessionmaker(bind=db_session.get_bind(), expire_on_commit=False)
    result = _case_result(
        run_id,
        chapter_id=1,
        chunk_id=0,
        source_case_ids=[],
    )
    result.pulled_case_ids = ["missing-source-case"]

    with pytest.raises(ValueError, match="未覆盖的 pulled 案例"):
        complete_annotation_run(
            result=result,
            novel_id=novel_id,
            session_factory=factory,
        )

    db_session.rollback()
    assert _count(db_session, ChapterAnnotationRecord, run_id) == 0
    assert _count(db_session, GraphFact, run_id) == 0
