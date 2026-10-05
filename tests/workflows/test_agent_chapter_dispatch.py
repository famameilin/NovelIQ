"""统一 Agent 的独立章节调度、失败隔离和可见性合同"""

from __future__ import annotations

import asyncio
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy import select

from src.agents.annotation.candidates import extract_dialogue_candidates
from src.agents.annotation.identity import stable_digest
from src.agents.annotation.schema import (
    AgentRunAudit,
    AgentRunResult,
    BoundChapterAnnotation,
    BoundDialogue,
    ChapterMetricsInput,
    PendingCase,
)
from src.agents.stream import AgentStream
from src.storage.db import get_session_factory
from src.storage.models import AnalysisCutoff, Chapter, ChapterAnnotationRecord
from src.workflows.annotate import run_annotate
from src.workflows.chapter_pool import PipelineWorkFailed
from tests.support.chapter_annotation_helpers import create_run_with_chunks

pytestmark = pytest.mark.usefixtures("pipeline_run_cleanup")


def _agent_result(run_id: str, chapter_id: int, text: str, *, create_case: bool = False) -> AgentRunResult:
    dialogues: list[BoundDialogue] = []
    seeds: list[PendingCase] = []
    if create_case:
        candidate = extract_dialogue_candidates(chapter_id, text)[0]
        dialogues = [BoundDialogue(candidate_index=1, candidate_key=candidate.candidate_key,
                                   content=candidate.content, start=candidate.start, end=candidate.end, speaker=None)]
        target = {"chapter_id": chapter_id, "candidate_key": candidate.candidate_key, "kind": "说话人"}
        seeds = [PendingCase(type="说话人", chapter_id=chapter_id, keys=["住手"], description="说话人尚不明确",
                             target_key=stable_digest(run_id, "说话人", target, fold_text=True), target_ref=target)]
    return AgentRunResult(
        run_id=run_id, chapter_id=chapter_id, pushed_cases=seeds,
        annotation=BoundChapterAnnotation(
            metrics=ChapterMetricsInput(summary=text[:100], emotional_valence=0, narrative_function="铺垫"),
            character_observations=[], dialogues=dialogues, events=[],
        ), audit=AgentRunAudit(allow_future_context=True, write_records=[],
                              authorized_text_paragraph_ids=[]),
    )


@pytest.mark.asyncio
async def test_independent_chapter_graphs_keep_cases_without_full_book_rounds(db_session) -> None:
    novel_id, run_id = create_run_with_chunks(db_session, texts=['有人喊道：“住手！”', "次章回应"], chapter_ids=[1, 2])
    graphs = []
    both_started = asyncio.Event()

    async def formal(**kwargs):
        graphs.append(kwargs["graph_state"])
        assert not kwargs["graph_state"].entity_names
        if len(graphs) == 2:
            both_started.set()
        await asyncio.wait_for(both_started.wait(), timeout=3)
        return _agent_result(run_id, kwargs["chapter_id"], kwargs["chapter_text"],
                             create_case=kwargs["chapter_id"] == 1)

    with patch("src.agents.annotation.run_annotation_agent", side_effect=formal) as chapter_agent, patch(
        "src.agents.llm.build_chat_model", return_value=MagicMock()
    ), patch(
        "src.models.local.embedding.EmbeddingClient", return_value=MagicMock()
    ):
        assert await asyncio.wait_for(run_annotate(run_id, db_session, novel_id=novel_id), 20) == (2, 0, 2)
    assert len(graphs) == 2 and graphs[0] is not graphs[1]
    assert chapter_agent.call_count == 2
    with get_session_factory()() as session:
        committed = list(session.execute(select(ChapterAnnotationRecord.chapter_id).where(
            ChapterAnnotationRecord.run_id == run_id,
        )).scalars())
        assert sorted(committed) == [1, 2]


