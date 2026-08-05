from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.agents.annotation import AnnotationAgentRunError
from src.api.models.events import StreamEvent
from src.workflows.annotate import (
    _build_chapter_context,
    _group_chunks_by_chapter,
    _iter_dispatch_waves,
    run_annotate,
)


def test_group_chunks_by_chapter_preserves_chapter_and_chunk_order() -> None:
    """
    2026-08-02 用于验证 dispatcher 按数据库顺序稳定分组章节与子块
    """
    grouped = _group_chunks_by_chapter(
        [
            (0, 1, "第一块"),
            (1, 1, "第二块"),
            (2, 2, "第三块"),
        ]
    )

    assert grouped == [
        (1, [(0, "第一块"), (1, "第二块")]),
        (2, [(2, "第三块")]),
    ]


def test_build_chapter_context_only_reads_preceding_sibling_chunks() -> None:
    """
    2026-08-04 用于验证子块上下文仅包含当前块之前的同章原文
    """
    chapter_chunks = [(10, "甲" * 20), (11, "乙" * 20)]

    first_context = _build_chapter_context(
        chapter_chunks,
        current_chunk_id=10,
        max_context_chunks=8,
        max_chars_per_chunk=10,
    )
    second_context = _build_chapter_context(
        chapter_chunks,
        current_chunk_id=11,
        max_context_chunks=8,
        max_chars_per_chunk=10,
    )

    assert first_context is None
    assert second_context is not None and "chunk 10" in second_context
    assert "甲" * 10 in second_context
    assert "乙" not in second_context


def test_iter_dispatch_waves_respects_max_sub_agents() -> None:
    """
    2026-08-02 用于保证每个 dispatcher 波次的子代理数量不超过配置上限
    """
    chunks = [(index, str(index)) for index in range(7)]

    waves = _iter_dispatch_waves(chunks, max_sub_agents=3)

    assert [len(wave) for wave in waves] == [3, 3, 1]
    assert [chunk_id for wave in waves for chunk_id, _text in wave] == list(range(7))


@pytest.mark.asyncio
async def test_run_annotate_dispatches_multi_chunk_chapter_as_sub_agents() -> None:
    """
    2026-08-02 用于验证多子块章节通过 workflow 入口发送子代理事件与章节上下文
    """
    mock_session = MagicMock()
    mock_chunk_repo = MagicMock()
    mock_chunk_repo.fetch_chunks_with_chapter.return_value = [
        (0, 1, "顾霜进入山门"),
        (1, 1, "贺重明在殿中等候"),
    ]
    agent_calls: list[dict] = []
    emitted: list[StreamEvent] = []
    evidence_service = MagicMock()
    evidence_service.requires_level3.return_value = True
    evidence_service.ensure_level3_ready = AsyncMock()

    async def fake_run_annotation_agent(**kwargs):
        """
        2026-08-02 用于记录 workflow 委派给标注 Agent 的真实参数
        """
        agent_calls.append(kwargs)
        result = SimpleNamespace(
            annotation=MagicMock(),
            foreshadowing=None,
            dialogue_speakers=None,
            dialogues=None,
            dialogue_tones=None,
            dialogue_identity_clues=None,
            relations=None,
        )
        return result, kwargs["memory"]

    async def capture(event: StreamEvent) -> None:
        """
        2026-08-02 用于收集章节 dispatcher 发出的进度事件
        """
        emitted.append(event)

    with (
        patch("src.workflows.annotate.ChunkRepository", return_value=mock_chunk_repo),
        patch("src.agents.annotation.run_annotation_agent", new=fake_run_annotation_agent),
        patch("src.agents.annotation.save_identity_memory"),
        patch("src.agents.llm.build_chat_model", return_value=MagicMock()),
        patch(
            "src.workflows.annotate_helpers._init_evidence_service",
            return_value=evidence_service,
        ),
        patch(
            "src.workflows.annotate_helpers._extract_and_save_global_context",
            new=AsyncMock(return_value="全局上下文"),
        ),
        patch("src.workflows.annotate_helpers._store_annotation_results"),
        patch("src.workflows.annotate_helpers.project_graph_tables"),
    ):
        result = await run_annotate(
            run_id="run-1",
            session=mock_session,
            novel_id="novel-1",
            emitter=capture,
        )

    assert result == (2, 0, 2)
    assert len(agent_calls) == 2
    assert agent_calls[0]["chapter_context"] is None
    assert "chunk 0" in agent_calls[1]["chapter_context"]
    assert any(event.sub_stage == "sub_agent" for event in emitted)
    assert emitted[-1].sub_stage == "sub_agent"
    assert emitted[-1].sub_percent == 100.0
    evidence_service.ensure_level3_ready.assert_not_awaited()


@pytest.mark.asyncio
async def test_run_annotate_retries_chunk_with_configured_fallback_model() -> None:
    """
    2026-08-04 用于验证主标注 Agent 失败时同一 chunk 会切换 annotation_fallback 重试
    """
    mock_session = MagicMock()
    mock_chunk_repo = MagicMock()
    mock_chunk_repo.fetch_chunks_with_chapter.return_value = [(0, 1, "顾霜进入山门")]
    evidence_service = MagicMock()
    evidence_service.requires_level3.return_value = False
    evidence_service.ensure_level3_ready = AsyncMock()
    agent_calls: list[dict] = []

    async def fake_run_annotation_agent(**kwargs):
        """
        2026-08-04 用于模拟主模型失败和兜底模型成功的标注结果
        """
        agent_calls.append(kwargs)
        if kwargs["model_task_type"] == "annotation":
            raise AnnotationAgentRunError("primary unavailable")
        result = SimpleNamespace(
            annotation=MagicMock(),
            foreshadowing=None,
            dialogue_speakers=None,
            dialogues=None,
            dialogue_tones=None,
            dialogue_identity_clues=None,
            relations=None,
        )
        return result, kwargs["memory"]

    with (
        patch("src.workflows.annotate.ChunkRepository", return_value=mock_chunk_repo),
        patch("src.agents.annotation.run_annotation_agent", new=fake_run_annotation_agent),
        patch("src.agents.annotation.save_identity_memory"),
        patch("src.agents.llm.build_chat_model", side_effect=[MagicMock(), MagicMock()]) as build_model,
        patch("src.workflows.annotate_helpers._init_evidence_service", return_value=evidence_service),
        patch("src.workflows.annotate_helpers._extract_and_save_global_context", new=AsyncMock(return_value="上下文")),
        patch("src.workflows.annotate_helpers._store_annotation_results"),
        patch("src.workflows.annotate_helpers.project_graph_tables"),
        patch("src.workflows.annotate.settings.analysis.annotation_fallback_enabled", True),
    ):
        result = await run_annotate(run_id="run-1", session=mock_session, novel_id="novel-1")

    assert result == (1, 0, 1)
    assert [call["model_task_type"] for call in agent_calls] == ["annotation", "annotation_fallback"]
    assert [call.args[0] for call in build_model.call_args_list] == ["annotation", "annotation_fallback"]
