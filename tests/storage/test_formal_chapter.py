"""正式章节独立提交、未来原文来源和不可变冲突"""

from __future__ import annotations

from uuid import uuid4

import pytest
from sqlalchemy import func, select

from src.agents.annotation.identity import stable_digest, text_digest
from src.agents.annotation.schema import (
    AgentRunAudit,
    AgentRunResult,
    BoundChapterAnnotation,
    ChapterMetricsInput,
)
from src.storage.db import get_session_factory
from src.storage.models import (
    AnalysisRun,
    Chapter,
    ChapterAnnotationRecord,
    Novel,
    Paragraph,
    ProjectionWorkItem,
    SemanticCommand,
    SourceManifest,
    TextEvidenceRecord,
)
from src.storage.repositories.formal_chapter import FormalChapterRepository
from src.storage.repositories.pipeline_work import ImmutableWorkConflict, PipelineWorkRepository

pytestmark = pytest.mark.usefixtures("pipeline_run_cleanup")


def _source() -> tuple[str, PipelineWorkRepository]:
    run_id = str(uuid4())
    source_hash = stable_digest(run_id, "source-manifest")
    novel_id = uuid4().hex[:8]
    with get_session_factory()() as session, session.begin():
        session.add(Novel(novel_id=novel_id, title="正式结果测试"))
        session.flush()
        session.add(AnalysisRun(run_id=run_id, novel_id=novel_id, status="running"))
        session.flush()
        for chapter_id, text in ((1, "第一章原文"), (2, "未来章节原文")):
            session.add(
                Chapter(
                    chapter_id=chapter_id,
                    run_id=run_id,
                    sequence=chapter_id,
                    title=f"第{chapter_id}章",
                    display_title=f"第{chapter_id}章",
                    level="chapter",
                    start_pos=0,
                    end_pos=len(text),
                    text=text,
                    char_offset=0,
                    char_end_offset=len(text),
                )
            )
            session.flush()
            session.add(
                Paragraph(
                    run_id=run_id,
                    paragraph_id=chapter_id,
                    chapter_id=chapter_id,
                    paragraph_index=0,
                    source_paragraph_index=0,
                    fragment_index=0,
                    local_start_char=0,
                    local_end_char=len(text),
                    global_start_char=chapter_id * 100,
                    global_end_char=chapter_id * 100 + len(text),
                    char_count=len(text),
                    token_count=4,
                    text=text,
                )
            )
    with get_session_factory()() as session, session.begin():
        session.add(SourceManifest(
            source_manifest_hash=source_hash, run_id=run_id,
            chapter_hashes={"1": text_digest("第一章原文"), "2": text_digest("未来章节原文")},
            paragraph_hashes={"1": text_digest("第一章原文"), "2": text_digest("未来章节原文")},
        ))
    queue = PipelineWorkRepository(get_session_factory())
    text = "第一章原文"
    queue.enqueue(
        run_id=run_id,
        work_kind="formal_current",
        logical_key="chapter:1",
        cutoff_hash=source_hash,
        payload={
            "chapter_id": 1,
            "chapter_sequence": 1,
            "source_manifest_hash": source_hash,
            "chapter_text_hash": text_digest(text),
            "paragraph_manifest_hash": stable_digest([(1, 0, len(text), text_digest(text))]),
        },
    )
    return run_id, queue


def _result(run_id: str, *, summary: str = "本章摘要") -> AgentRunResult:
    return AgentRunResult(
        run_id=run_id,
        chapter_id=1,
        annotation=BoundChapterAnnotation(
            metrics=ChapterMetricsInput(summary=summary, emotional_valence=0, narrative_function="铺垫"),
            character_observations=[],
            dialogues=[],
            events=[],
        ),
        entity_ops=[
            {
                "name": "甲",
                "entity_type": "character",
                "tags": [],
                "description": None,
                "attributes": {},
                "chapter_id": 1,
            }
        ],
        audit=AgentRunAudit(
            allow_future_context=True,
            write_records=[],
            authorized_text_paragraph_ids=[2],
        ),
    )


def test_formal_commit_records_future_source_and_projection_work() -> None:
    run_id, queue = _source()
    receipt = queue.claim(owner="formal-test", run_id=run_id)
    assert receipt is not None
    annotation_id = FormalChapterRepository(get_session_factory()).commit(receipt, _result(run_id))
    with get_session_factory()() as session:
        row = session.get(ChapterAnnotationRecord, annotation_id)
        assert row is not None
        assert row.formal_work_id == receipt.work_id
        assert row.payload_hash is not None
        assert session.execute(
            select(func.count()).select_from(TextEvidenceRecord).where(TextEvidenceRecord.run_id == run_id)
        ).scalar_one() == 2
        commands = list(session.execute(
            select(SemanticCommand).where(SemanticCommand.run_id == run_id)
        ).scalars())
        assert len(commands) == 2
        assert all(len(command.evidence_ids) == 2 for command in commands)
        assert session.execute(
            select(func.count()).select_from(ProjectionWorkItem).where(ProjectionWorkItem.run_id == run_id)
        ).scalar_one() == 2


def test_formal_commit_rejects_changed_source_without_partial_write() -> None:
    run_id, queue = _source()
    receipt = queue.claim(owner="formal-test", run_id=run_id)
    assert receipt is not None
    with get_session_factory()() as session, session.begin():
        chapter = session.get(Chapter, (1, run_id))
        assert chapter is not None
        chapter.text = "来源已经改变"
    with pytest.raises(ImmutableWorkConflict):
        FormalChapterRepository(get_session_factory()).commit(receipt, _result(run_id))
    with get_session_factory()() as session:
        assert session.execute(
            select(func.count()).select_from(ChapterAnnotationRecord).where(ChapterAnnotationRecord.run_id == run_id)
        ).scalar_one() == 0