@pytest.mark.asyncio
async def test_run_annotate_passes_agent_stream_to_agent(db_session) -> None:
    novel_id, run_id = create_run_with_chunks(db_session, texts=["第一章"], chapter_ids=[1])
    emitted = []

    async def formal(**kwargs):
        assert isinstance(kwargs["stream"], AgentStream)
        await kwargs["stream"].thinking("正在核对原文")
        return _agent_result(run_id, 1, kwargs["chapter_text"])

    async def emit(event) -> None:
        emitted.append(event)

    with patch("src.agents.annotation.run_annotation_agent", side_effect=formal), patch(
        "src.agents.llm.build_chat_model", return_value=MagicMock()
    ), patch("src.models.local.embedding.EmbeddingClient", return_value=MagicMock()):
        assert await run_annotate(run_id, db_session, novel_id=novel_id, emitter=emit) == (1, 0, 1)
    assert any(event.action == "thinking" and event.chapter_id == 1 for event in emitted)
    assert any(event.action == "progress" and event.current == 1 for event in emitted)


@pytest.mark.asyncio
async def test_progress_uses_display_label_not_shifted_chapter_id(db_session) -> None:
    novel_id, run_id = create_run_with_chunks(db_session, texts=["第一章正文"], chapter_ids=[7])
    chapter = db_session.get(Chapter, (7, run_id))
    chapter.display_index_label = "第一章"
    db_session.commit()
    emitted = []

    async def formal(**kwargs):
        assert kwargs["chapter_id"] == 7
        assert kwargs["chapter_label"] == "第一章"
        return _agent_result(run_id, 7, kwargs["chapter_text"])

    async def emit(event) -> None:
        emitted.append(event)

    with patch("src.agents.annotation.run_annotation_agent", side_effect=formal), patch(
        "src.agents.llm.build_chat_model", return_value=MagicMock()
    ), patch("src.models.local.embedding.EmbeddingClient", return_value=MagicMock()):
        await run_annotate(run_id, db_session, novel_id=novel_id, emitter=emit)
    assert any(event.chapter_id == 7 and "第一章" in event.message for event in emitted)


@pytest.mark.asyncio
async def test_long_and_short_chapters_dispatch_by_length(db_session) -> None:
    """2026-10-02 双路径派发：短章走单 agent，长章（超过 sub_chunk_max_chars）走三条职责
    subagent 并发——两条路径都从 PipelineAgentExecutor.execute 进入，返回同构章级结果"""
    novel_id, run_id = create_run_with_chunks(db_session, texts=["短章", "长章原文。" * 5000], chapter_ids=[1, 2])
    agent_calls: list[int] = []
    subagent_calls: list[int] = []

    async def formal(**kwargs):
        agent_calls.append(kwargs["chapter_id"])
        return _agent_result(run_id, kwargs["chapter_id"], kwargs["chapter_text"])

    async def subagents(**kwargs):
        subagent_calls.append(kwargs["chapter_id"])
        assert kwargs["paragraph_info"] is not None
        assert kwargs["graph_state"] is not None
        return _agent_result(run_id, kwargs["chapter_id"], kwargs["chapter_text"])

    with patch("src.agents.annotation.run_annotation_agent", side_effect=formal), patch(
        "src.workflows.annotate_helpers.block_codeact.run_chapter_subagents", side_effect=subagents
    ), patch(
        "src.agents.llm.build_chat_model", return_value=MagicMock()
    ), patch("src.models.local.embedding.EmbeddingClient", return_value=MagicMock()):
        assert await run_annotate(run_id, db_session, novel_id=novel_id) == (2, 0, 2)
    assert agent_calls == [1]
    assert subagent_calls == [2]


@pytest.mark.asyncio
async def test_chapters_dispatch_in_sequence_order(db_session, monkeypatch) -> None:
    """2026-10-05 派发严格按章节序：容量 1 时 ch2 只能在 ch1 完成后启动"""
    from src.config import settings
    from src.config.schemas.model import WeightedModelSettings

    monkeypatch.setattr(settings.models, "model_pool", [
        WeightedModelSettings("seq-model", "https://seq.example/v1", "seq-key", max_in_flight=1),
    ])
    monkeypatch.setattr(settings.models.annotation, "total_attempts", 3)
    novel_id, run_id = create_run_with_chunks(db_session, texts=["第一章", "第二章"], chapter_ids=[1, 2])
    started: list[int] = []

    async def formal(**kwargs):
        started.append(kwargs["chapter_id"])
        await asyncio.sleep(0.01)
        return _agent_result(run_id, kwargs["chapter_id"], kwargs["chapter_text"])

    with patch("src.agents.annotation.run_annotation_agent", side_effect=formal), patch(
        "src.agents.llm.build_chat_model", return_value=MagicMock()
    ), patch("src.models.local.embedding.EmbeddingClient", return_value=MagicMock()):
        assert await run_annotate(run_id, db_session, novel_id=novel_id) == (2, 0, 2)
    assert started == [1, 2]


