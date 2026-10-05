"""章节任意完成顺序下的精确原文连接、冲突入池与正式结果不变"""

from __future__ import annotations

from unittest.mock import patch

import pytest
from sqlalchemy import select

from src.agents.annotation.fact_graph import mention_uuid
from src.agents.annotation.identity import stable_uuid, text_digest
from src.agents.annotation.schema import (
    AgentRunAudit,
    AgentRunResult,
    BoundChapterAnnotation,
    BoundEvent,
    ChapterMetricsInput,
    CrossChapterLink,
    SourceReference,
)
from src.storage.db import get_session_factory
from src.storage.models import (
    CaseHead,
    ChapterAnnotationRecord,
    CommandOutcome,
    ContinuityCase,
    EventEdge,
    GraphEntity,
    Paragraph,
    SemanticCommand,
    TextEvidenceRecord,
)
from src.storage.repositories.formal_chapter import FormalChapterRepository
from src.storage.repositories.pipeline_projection import PipelineProjectionRepository
from src.storage.repositories.pipeline_source import prepare_formal_work
from src.workflows.annotate import project_and_release
from tests.support.chapter_annotation_helpers import create_run_with_chunks

pytestmark = pytest.mark.usefixtures("pipeline_run_cleanup")


def _reference(chapter_id: int, paragraph_id: int, text: str, quote: str) -> SourceReference:
    start = text.index(quote)
    return SourceReference(chapter_id=chapter_id, paragraph_id=paragraph_id, char_start=start,
                           char_end=start + len(quote), text_hash=text_digest(quote))


