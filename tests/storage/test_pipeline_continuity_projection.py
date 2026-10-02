"""真实 PostgreSQL 验证正式不可变、连续性派生与释放栅栏"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select

from src.agents.annotation.fact_graph import mention_uuid
from src.agents.annotation.identity import stable_digest, stable_uuid, text_digest
from src.agents.annotation.schema import (
    AgentRunAudit,
    AgentRunResult,
    BoundChapterAnnotation,
    BoundCharacterObservation,
    BoundDialogue,
    BoundEvent,
    ChapterMetricsInput,
    PendingCase,
)
from src.storage.db import get_session_factory
from src.storage.models import (
    AnalysisCutoff,
    AnalysisRun,
    CaseHead,
    Chapter,
    ChapterAnnotationRecord,
    DialogueRecord,
    EventEdge,
    EventOutbox,
    GraphEntity,
    GraphFact,
    Paragraph,
    ProjectionWorkItem,
    RelationState,
    SemanticCommand,
    TextEvidenceRecord,
)
from src.storage.repositories.annotation.repository import AnnotationRepository
from src.storage.repositories.formal_chapter import FormalChapterRepository
from src.storage.repositories.pipeline_continuity import CaseClaimLost, PipelineContinuityRepository
from src.storage.repositories.pipeline_projection import CutoffNotReady, PipelineProjectionRepository
from src.storage.repositories.pipeline_source import prepare_formal_work
from src.storage.repositories.pipeline_visibility import cutoff_view, dialogue_continuity
from src.storage.repositories.pipeline_work import ImmutableWorkConflict, PipelineWorkRepository
from src.workflows.pipeline_materialization import materialize_cutoff
from tests.support.chapter_annotation_helpers import create_run_with_chunks

pytestmark = pytest.mark.usefixtures("pipeline_run_cleanup")


def test_cutoff_history_keeps_previous_case_snapshot_after_new_head(db_session) -> None:
    run_id, case_id, source_hash = _source(db_session)
    factory = get_session_factory()
    projections = PipelineProjectionRepository(factory)
    original = projections.latest_released(run_id)
    assert original is not None
    with factory() as session:
        before = cutoff_view(session, session.get(AnalysisCutoff, original["cutoff_hash"]))
    receipt = _continuity(run_id, case_id, source_hash)
    repository = PipelineContinuityRepository(factory)
    claim = repository.claim(receipt, case_id)
    repository.commit(receipt, claim, state="deferred", reason="原文尚不能消除歧义")
    cutoff_hash = projections.seal(run_id, round_kind="continuity", round_number=1)
    _project(projections, cutoff_hash)
    with factory() as session:
        after = cutoff_view(session, session.get(AnalysisCutoff, original["cutoff_hash"]))
        current = cutoff_view(session, session.get(AnalysisCutoff, cutoff_hash))
    assert before == after
    assert after["case_states"]["pending"] == 1 and current["case_states"]["deferred"] == 1
    assert current["evidence"][0]["text"]


def test_pending_event_dependency_is_released_explicitly_without_dangling_edge(db_session) -> None:
    run_id, _, _ = _source(db_session)
    factory = get_session_factory()
    command_id = stable_digest(run_id, "pending-event-link")
    with factory() as session, session.begin():
        origin = session.execute(select(SemanticCommand).where(
            SemanticCommand.run_id == run_id, SemanticCommand.command_kind == "event",
        ).limit(1)).scalar_one()
        payload = {"root_event_id": origin.payload["node_id"], "event_id": "not-yet-present"}
        session.add(SemanticCommand(
            command_id=command_id, run_id=run_id, origin_annotation_id=origin.origin_annotation_id,
            origin_chapter_id=origin.origin_chapter_id, origin_chapter_sequence=origin.origin_chapter_sequence,
            command_path="test/pending-link", command_kind="event_link", partition_key=f"eventlink:{command_id}",
            effective_document_position={}, payload=payload, payload_hash=stable_digest(payload),
            evidence_ids=origin.evidence_ids, author_work_id=origin.author_work_id,
        ))
        session.flush()
        session.add(ProjectionWorkItem(projection_id=command_id, run_id=run_id, command_id=command_id,
                                       partition_key=f"eventlink:{command_id}"))
    projections = PipelineProjectionRepository(factory)
    cutoff_hash = projections.seal(run_id, round_kind="continuity", round_number=1)
    _project(projections, cutoff_hash)
    with factory() as session, session.begin():
        session.get(AnalysisRun, run_id).annotation_cutoff_hash = cutoff_hash
        cutoff = session.get(AnalysisCutoff, cutoff_hash)
        snapshot = cutoff_view(session, cutoff)
        assert cutoff.state == "released" and snapshot["pending_dependency_count"] == 1
        assert snapshot["domain_values"][0]["state"] == "pending_dependency"
        assert not list(session.execute(select(EventEdge).where(EventEdge.run_id == run_id)).scalars())


def test_conflicting_later_parent_retracts_only_derived_relation_not_formal_or_fact_log(db_session) -> None:
    from src.storage.repositories.graph.repository import GraphRepository

    run_id, case_id, source_hash = _source(db_session, domain="relation")
    factory = get_session_factory()
    receipt = _continuity(run_id, case_id, source_hash)
    continuity = PipelineContinuityRepository(factory)
    claim = continuity.claim(receipt, case_id)
    continuity.commit(receipt, claim, state="resolved", evidence=_evidence(run_id), resolution={
        "from_entity_id": mention_uuid(run_id, 1, "顾霜"), "to_entity_id": mention_uuid(run_id, 1, "林渡"),
        "relation_type": "盟友", "change_kind": "retract",
    })
    projections = PipelineProjectionRepository(factory)
    _project(projections, projections.seal(run_id, round_kind="continuity", round_number=1))
    with factory() as session, session.begin():
        original_parent = session.execute(select(SemanticCommand).where(
            SemanticCommand.run_id == run_id, SemanticCommand.command_kind == "case_resolution",
        )).scalar_one()
        original_child = session.execute(select(SemanticCommand).where(
            SemanticCommand.parent_command_id == original_parent.command_id,
        )).scalar_one()
        original_fact = session.execute(select(GraphFact).where(
            GraphFact.run_id == run_id, GraphFact.payload_path == f"commands/{original_child.command_id}",
        )).scalar_one()
        fact_id = original_fact.fact_id
        payload = {**original_parent.payload, "resolution": {"conclusion": "另一个独立案例证据互斥"}}
        payload["domain_command"] = None
        command_id = stable_digest(run_id, "conflicting-parent")
        session.add(SemanticCommand(
            command_id=command_id, run_id=run_id, origin_annotation_id=original_parent.origin_annotation_id,
            origin_chapter_id=original_parent.origin_chapter_id,
            origin_chapter_sequence=original_parent.origin_chapter_sequence, command_path="test/conflicting-parent",
            command_kind="case_resolution", partition_key=original_parent.partition_key,
            effective_document_position=original_parent.effective_document_position,
            payload=payload, payload_hash=stable_digest(payload), evidence_ids=original_parent.evidence_ids,
            author_work_id=original_parent.author_work_id,
        ))
        session.flush()
        session.add(ProjectionWorkItem(projection_id=command_id, run_id=run_id, command_id=command_id,
                                       partition_key=original_parent.partition_key))
    cutoff_hash = projections.seal(run_id, round_kind="continuity", round_number=2)
    _project(projections, cutoff_hash)
    with factory() as session, session.begin():
        session.get(AnalysisRun, run_id).annotation_cutoff_hash = cutoff_hash
        session.flush()
        history, _ = GraphRepository(session).fetch_changes(run_id)
        assert fact_id not in {item.fact_id for item in history}
        assert session.get(GraphFact, original_fact.graph_fact_id) is not None
        assert len(list(session.execute(select(ChapterAnnotationRecord).where(
            ChapterAnnotationRecord.run_id == run_id,
        )).scalars())) == 2


def _project(projections: PipelineProjectionRepository, cutoff_hash: str) -> None:
    while projections.project_next(cutoff_hash):
        pass
    projections.release(cutoff_hash, materialize=materialize_cutoff)


def _source(db_session, *, domain: str = "dialogue", relation_type: str = "盟友") -> tuple[str, str, str]:
    _, run_id = create_run_with_chunks(db_session, texts=['顾霜喊道：“住手！”', '顾霜承认先前的喊声属于自己'],
                                       chapter_ids=[1, 2])
    factory = get_session_factory()
    prepare_formal_work(factory, run_id)
    queue = PipelineWorkRepository(factory)
    source_hash = ""
    case_id = ""
    for _ in range(2):
        receipt = queue.claim(owner="formal", run_id=run_id)
        assert receipt is not None
        chapter_id = receipt.payload["chapter_id"]
        source_hash = receipt.cutoff_hash
        with factory() as session:
            paragraph = session.execute(select(Paragraph).where(
                Paragraph.run_id == run_id, Paragraph.chapter_id == chapter_id,
            )).scalar_one()
            paragraph_id = paragraph.paragraph_id
            text = paragraph.text
        dialogues = [BoundDialogue(candidate_index=1, candidate_key="dialogue-1", content="住手！",
                                   start=6, end=9, speaker=None)] if chapter_id == 1 else []
        target = {"chapter_id": 1, "record_id": "dialogue/dialogue-1", "keys": ["顾霜"], "kind": "说话人"}
        if domain == "event":
            target = {"chapter_id": 1, "event_id": stable_uuid(run_id, 1, "event"), "kind": "伏笔"}
        if domain == "relation":
            target = {"chapter_id": 1, "record_id": f"relation/顾霜-林渡/{relation_type}", "kind": "关系"}
        case_id = stable_digest(run_id, "说话人", target, fold_text=True)
        seeds = [PendingCase(type="说话人", chapter_id=1, keys=["顾霜"], description="确认住手的说话人",
                             target_key=case_id, target_ref=target)] if chapter_id == 1 else []
        result = AgentRunResult(
            run_id=run_id, chapter_id=chapter_id, pushed_cases=seeds,
            entity_ops=[{"name": "顾霜", "entity_type": "character", "chapter_id": chapter_id,
                         "tags": ["主角"], "attributes": {"身份": "侠客"}}] + ([
                             {"name": "林渡", "entity_type": "character", "chapter_id": chapter_id,
                              "tags": [], "attributes": {}}
                         ] if domain == "relation" else []),
            relation_assert_ops=[{"from_entity": "顾霜", "to_entity": "林渡", "relation_type": relation_type,
                                  "attributes": {}, "chapter_id": chapter_id}] if domain == "relation" else [],
            annotation=BoundChapterAnnotation(
                metrics=ChapterMetricsInput(summary=text, emotional_valence=0, narrative_function="铺垫"),
                character_observations=[BoundCharacterObservation(character="顾霜", role_function="主体",
                                                                  action="回应", emotion=chapter_id - 1)],
                dialogues=dialogues,
                events=[BoundEvent(node_id=stable_uuid(run_id, chapter_id, "event"),
                                   tree_id=stable_uuid(run_id, chapter_id, "tree"), cause_role="root",
                                   description=text, evidence_paragraph_id=paragraph_id,
                                   is_foreshadow_setup=chapter_id == 1,
                                   payoff_likelihood="high" if chapter_id == 1 else None)],
            ), audit=AgentRunAudit(allow_future_context=True, write_records=[],
                                  authorized_text_paragraph_ids=[]),
        )
        FormalChapterRepository(factory).commit(receipt, result)
    projections = PipelineProjectionRepository(factory)
    boundary = projections.seal(run_id, round_kind="formal", round_number=0)
    _project(projections, boundary)
    return run_id, case_id, source_hash


def _continuity(run_id: str, case_id: str, source_hash: str, *, logical_key: str = "case"):
    factory = get_session_factory()
    boundary = PipelineProjectionRepository(factory).latest_released(run_id)
    assert boundary is not None
    queue = PipelineWorkRepository(factory)
    queue.enqueue(run_id=run_id, work_kind="continuity", logical_key=logical_key,
                  cutoff_hash=boundary["cutoff_hash"],
                  payload={"case_id": case_id, "source_manifest_hash": source_hash})
    receipt = queue.claim(owner="continuity", run_id=run_id, work_kind="continuity")
    assert receipt is not None
    return receipt


def _evidence(run_id: str) -> list[dict]:
    with get_session_factory()() as session:
        paragraph = session.execute(select(Paragraph).where(
            Paragraph.run_id == run_id, Paragraph.chapter_id == 2,
        )).scalar_one()
        return [{"paragraph_id": paragraph.paragraph_id, "char_start": 0, "char_end": len(paragraph.text),
                 "text_hash": text_digest(paragraph.text)}]


def test_continuity_speaker_uses_future_evidence_without_overwriting_formal_value(db_session) -> None:
    run_id, case_id, source_hash = _source(db_session)
    factory = get_session_factory()
    with factory() as session:
        original = session.execute(select(ChapterAnnotationRecord).where(
            ChapterAnnotationRecord.run_id == run_id, ChapterAnnotationRecord.chapter_id == 1,
        )).scalar_one().payload
    receipt = _continuity(run_id, case_id, source_hash)
    repository = PipelineContinuityRepository(factory)
    claim = repository.claim(receipt, case_id)
    command_id = repository.commit(receipt, claim, state="resolved", reason="后文明确承认喊声",
                                   resolution={"speaker_entity_id": mention_uuid(run_id, 1, "顾霜")},
                                   evidence=_evidence(run_id))
    projections = PipelineProjectionRepository(factory)
    cutoff_hash = projections.seal(run_id, round_kind="continuity", round_number=1)
    _project(projections, cutoff_hash)
    with factory() as session:
        dialogue = session.execute(select(DialogueRecord).where(DialogueRecord.run_id == run_id)).scalar_one()
        assert dialogue.speaker is None
        assert session.execute(select(ChapterAnnotationRecord).where(
            ChapterAnnotationRecord.run_id == run_id, ChapterAnnotationRecord.chapter_id == 1,
        )).scalar_one().payload == original
        overlay = dialogue_continuity(session, run_id)["dialogue-1"]
        assert overlay["value"]["speaker_entity_id"] == mention_uuid(run_id, 1, "顾霜")
        assert AnnotationRepository(session).fetch_chapter_dialogues_full(run_id)[0].speaker == ["顾霜"]
        child = session.execute(select(SemanticCommand).where(
            SemanticCommand.parent_command_id == command_id,
        )).scalar_one()
        assert child.command_kind == "dialogue_attribution"
        entities = list(session.execute(select(GraphEntity).where(GraphEntity.run_id == run_id)).scalars())
        assert len(entities) == 2 and all(entity.tags == ["主角"] for entity in entities)
        assert {entity.entity_id for entity in entities} == {
            mention_uuid(run_id, chapter, "顾霜") for chapter in (1, 2)
        }
        assert len(list(session.execute(select(GraphFact).where(
            GraphFact.run_id == run_id, GraphFact.fact_type == "character_observation",
        )).scalars())) == 2


def test_claim_competition_expiry_and_old_epoch_rejection(db_session) -> None:
    run_id, case_id, source_hash = _source(db_session)
    factory = get_session_factory()
    first = _continuity(run_id, case_id, source_hash, logical_key="first")
    second = _continuity(run_id, case_id, source_hash, logical_key="second")
    repository = PipelineContinuityRepository(factory)
    old = repository.claim(first, case_id)
    with pytest.raises(CaseClaimLost):
        repository.claim(second, case_id)
    with factory() as session, session.begin():
        head = session.get(CaseHead, case_id)
        assert head is not None
        head.active_lease_expires_at = datetime.now(UTC) - timedelta(seconds=1)
    current = repository.claim(second, case_id)
    assert current.claim_epoch > old.claim_epoch
    with pytest.raises(CaseClaimLost):
        repository.commit(first, old, state="deferred")
    repository.commit(first, None)
    repository.commit(second, current, state="deferred", reason="本轮没有足够证据")
    projections = PipelineProjectionRepository(factory)
    _project(projections, projections.seal(run_id, round_kind="continuity", round_number=1))


def test_future_source_change_after_seal_blocks_release(db_session) -> None:
    run_id, case_id, source_hash = _source(db_session)
    receipt = _continuity(run_id, case_id, source_hash)
    repository = PipelineContinuityRepository(get_session_factory())
    repository.commit(receipt, repository.claim(receipt, case_id), state="deferred")
    projections = PipelineProjectionRepository(get_session_factory())
    cutoff_hash = projections.seal(run_id, round_kind="continuity", round_number=1)
    while projections.project_next(cutoff_hash):
        pass
    with get_session_factory()() as session, session.begin():
        chapter = session.get(Chapter, (2, run_id))
        assert chapter is not None
        chapter.text = "修改了未来正文"
    with pytest.raises(ImmutableWorkConflict):
        projections.release(cutoff_hash, materialize=materialize_cutoff)
    with get_session_factory()() as session:
        assert session.get(AnalysisCutoff, cutoff_hash).state != "released"


def test_corrupted_text_evidence_prevents_materialization(db_session) -> None:
    run_id, _, _ = _source(db_session)
    factory = get_session_factory()
    with factory() as session, session.begin():
        evidence = session.execute(select(TextEvidenceRecord).where(
            TextEvidenceRecord.run_id == run_id,
        ).limit(1)).scalar_one()
        evidence.text_hash = "0" * 64
    projections = PipelineProjectionRepository(factory)
    cutoff_hash = projections.seal(run_id, round_kind="continuity", round_number=1)
    while projections.project_next(cutoff_hash):
        pass
    with pytest.raises(ValueError, match="原文证据区间或哈希无效"):
        projections.release(cutoff_hash, materialize=materialize_cutoff)
    with factory() as session:
        cutoff = session.get(AnalysisCutoff, cutoff_hash)
        assert cutoff.state == "failed"
        assert "quality" not in cutoff.manifest


def test_reversed_event_dependency_prevents_materialization(db_session) -> None:
    run_id, _, _ = _source(db_session)
    factory = get_session_factory()
    with factory() as session, session.begin():
        first, second = session.execute(select(SemanticCommand).where(
            SemanticCommand.run_id == run_id, SemanticCommand.command_kind == "event",
        ).order_by(SemanticCommand.origin_chapter_sequence)).scalars()
        payload = {"root_event_id": second.payload["node_id"], "event_id": first.payload["node_id"],
                   "edge_type": "causal"}
        command_id = stable_digest(run_id, "reversed-event")
        session.add(SemanticCommand(
            command_id=command_id, run_id=run_id, command_kind="event_link", partition_key=f"cause:{command_id}",
            origin_annotation_id=first.origin_annotation_id, origin_chapter_id=first.origin_chapter_id,
            origin_chapter_sequence=first.origin_chapter_sequence, command_path="test/reversed-event",
            effective_document_position=first.effective_document_position, payload=payload,
            payload_hash=stable_digest(payload), evidence_ids=first.evidence_ids, author_work_id=first.author_work_id,
        ))
        session.flush()
        session.add(ProjectionWorkItem(projection_id=command_id, run_id=run_id, command_id=command_id,
                                       partition_key=f"cause:{command_id}"))
    projections = PipelineProjectionRepository(factory)
    cutoff_hash = projections.seal(run_id, round_kind="continuity", round_number=1)
    while projections.project_next(cutoff_hash):
        pass
    with pytest.raises(ValueError, match="事件依赖与文档偏序不一致"):
        projections.release(cutoff_hash, materialize=materialize_cutoff)
    with factory() as session:
        assert session.get(AnalysisCutoff, cutoff_hash).state == "failed"


def test_dead_letter_partition_blocks_release(db_session) -> None:
    run_id, case_id, source_hash = _source(db_session)
    receipt = _continuity(run_id, case_id, source_hash)
    repository = PipelineContinuityRepository(get_session_factory())
    repository.commit(receipt, repository.claim(receipt, case_id), state="deferred")
    projections = PipelineProjectionRepository(get_session_factory())
    cutoff_hash = projections.seal(run_id, round_kind="continuity", round_number=1)
    with get_session_factory()() as session, session.begin():
        item = session.execute(select(ProjectionWorkItem).where(
            ProjectionWorkItem.cutoff_hash == cutoff_hash,
        ).limit(1)).scalar_one()
        item.state = "dead_letter"
    with pytest.raises(CutoffNotReady):
        projections.release(cutoff_hash, materialize=materialize_cutoff)


def test_event_link_is_materialized_from_case_child_command(db_session) -> None:
    run_id, case_id, source_hash = _source(db_session, domain="event")
    receipt = _continuity(run_id, case_id, source_hash)
    repository = PipelineContinuityRepository(get_session_factory())
    repository.commit(receipt, repository.claim(receipt, case_id), state="resolved", reason="后文回应伏笔",
                      resolution={"event_id": stable_uuid(run_id, 2, "event"),
                                  "root_event_id": stable_uuid(run_id, 1, "event")}, evidence=_evidence(run_id))
    projections = PipelineProjectionRepository(get_session_factory())
    _project(projections, projections.seal(run_id, round_kind="continuity", round_number=1))
    with get_session_factory()() as session:
        edge = session.execute(select(EventEdge).where(EventEdge.run_id == run_id)).scalar_one()
        assert edge.edge_type == "foreshadowing"
        assert edge.evidence


def test_relation_overlay_follows_formal_at_same_position(db_session) -> None:
    run_id, case_id, source_hash = _source(db_session, domain="relation")
    factory = get_session_factory()
    receipt = _continuity(run_id, case_id, source_hash)
    repository = PipelineContinuityRepository(factory)
    repository.commit(receipt, repository.claim(receipt, case_id), state="resolved", reason="后文确认此前决裂",
                      resolution={"from_entity_id": mention_uuid(run_id, 1, "顾霜"),
                                  "to_entity_id": mention_uuid(run_id, 1, "林渡"),
                                  "relation_type": "盟友", "change_kind": "break"}, evidence=_evidence(run_id))
    projections = PipelineProjectionRepository(factory)
    _project(projections, projections.seal(run_id, round_kind="continuity", round_number=1))
    with factory() as session:
        states = list(session.execute(select(RelationState).where(
            RelationState.run_id == run_id,
        ).order_by(RelationState.chapter_id)).scalars())
        assert len(states) == 2
        assert states[0].is_active is False
        assert states[0].changes[-1]["change_kind"] == "break"
        assert states[1].is_active is True
        assert states[1].changes[-1]["change_kind"] == "assert"


def test_dialogue_case_cannot_modify_unrelated_event(db_session) -> None:
    run_id, case_id, source_hash = _source(db_session)
    receipt = _continuity(run_id, case_id, source_hash)
    repository = PipelineContinuityRepository(get_session_factory())
    with pytest.raises(ValueError, match="确切正式事件"):
        repository.commit(receipt, repository.claim(receipt, case_id), state="resolved",
                          resolution={"event_id": stable_uuid(run_id, 2, "event"),
                                      "root_event_id": stable_uuid(run_id, 1, "event")}, evidence=_evidence(run_id))


def test_materialization_failure_is_persisted_and_recoverable(db_session) -> None:
    run_id, case_id, source_hash = _source(db_session)
    factory = get_session_factory()
    receipt = _continuity(run_id, case_id, source_hash)
    repository = PipelineContinuityRepository(factory)
    repository.commit(receipt, repository.claim(receipt, case_id), state="deferred")
    projections = PipelineProjectionRepository(factory)
    cutoff_hash = projections.seal(run_id, round_kind="continuity", round_number=1)
    while projections.project_next(cutoff_hash):
        pass

    def fail_materialization(session, cutoff) -> None:
        raise RuntimeError("注入物化失败")

    with pytest.raises(RuntimeError, match="注入物化失败"):
        projections.release(cutoff_hash, materialize=fail_materialization)
    with factory() as session:
        assert session.get(AnalysisCutoff, cutoff_hash).state == "failed"
        assert session.execute(select(EventOutbox).where(
            EventOutbox.cutoff_hash == cutoff_hash, EventOutbox.event_type == "cutoff_materialization_failed",
        )).scalar_one()
    projections.resume_projection(cutoff_hash)
    _project(projections, cutoff_hash)


def test_source_whitespace_change_is_not_silently_normalized(db_session) -> None:
    run_id, case_id, source_hash = _source(db_session)
    receipt = _continuity(run_id, case_id, source_hash)
    repository = PipelineContinuityRepository(get_session_factory())
    repository.commit(receipt, repository.claim(receipt, case_id), state="deferred")
    with get_session_factory()() as session, session.begin():
        chapter = session.get(Chapter, (2, run_id))
        chapter.text = " " + chapter.text
    with pytest.raises(ImmutableWorkConflict, match="全书正文"):
        PipelineProjectionRepository(get_session_factory()).seal(run_id, round_kind="continuity", round_number=1)


def test_projector_fault_marks_only_attempted_partition_and_resume_keeps_acks(db_session) -> None:
    from unittest.mock import patch

    run_id, case_id, source_hash = _source(db_session)
    factory = get_session_factory()
    receipt = _continuity(run_id, case_id, source_hash)
    repository = PipelineContinuityRepository(factory)
    repository.commit(receipt, repository.claim(receipt, case_id), state="deferred")
    projections = PipelineProjectionRepository(factory)
    cutoff_hash = projections.seal(run_id, round_kind="continuity", round_number=1)
    assert projections.project_next(cutoff_hash)
    with patch("src.storage.repositories.pipeline_projection.reduce_partition", side_effect=RuntimeError("分区失败")):
        with pytest.raises(RuntimeError, match="分区失败"):
            projections.project_next(cutoff_hash)
    with factory() as session:
        items = list(session.execute(select(ProjectionWorkItem).where(
            ProjectionWorkItem.cutoff_hash == cutoff_hash,
        )).scalars())
        assert len({item.partition_key for item in items if item.state == "dead_letter"}) == 1
        assert any(item.state == "queued" for item in items)
        ack_ids = {item.projection_id: item.attempt_epoch for item in items if item.state == "ack"}
        assert ack_ids
    projections.resume_projection(cutoff_hash)
    _project(projections, cutoff_hash)
    with factory() as session:
        for identity, epoch in ack_ids.items():
            assert session.get(ProjectionWorkItem, identity).attempt_epoch == epoch


def test_local_same_character_merges_only_the_declared_chapter_pairs(db_session) -> None:
    run_id, _, _ = _source(db_session, domain="relation", relation_type="同一人物")
    with get_session_factory()() as session:
        entities = list(session.execute(select(GraphEntity).where(GraphEntity.run_id == run_id)).scalars())
        elected = [entity.entity_id for entity in entities if entity.attributes.get("is_representative")]
        expected = {min(mention_uuid(run_id, chapter, name) for name in ("顾霜", "林渡")) for chapter in (1, 2)}
        assert set(elected) == expected