@pytest.mark.asyncio
async def test_resume_reruns_only_uncommitted_chapters(db_session, monkeypatch) -> None:
    """2026-10-05 重启恢复 = 重查无标注章节：已提交章不重跑，失败章按差集补跑"""
    from src.config import settings

    monkeypatch.setattr("src.workflows.chapter_pool.retry_delay", lambda epoch: 0)
    monkeypatch.setattr(settings.models.annotation, "total_attempts", 1)
    novel_id, run_id = create_run_with_chunks(db_session, texts=["第一章", "第二章"], chapter_ids=[1, 2])

    async def failing_first(**kwargs):
        if kwargs["chapter_id"] == 1:
            raise ValueError("注入终局失败")
        return _agent_result(run_id, 2, kwargs["chapter_text"])

    with patch("src.agents.annotation.run_annotation_agent", side_effect=failing_first), patch(
        "src.agents.llm.build_chat_model", return_value=MagicMock()
    ), patch("src.models.local.embedding.EmbeddingClient", return_value=MagicMock()), pytest.raises(PipelineWorkFailed):
        await run_annotate(run_id, db_session, novel_id=novel_id)

    monkeypatch.setattr(settings.models.annotation, "total_attempts", 3)
    resumed: list[int] = []

    async def formal(**kwargs):
        resumed.append(kwargs["chapter_id"])
        return _agent_result(run_id, kwargs["chapter_id"], kwargs["chapter_text"])

    with patch("src.agents.annotation.run_annotation_agent", side_effect=formal), patch(
        "src.agents.llm.build_chat_model", return_value=MagicMock()
    ), patch("src.models.local.embedding.EmbeddingClient", return_value=MagicMock()):
        assert await run_annotate(run_id, db_session, novel_id=novel_id) == (2, 0, 2)
    assert resumed == [1]


@pytest.mark.asyncio
@pytest.mark.parametrize("all_fail", [False, True])
async def test_failed_chapter_does_not_abort_other_work_or_release_partial_cutoff(
    db_session, all_fail, monkeypatch,
) -> None:
    novel_id, run_id = create_run_with_chunks(db_session, texts=["第一章", "第二章"], chapter_ids=[1, 2])
    calls: list[int] = []
    monkeypatch.setattr("src.workflows.chapter_pool.retry_delay", lambda epoch: 0)

    async def formal(**kwargs):
        calls.append(kwargs["chapter_id"])
        if all_fail or kwargs["chapter_id"] == 1:
            raise ValueError("注入不可重试的正式标注失败")
        return _agent_result(run_id, 2, kwargs["chapter_text"])

    with patch("src.agents.annotation.run_annotation_agent", side_effect=formal), patch(
        "src.agents.llm.build_chat_model", return_value=MagicMock()
    ), patch("src.models.local.embedding.EmbeddingClient", return_value=MagicMock()), pytest.raises(PipelineWorkFailed):
        await run_annotate(run_id, db_session, novel_id=novel_id)
    assert sorted(calls) == ([1] * 3 + [2] * 3 if all_fail else [1] * 3 + [2])
    with get_session_factory()() as session:
        committed = list(session.execute(select(ChapterAnnotationRecord.chapter_id).where(
            ChapterAnnotationRecord.run_id == run_id,
        )).scalars())
        assert committed == ([] if all_fail else [2])
        assert not list(session.execute(select(AnalysisCutoff).where(AnalysisCutoff.run_id == run_id)).scalars())
