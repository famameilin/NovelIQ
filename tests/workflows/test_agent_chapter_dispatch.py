"""章节标注 Workflow 串行调度测试"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy import func, select

from src.agents.annotation.candidates import extract_dialogue_candidates
from src.agents.annotation.runner import AnnotationAgentRunError
from src.agents.annotation.schema import (
    AgentRunAudit,
    AgentRunResult,
    BoundChapterAnnotation,
    BoundChunkAnnotation,
    BoundDialogue,
    BoundEntityDirectory,
    CaseSearchResult,
    ChunkMetricsInput,
    PendingCase,
    SuccessAudit,
)
from src.agents.stream import AgentStream
from src.storage.models import ChapterAnnotationRecord
from src.workflows.annotate import _group_chunks_by_chapter, run_annotate
from tests.support.chapter_annotation_helpers import create_run_with_chunks, evidence, persist_chapter_annotation


def _annotation(
    *,
    chapter_id: int,
    chunk_id: int,
    chunk_text: str,
    create_case: bool,
) -> BoundChapterAnnotation:
    """2026-08-07 用于构造指定章节的新合同完整标注"""
    dialogues: list[BoundDialogue] = []
    if create_case:
        candidate = next(
            item
            for item in extract_dialogue_candidates(chunk_id, chunk_text)
            if item.content == "住手"
        )
        dialogues.append(
            BoundDialogue(
                candidate_key=candidate.candidate_key,
                content=candidate.content,
                start=candidate.start,
                end=candidate.end,
                description="住手出现",
                speaker=None,
                tone=None,
                is_inner_monologue=False,
                confidence="high",
                reason="住手出现",
                evidence=evidence("住手出现", chunk_id),
            )
        )
    return BoundChapterAnnotation(
        chapter_summary=f"章节 {chapter_id}",
        chunks=[
            BoundChunkAnnotation(
                chunk_id=chunk_id,
                metrics=ChunkMetricsInput(
                    summary=f"chunk {chunk_id}",
                    emotional_valence="neutral",
                    narrative_function="铺垫",
                    confidence="high",
                    reason="摘要",
                ),
                entities=BoundEntityDirectory(),
                character_observations=[],
                dialogues=dialogues,
                events=[],
                relations=[],
                states=[],
                foreshadowings=[],
            )
        ],
    )


def _pending_case(
    *,
    chunk_id: int,
    chunk_text: str,
    chapter_id: int,
) -> PendingCase:
    """2026-08-07 用于构造绑定 chapter 对话的系统自动案例"""
    candidate = next(
        item
        for item in extract_dialogue_candidates(chunk_id, chunk_text)
        if item.content == "住手"
    )
    return PendingCase(
        type="dialogue_speaker",
        chunk_id=chunk_id,
        keys=["住手", "说话人"],
        description="该句住手由谁说出",
        target_key=f"target-{chapter_id}",
        target_ref={
            "kind": "dialogue",
            "candidate_key": candidate.candidate_key,
            "chunk_id": chunk_id,
            "start": candidate.start,
            "end": candidate.end,
            "text": candidate.content,
        },
        evidence=evidence("住手出现", chunk_id),
    )


def _agent_result(
    *,
    run_id: str,
    chapter_id: int,
    chunk_id: int,
    chunk_text: str,
    create_case: bool = False,
) -> AgentRunResult:
    """2026-08-07 用于构造 Workflow 串行测试的 Agent 成功结果"""
    annotation = _annotation(
        chapter_id=chapter_id,
        chunk_id=chunk_id,
        chunk_text=chunk_text,
        create_case=create_case,
    )
    return AgentRunResult(
        run_id=run_id,
        chapter_id=chapter_id,
        annotation=annotation,
        resolved_cases=[],
        pending_cases=(
            [_pending_case(chunk_id=chunk_id, chunk_text=chunk_text, chapter_id=chapter_id)]
            if create_case
            else []
        ),
        audit=AgentRunAudit(
            allow_future_context=False,
            write_revisions=[],
            rotation_case_ids=[],
            authorized_text_chunk_ids=[chunk_id],
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
        chunk_text = kwargs["current_chunks"][0][1]
        if chapter_id == 2:
            read_session = kwargs["session_factory"]()
            try:
                service = kwargs["query_service_factory"](read_session)
                search_result = service.search_pool(
                    "住手",
                    hidden_case_ids=set(),
                )
                assert all(
                    isinstance(item, CaseSearchResult) for item in search_result.results
                )
                assert search_result.results[0].description == "该句住手由谁说出"
            finally:
                read_session.rollback()
                read_session.close()
        return _agent_result(
            run_id=run_id,
            chapter_id=chapter_id,
            chunk_id=chapter_id - 1,
            chunk_text=chunk_text,
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
    """2026-08-07 用于验证正式标注存在时直接回读并跳过 Agent"""
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
        chunk_text = kwargs["current_chunks"][0][1]
        return _agent_result(
            run_id=run_id,
            chapter_id=kwargs["chapter_id"],
            chunk_id=1,
            chunk_text=chunk_text,
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
async def test_run_annotate_passes_agent_stream_to_agent(db_session) -> None:
    """2026-08-09 用于验证 emitter 会以 AgentStream 形式透传给章节 Agent"""
    novel_id, run_id = create_run_with_chunks(
        db_session,
        texts=["第一章"],
        chapter_ids=[1],
        title="流式透传",
    )
    emitted: list[tuple[str, str]] = []
    seen_streams: list[AgentStream | None] = []

    async def fake_agent(**kwargs):
        """2026-08-09 用于捕获 stream 参数并返回合法章节结果"""
        seen_streams.append(kwargs.get("stream"))
        chunk_text = kwargs["current_chunks"][0][1]
        return _agent_result(
            run_id=run_id,
            chapter_id=1,
            chunk_id=0,
            chunk_text=chunk_text,
        )

    async def emitter(event) -> None:
        """2026-08-09 用于记录 workflow 级事件"""
        emitted.append((event.action, event.content))

    with (
        patch("src.agents.annotation.run_annotation_agent", new=fake_agent),
        patch("src.agents.llm.build_chat_model", return_value=MagicMock()),
    ):
        result = await run_annotate(
            run_id=run_id,
            session=db_session,
            novel_id=novel_id,
            emitter=emitter,
        )

    assert result == (1, 0, 1)
    assert len(seen_streams) == 1
    assert isinstance(seen_streams[0], AgentStream)
    # 章节开始 thinking 事件已通过 AgentStream 到达 emitter
    assert ("thinking", "章节 1 标注 Agent 开始处理") in emitted


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
