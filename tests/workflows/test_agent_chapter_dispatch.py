"""章节标注 Workflow 调度测试（2026-09-19 双路径：正文不超门槛=agent 路径，超门槛=三条 subagent 并发）"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy import func, select

from src.agents.annotation.candidates import extract_dialogue_candidates
from src.agents.annotation.schema import (
    AgentRunAudit,
    AgentRunResult,
    BoundChapterAnnotation,
    BoundDialogue,
    CaseSearchResult,
    ChapterMetricsInput,
    PendingCase,
)
from src.agents.stream import AgentStream
from src.api.models.events import StreamEvent
from src.config import settings
from src.storage.models import Chapter, ChapterAnnotationRecord
from src.workflows.annotate import _validated_chapter_rows, run_annotate
from tests.support.chapter_annotation_helpers import create_run_with_chunks, persist_chapter_annotation


def _annotation(
    *,
    chapter_id: int,
    chapter_text: str,
    create_case: bool,
) -> BoundChapterAnnotation:
    """2026-08-07 用于构造指定章节的新合同完整标注"""
    dialogues: list[BoundDialogue] = []
    if create_case:
        candidate = next(
            item for item in extract_dialogue_candidates(chapter_id, chapter_text) if item.content == "住手"
        )
        dialogues.append(
            BoundDialogue(
                candidate_index=1,
                candidate_key=candidate.candidate_key,
                content=candidate.content,
                start=candidate.start,
                end=candidate.end,
                speaker=None,
                tone=None,
                is_inner_monologue=False,
            )
        )
    return BoundChapterAnnotation(
        metrics=ChapterMetricsInput(
            summary=f"章节 {chapter_id}",
            emotional_valence=0,
            narrative_function="铺垫",
        ),
        character_observations=[],
        dialogues=dialogues,
        events=[],
    )


def _pending_case(
    *,
    chapter_id: int,
    chapter_text: str,
) -> PendingCase:
    """2026-08-07 用于构造绑定 chapter 对话的系统自动案例"""
    candidate = next(item for item in extract_dialogue_candidates(chapter_id, chapter_text) if item.content == "住手")
    return PendingCase(
        type="dialogue_speaker",
        chapter_id=chapter_id,
        keys=["住手", "说话人"],
        description="该句住手由谁说出",
        target_key=f"target-{chapter_id}",
        target_ref={
            "kind": "dialogue_speaker",
            "dialogue_id": candidate.candidate_key,
            "chapter_id": chapter_id,
        },
    )


def _agent_result(
    *,
    run_id: str,
    chapter_id: int,
    chapter_text: str,
    create_case: bool = False,
) -> AgentRunResult:
    """2026-08-07 用于构造 Workflow 调度测试的 Agent 成功结果"""
    annotation = _annotation(
        chapter_id=chapter_id,
        chapter_text=chapter_text,
        create_case=create_case,
    )
    return AgentRunResult(
        run_id=run_id,
        chapter_id=chapter_id,
        annotation=annotation,
        resolved_cases=[],
        pushed_cases=(
            [_pending_case(chapter_id=chapter_id, chapter_text=chapter_text)] if create_case else []
        ),
        audit=AgentRunAudit(
            allow_future_context=False,
            write_records=[],
            authorized_chapter_ids=[chapter_id],
            authorized_text_paragraph_ids=[],
        ),
    )


def test_validated_chapter_rows_requires_real_nonempty_identity() -> None:
    """2026-08-05 用于验证章行校验拒绝空 chapter_id"""
    with pytest.raises(ValueError):
        _validated_chapter_rows([(0, "无章节身份")])


def test_validated_chapter_rows_preserves_persisted_order() -> None:
    """2026-09-19 用于验证章行保持数据库原文顺序（M9a-2 后一章一行，无聚合）"""
    assert _validated_chapter_rows([(1, "甲"), (2, "乙"), (3, "丙")]) == [(1, "甲"), (2, "乙"), (3, "丙")]


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
        chapter_text = kwargs["chapter_text"]
        if chapter_id == 2:
            # 2026-09-16 连接粒度：查询工厂收的是会话工厂，连接由查询服务按次取还
            service = kwargs["query_service_factory"](kwargs["session_factory"])
            search_result = service.search_pool(
                "住手",
                hidden_case_ids=set(),
            )
            assert all(isinstance(item, CaseSearchResult) for item in search_result.results)
            assert search_result.results[0].description == "该句住手由谁说出"
        return _agent_result(
            run_id=run_id,
            chapter_id=chapter_id,
            chapter_text=chapter_text,
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
        return _agent_result(
            run_id=run_id,
            chapter_id=kwargs["chapter_id"],
            chapter_text=kwargs["chapter_text"],
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
        select(func.count()).select_from(ChapterAnnotationRecord).where(ChapterAnnotationRecord.run_id == run_id)
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
        return _agent_result(
            run_id=run_id,
            chapter_id=1,
            chapter_text=kwargs["chapter_text"],
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
    # （M9a-2：insert_chapter_texts 补建的默认章行带"第N章"标题，标签取章标题）
    assert any(action == "thinking" for action, _content in emitted)


@pytest.mark.asyncio
async def test_run_annotate_uses_display_label_for_shifted_chapter_ids(db_session) -> None:
    """2026-08-12 用于验证卷标题占用编号导致 chapter_id 偏移时，消息展示真实章节序号"""
    novel_id, run_id = create_run_with_chunks(
        db_session,
        texts=["第一章"],
        chapter_ids=[2],
        title="编号偏移展示",
    )
    # M9a-2：insert_chapter_texts 已为章 2 补建默认结构行（标题"第2章"），
    # 卷行可直接插入；章 2 行改为更新展示字段，避免重复插入撞 chapters 主键
    db_session.add(
        Chapter(
            chapter_id=1,
            sequence=1,
            title="少年篇",
            display_title="少年篇",
            display_index_label=None,
            level="volume",
            start_pos=0,
            end_pos=10,
            run_id=run_id,
        )
    )
    chapter_row = db_session.execute(
        select(Chapter).where(
            Chapter.run_id == run_id,
            Chapter.chapter_id == 2,
        )
    ).scalar_one()
    chapter_row.title = "第一章 贺院三尺有顽童"
    chapter_row.display_title = "第一章 贺院三尺有顽童"
    chapter_row.display_index_label = "第1章"
    chapter_row.sequence = 2
    db_session.commit()
    emitted: list[StreamEvent] = []
    seen_labels: list[str | None] = []

    async def fake_agent(**kwargs):
        """2026-08-12 用于捕获 chapter_label 参数并返回合法章节结果"""
        seen_labels.append(kwargs.get("chapter_label"))
        return _agent_result(
            run_id=run_id,
            chapter_id=2,
            chapter_text=kwargs["chapter_text"],
        )

    async def emitter(event: StreamEvent) -> None:
        """2026-08-12 用于记录 workflow 级完整事件"""
        emitted.append(event)

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
    assert seen_labels == ["第1章"]
    # chapter_id=2 的展示标签为"第1章"，而非内部编号 2
    assert any(event.action == "thinking" for event in emitted)
    messages = [event.message for event in emitted if event.action == "progress"]
    assert messages


@pytest.mark.asyncio
async def test_run_annotate_dispatches_long_chapter_to_three_subagents(db_session, monkeypatch) -> None:
    """2026-09-19 双路径：正文超过 sub_chunk_max_chars 的章派发到 subagent 路径（三条职责并发），不超过走 agent 路径"""
    novel_id, run_id = create_run_with_chunks(
        db_session,
        texts=["第一章", "第二章正文远超十个字的门槛长度"],
        chapter_ids=[1, 2],
        title="双路径派发",
    )
    monkeypatch.setattr(settings.models.annotation, "sub_chunk_max_chars", 10)
    seen: list[tuple[int, tuple[str, ...]]] = []
    agent_calls: list[int] = []

    async def fake_subagents(**kwargs):
        """2026-09-19 用于捕获长章的派发与角色组合"""
        seen.append((kwargs["chapter_id"], tuple(kwargs.get("roles") or ("structure", "event", "evidence"))))
        return _agent_result(
            run_id=run_id,
            chapter_id=kwargs["chapter_id"],
            chapter_text=kwargs["chapter_text"],
        )

    async def fake_agent(**kwargs):
        """2026-09-19 用于接住短章的 agent 路径派发"""
        agent_calls.append(kwargs["chapter_id"])
        return _agent_result(
            run_id=run_id,
            chapter_id=kwargs["chapter_id"],
            chapter_text=kwargs["chapter_text"],
        )

    with (
        patch("src.workflows.annotate_helpers.block_codeact.run_chapter_subagents", new=fake_subagents),
        patch("src.agents.annotation.run_annotation_agent", new=fake_agent),
        patch("src.agents.llm.build_chat_model", return_value=MagicMock()),
    ):
        result = await run_annotate(
            run_id=run_id,
            session=db_session,
            novel_id=novel_id,
        )

    assert result == (2, 0, 2)
    # 章 1 正文不超门槛 → agent 路径；章 2 超门槛 → 三条职责 subagent
    assert agent_calls == [1]
    assert seen == [(2, ("structure", "event", "evidence"))]


@pytest.mark.asyncio
async def test_run_annotate_interrupts_after_failed_chapter_preserving_committed(db_session) -> None:
    """2026-08-13 用于验证第二章 Agent 失败时中断后续章节并抛出异常，第一章结果仍被保存

    中断语义：失败章未提交图版本，若后续章节继续提交会产生修订号空洞，
    resume 补跑失败章时与后续章节修订号冲突（uq_*_run_revision）且重试必败。
    中断后 run 收口 failed，resume 跳过已成功章节、仅重跑失败章及后续章节。
    """
    novel_id, run_id = create_run_with_chunks(
        db_session,
        texts=["第一章", "第二章", "第三章"],
        chapter_ids=[1, 2, 3],
        title="章节失败中断",
    )
    calls: list[int] = []

    async def fake_agent(**kwargs):
        """2026-08-13 用于让第二章 Agent 失败并记录执行顺序"""
        chapter_id = kwargs["chapter_id"]
        calls.append(chapter_id)
        if chapter_id == 2:
            raise RuntimeError("第二章标注失败")
        return _agent_result(
            run_id=run_id,
            chapter_id=chapter_id,
            chapter_text=kwargs["chapter_text"],
        )

    with (
        patch("src.agents.annotation.run_annotation_agent", new=fake_agent),
        patch("src.agents.llm.build_chat_model", return_value=MagicMock()),
    ):
        with pytest.raises(RuntimeError):
            await run_annotate(
                run_id=run_id,
                session=db_session,
                novel_id=novel_id,
            )

    # 失败章后不再执行后续章节（第三章未被调用），已成功章节保留提交
    assert calls == [1, 2]
    db_session.rollback()
    count = db_session.execute(
        select(func.count()).select_from(ChapterAnnotationRecord).where(ChapterAnnotationRecord.run_id == run_id)
    ).scalar_one()
    assert count == 1


@pytest.mark.asyncio
async def test_run_annotate_raises_when_all_chapters_fail(db_session) -> None:
    """2026-08-12 用于验证所有章节均失败时整个 run 抛出首个异常"""
    novel_id, run_id = create_run_with_chunks(
        db_session,
        texts=["第一章", "第二章"],
        chapter_ids=[1, 2],
        title="章节全部失败",
    )
    agent = MagicMock(side_effect=RuntimeError("标注失败"))

    async def failing_agent(**kwargs):
        """2026-08-12 用于模拟所有章节 Agent 失败"""
        return agent(**kwargs)

    with (
        patch("src.agents.annotation.run_annotation_agent", new=failing_agent),
        patch("src.agents.llm.build_chat_model", return_value=MagicMock()),
    ):
        with pytest.raises(RuntimeError):
            await run_annotate(
                run_id=run_id,
                session=db_session,
                novel_id=novel_id,
            )

    assert agent.call_count == 1
    db_session.rollback()
    count = db_session.execute(
        select(func.count()).select_from(ChapterAnnotationRecord).where(ChapterAnnotationRecord.run_id == run_id)
    ).scalar_one()
    assert count == 0