def _result(run_id: str, chapter_id: int, references: list[SourceReference],
            *, kind: str = "same_entity", target: SourceReference | None = None) -> AgentRunResult:
    event = kind in {"causal", "foreshadowing"}
    record = "t1/root" if event else "entity/甲"
    return AgentRunResult(
        run_id=run_id, chapter_id=chapter_id,
        entity_ops=[] if event else [{"name": "甲", "entity_type": "character", "attributes": {}, "tags": []}],
        annotation=BoundChapterAnnotation(
            metrics=ChapterMetricsInput(summary="本章独立结论", emotional_valence=0, narrative_function="铺垫"),
            character_observations=[], dialogues=[],
            events=[BoundEvent(node_id=stable_uuid(run_id, chapter_id, "event_node", "t1", "root"),
                               tree_id=stable_uuid(run_id, chapter_id, "event_tree", "t1"),
                               cause_role="root", description="本章事件",
                               evidence_paragraph_id=references[0].paragraph_id,
                               is_foreshadow_setup=kind == "foreshadowing", payoff_likelihood="high")]
            if event else [],
        ),
        audit=AgentRunAudit(allow_future_context=True, write_records=[],
                            authorized_text_paragraph_ids=[target.paragraph_id] if target else [],
                            source_anchors={record: references}),
        cross_chapter_links=[CrossChapterLink(record_id=record, kind=kind, source=references[0], target=target)]
        if target else [],
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("completion_order", [(1, 2), (2, 1)])
@pytest.mark.parametrize("mode", ["same_entity", "conflict", "missing", "ambiguous", "causal", "foreshadowing"])
async def test_chapter_links_connect_without_second_model_round(db_session, completion_order, mode) -> None:
    _, run_id = create_run_with_chunks(db_session, texts=["甲是阿青。", "甲带来了消息。"], chapter_ids=[1, 2])
    factory = get_session_factory()
    by_chapter = {receipt.payload["chapter_id"]: receipt for receipt in prepare_formal_work(factory, run_id)}
    paragraphs = list(db_session.execute(select(Paragraph).where(Paragraph.run_id == run_id)
                      .order_by(Paragraph.chapter_id)).scalars())
    references = {row.chapter_id: _reference(row.chapter_id, row.paragraph_id, row.text, "甲") for row in paragraphs}
    kind = mode if mode in {"causal", "foreshadowing"} else "same_entity"
    results = {chapter_id: _result(run_id, chapter_id, [references[chapter_id]], kind=kind,
                                    target=references[2] if chapter_id == 1 else None) for chapter_id in (1, 2)}
    if mode == "conflict":
        results[2] = _result(run_id, 2, [references[2]], kind="different_entity", target=references[1])
    elif mode == "missing":
        results[2].audit.source_anchors = {}
    elif mode == "ambiguous":
        results[2].entity_ops.append({"name": "乙", "entity_type": "character", "attributes": {}, "tags": []})
        results[2].audit.source_anchors["entity/乙"] = [references[2]]
    formal = FormalChapterRepository(factory)
    for chapter_id in completion_order:
        formal.commit(by_chapter[chapter_id], results[chapter_id])
    projector = PipelineProjectionRepository(factory)
    with patch("src.agents.annotation.run_annotation_agent") as model:
        cutoff = projector.seal(run_id, round_kind="formal", round_number=0)
        await project_and_release(projector, cutoff)
        model.assert_not_called()
    with factory() as session:
        annotations = list(session.execute(select(ChapterAnnotationRecord).where(
            ChapterAnnotationRecord.run_id == run_id)).scalars())
        assert len(annotations) == 2
        assert all(row.payload == results[row.chapter_id].annotation.model_dump(mode="json") for row in annotations)
        cases = list(session.execute(select(ContinuityCase).where(ContinuityCase.run_id == run_id)).scalars())
        if mode == "same_entity":
            assert not cases
            entities = list(session.execute(select(GraphEntity).where(GraphEntity.run_id == run_id)).scalars())
            assert {row.attributes["canonical_entity_id"] for row in entities} == {mention_uuid(run_id, 1, "甲")}
        elif mode in {"causal", "foreshadowing"}:
            assert not cases
            edge = session.execute(select(EventEdge).where(EventEdge.run_id == run_id)).scalar_one()
            assert (edge.source_chapter_id, edge.target_chapter_id, edge.edge_type) == (1, 2, mode)
        else:
            assert cases and all(len(row.source_evidence) >= 2 for row in cases)
            assert all(session.get(CaseHead, row.case_id).state == ("contested" if mode == "conflict" else "pending")
                       for row in cases)
        links = list(session.execute(select(SemanticCommand).where(
            SemanticCommand.run_id == run_id, SemanticCommand.command_kind == "cross_chapter_link")).scalars())
        for link in links:
            assert len(link.evidence_ids) == 2
            for identifier in link.evidence_ids:
                evidence = session.get(TextEvidenceRecord, identifier)
                assert evidence.char_end - evidence.char_start == 1
        if mode == "conflict":
            bindings = session.execute(select(SemanticCommand).where(
                SemanticCommand.run_id == run_id, SemanticCommand.command_kind == "identity_binding")).scalars()
            assert all(session.get(CommandOutcome, item.command_id).state == "conflict" for item in bindings)


def test_invalid_cross_chapter_span_rolls_back_entire_chapter(db_session) -> None:
    _, run_id = create_run_with_chunks(db_session, texts=["甲出现。", "甲回应。"], chapter_ids=[1, 2])
    factory = get_session_factory()
    receipt = prepare_formal_work(factory, run_id)[0]
    paragraphs = list(db_session.execute(select(Paragraph).where(Paragraph.run_id == run_id)
                      .order_by(Paragraph.chapter_id)).scalars())
    references = {row.chapter_id: _reference(row.chapter_id, row.paragraph_id, row.text, "甲") for row in paragraphs}
    current = receipt.payload["chapter_id"]
    target = references[3 - current].model_copy(update={"text_hash": "invalid"})
    result = _result(run_id, current, [references[current]], target=target)
    with pytest.raises(ValueError, match="哈希"):
        FormalChapterRepository(factory).commit(receipt, result)
    with factory() as session:
        assert not list(session.execute(select(ChapterAnnotationRecord).where(
            ChapterAnnotationRecord.run_id == run_id)).scalars())
