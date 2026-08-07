"""章节标注 Workflow 串行调度测试"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy import func, select

from src.agents.annotation.runner import AnnotationAgentRunError
from src.agents.annotation.schema import (
    AgentRunAudit,
    AgentRunResult,
    ChapterFinish,
    PushedCase,
    SuccessAudit,
)
from src.storage.models import ChapterAnnotationRecord
from src.workflows.annotate import _group_chunks_by_chapter, run_annotate
from tests.support.chapter_annotation_helpers import create_run_with_chunks, persist_chapter_annotation


def _coverage(chunk_id: int) -> dict:
    """2026-08-07 用于构造 Workflow 测试全领域 coverage"""
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


def _finish(chapter_id: int, chunk_id: int, *, create_case: bool) -> ChapterFinish:
    """2026-08-07 用于构造指定章节的新合同完整 finish"""
    dialogues = []
    if create_case:
        dialogues.append(
            {
                "ref": "dialogue_1",
                "confidence": "high",
                "evidence": [{"reason": "住手出现", "chunk_id": chunk_id}],
                "content": "住手",
                "start": 1,
                "end": 3,
                "speaker_ref": None,
                "speaker_existing_entity_id": None,
                "tone": None,
                "is_inner_monologue": False,
            }
        )
    return ChapterFinish.model_validate(
        {
            "chapter_summary": f"章节 {chapter_id}",
            "entities": {
                "characters": [],
                "locations": [],
                "objects": [],
                "organizations": [],
            },
            "chunks": [
                {
                    "chunk_id": chunk_id,
                    "summary": f"chunk {chunk_id}",
                    "metrics": {
                        "emotional_valence": "neutral",
                        "event_type": "铺垫",
                        "pivot_moment": False,
                        "cliffhanger": False,
                    },
                    "character_observations": [],
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


def _agent_result(
    *,
    run_id: str,
    chapter_id: int,
    chunk_id: int,
    create_case: bool = False,
) -> AgentRunResult:
    """2026-08-07 用于构造 Workflow 串行测试的 Agent 成功结果"""
    finish = _finish(chapter_id, chunk_id, create_case=create_case)
    pushed_cases = (
        [
            PushedCase(
                description="该句住手由谁说出",
                keys=["住手", "说话人"],
                type="dialogue_speaker",
                chunkid=chunk_id,
                target_key=f"target-{chapter_id}",
                target_anchor={
                    "chunk_id": chunk_id,
                    "start": 1,
                    "end": 3,
                    "text": "住手",
                },
                target_ref={
                    "kind": "dialogue",
                    "item_ref": "dialogue_1",
                    "chunk_id": chunk_id,
                    "start": 1,
                    "end": 3,
                    "text": "住手",
                },
            )
        ]
        if create_case
        else []
    )
    return AgentRunResult(
        run_id=run_id,
        chapter_id=chapter_id,
        finish=finish,
        pulled_results=[],
        pushed_cases=pushed_cases,
        audit=AgentRunAudit(
            allow_future_context=False,
            initial_finish=finish,
            revision_payloads=[],
            initial_case_candidate_ids=[],
            rotation_case_ids=[],
            authorized_text_chunk_ids=[chunk_id],
            visible_graph_fact_refs=[],
            visible_graph_entity_ids=[],
            visible_graph_relation_ids=[],
            success=SuccessAudit(
                attempt_number=1,
                messages=[],
                tool_calls=[],
                model_provider="local",
                duration_ms=1,
            ),
        ),
    )


def test_group_chunks_by_chapter_requires_real_nonempty_identity() -> None:
    """2026-08-05 用于验证章节聚合拒绝空 chapter_id 和运行时序号兜底"""
    with pytest.raises(ValueError, match="chapter_id 必须真实且非空"):
        _group_chunks_by_chapter([(0, None, "无章节身份")])  # type: ignore[list-item]


def test_group_chunks_by_chapter_preserves_persisted_order() -> None:
    """2026-08-05 用于验证章节与 chunk 均保持数据库原文顺序"""
    assert _group_chunks_by_chapter(
        [(0, 1, "甲"), (1, 1, "乙"), (2, 2, "丙")]
    ) == [(1, [(0, "甲"), (1, "乙")]), (2, [(2, "丙")])]


@pytest.mark.asyncio
async def test_run_annotate_is_strictly_serial_and_next_chapter_sees_committed_case(db_session) -> None:
    """2026-08-07 用于验证前章事务提交后后章可检索新 active 案例"""
    novel_id, run_id = create_run_with_chunks(
        db_session,
        texts=["“住手”回荡", "后文点明顾霜身份"],
        chapter_ids=[1, 2],
        title="章节串行",
    )
    calls: list[int] = []

    async def fake_agent(**kwargs):
        """2026-08-07 用于在第二章启动时读取第一章已提交案例"""
        chapter_id = kwargs["chapter_id"]
        calls.append(chapter_id)
        if chapter_id == 2:
            read_session = kwargs["session_factory"]()
            try:
                service = kwargs["query_service_factory"](read_session)
                search_result = service.search_pool(
                    "住手",
                    hidden_case_ids=set(),
                )
                assert [item.result_kind for item in search_result.results] == ["case"]
            finally:
                read_session.rollback()
                read_session.close()
        return _agent_result(
            run_id=run_id,
            chapter_id=chapter_id,
            chunk_id=chapter_id - 1,
            create_case=chapter_id == 1,
        )

    with (
        patch("src.agents.annotation.run_annotation_agent", new=fake_agent),
        patch("src.agents.llm.build_chat_model", return_value=MagicMock()),
    ):
        result = await run_annotate(
            run_id=run_id,
            session=db_session,
            novel_id=novel_id,
        )

    assert result == (2, 0, 2)
    assert calls == [1, 2]


@pytest.mark.asyncio
async def test_run_annotate_skips_existing_chapter_completion(db_session) -> None:
    """2026-08-07 用于验证正式 ChapterFinish 存在时直接回读并跳过 Agent"""
    novel_id, run_id = create_run_with_chunks(
        db_session,
        texts=["第一章", "第二章"],
        chapter_ids=[1, 2],
        title="章节回读",
    )
    persist_chapter_annotation(db_session, run_id=run_id, chapter_id=1)
    calls: list[int] = []

    async def fake_agent(**kwargs):
        """2026-08-07 用于记录仍需执行的章节"""
        calls.append(kwargs["chapter_id"])
        return _agent_result(
            run_id=run_id,
            chapter_id=kwargs["chapter_id"],
            chunk_id=1,
        )

    with (
        patch("src.agents.annotation.run_annotation_agent", new=fake_agent),
        patch("src.agents.llm.build_chat_model", return_value=MagicMock()),
    ):
        result = await run_annotate(
            run_id=run_id,
            session=db_session,
            novel_id=novel_id,
        )

    assert result == (2, 0, 2)
    assert calls == [2]
    db_session.rollback()
    count = db_session.execute(
        select(func.count())
        .select_from(ChapterAnnotationRecord)
        .where(ChapterAnnotationRecord.run_id == run_id)
    ).scalar_one()
    assert count == 2


@pytest.mark.asyncio
async def test_run_annotate_stops_entire_stage_on_agent_exhaustion(db_session) -> None:
    """2026-08-05 用于验证章节 Agent 三次耗尽后不启动任何后续章节"""
    novel_id, run_id = create_run_with_chunks(
        db_session,
        texts=["第一章", "第二章"],
        chapter_ids=[1, 2],
        title="章节失败终止",
    )
    agent = MagicMock(side_effect=AnnotationAgentRunError("三次失败"))

    async def failing_agent(**kwargs):
        """2026-08-05 用于模拟首章三次尝试耗尽"""
        return agent(**kwargs)

    with (
        patch("src.agents.annotation.run_annotation_agent", new=failing_agent),
        patch("src.agents.llm.build_chat_model", return_value=MagicMock()),
    ):
        with pytest.raises(AnnotationAgentRunError, match="三次失败"):
            await run_annotate(
                run_id=run_id,
                session=db_session,
                novel_id=novel_id,
            )

    assert agent.call_count == 1
    db_session.rollback()
    count = db_session.execute(
        select(func.count())
        .select_from(ChapterAnnotationRecord)
        .where(ChapterAnnotationRecord.run_id == run_id)
    ).scalar_one()
    assert count == 0
