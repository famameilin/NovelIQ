"""并行正式提交、固定快照释放和进程恢复的真实 PostgreSQL 验证"""

from __future__ import annotations

import asyncio
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy import select

from src.agents.annotation.schema import AgentRunAudit, AgentRunResult, BoundChapterAnnotation, ChapterMetricsInput
from src.config import settings
from src.storage.db import get_session_factory
from src.storage.models import AnalysisCutoff, ChapterAnnotationRecord, WorkItem
from src.workflows.annotate import run_annotate
from tests.support.chapter_annotation_helpers import create_run_with_chunks

pytestmark = pytest.mark.usefixtures("pipeline_run_cleanup")


@pytest.mark.asyncio
async def test_chapters_run_concurrently_and_resume_does_not_call_model_again(db_session) -> None:
    novel_id, run_id = create_run_with_chunks(db_session, texts=["甲章原文", "乙章原文"], chapter_ids=[1, 2])
    active = 0
    peak = 0
    calls: list[int] = []
    both_started = asyncio.Event()

    async def fake_agent(**kwargs) -> AgentRunResult:
        nonlocal active, peak
        active += 1
        peak = max(peak, active)
        calls.append(kwargs["chapter_id"])
        assert not kwargs["graph_state"].entity_names
        if active == 2:
            both_started.set()
        await asyncio.wait_for(both_started.wait(), timeout=3)
        active -= 1
        return AgentRunResult(
            run_id=run_id, chapter_id=kwargs["chapter_id"],
            annotation=BoundChapterAnnotation(
                metrics=ChapterMetricsInput(summary="章节摘要", emotional_valence=0, narrative_function="铺垫"),
                character_observations=[], dialogues=[], events=[],
            ), audit=AgentRunAudit(allow_future_context=True, write_records=[], authorized_text_paragraph_ids=[]),
        )

    with patch("src.agents.annotation.run_annotation_agent", side_effect=fake_agent), patch(
        "src.agents.llm.build_chat_model", return_value=MagicMock()
    ), patch("src.models.local.embedding.EmbeddingClient", return_value=MagicMock()):
        assert await asyncio.wait_for(run_annotate(run_id, db_session, novel_id=novel_id), timeout=25) == (2, 0, 2)
        assert peak == 2
        assert await run_annotate(run_id, db_session, novel_id=novel_id) == (2, 0, 2)
        assert sorted(calls) == [1, 2]
    with get_session_factory()() as session:
        cutoff = session.execute(select(AnalysisCutoff).where(AnalysisCutoff.run_id == run_id)).scalar_one()
        assert cutoff.state == "released"
        annotations = session.execute(select(ChapterAnnotationRecord).where(
            ChapterAnnotationRecord.run_id == run_id
        )).scalars().all()
        assert len(annotations) == 2
        assert all(row.payload_hash for row in annotations)
        assert all(row.state == "succeeded" for row in session.execute(select(WorkItem).where(
            WorkItem.run_id == run_id
        )).scalars())


@pytest.mark.asyncio
async def test_model_pool_capacity_one_serializes_chapter_agents(db_session, monkeypatch) -> None:
    """2026-10-02 模型池分发：容量=1 时任意时刻只有 1 个 agent 在跑，其余章留在队列"""
    novel_id, run_id = create_run_with_chunks(db_session, texts=["甲章原文", "乙章原文"], chapter_ids=[1, 2])
    monkeypatch.setattr(settings.models.model_pool[0], "max_in_flight", 1)
    active = 0
    peak = 0

    async def formal(**kwargs) -> AgentRunResult:
        nonlocal active, peak
        active += 1
        peak = max(peak, active)
        await asyncio.sleep(0.02)
        active -= 1
        return AgentRunResult(
            run_id=run_id, chapter_id=kwargs["chapter_id"],
            annotation=BoundChapterAnnotation(
                metrics=ChapterMetricsInput(summary="章节摘要", emotional_valence=0, narrative_function="铺垫"),
                character_observations=[], dialogues=[], events=[],
            ), audit=AgentRunAudit(allow_future_context=True, write_records=[], authorized_text_paragraph_ids=[]),
        )

    with patch("src.agents.annotation.run_annotation_agent", side_effect=formal), patch(
        "src.agents.llm.build_chat_model", return_value=MagicMock()
    ), patch(
        "src.models.local.embedding.EmbeddingClient", return_value=MagicMock()
    ):
        assert await asyncio.wait_for(run_annotate(run_id, db_session, novel_id=novel_id), timeout=25) == (2, 0, 2)
    assert peak == 1
