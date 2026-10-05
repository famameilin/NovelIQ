"""跨章身份绑定与类型仲裁不改正式值，互斥主张不选最后写入者"""

from __future__ import annotations

import pytest
from sqlalchemy import select

from src.agents.annotation.fact_graph import mention_uuid
from src.agents.annotation.identity import stable_digest
from src.knowledge.authority.alias import build_alias_resolution
from src.storage.db import get_session_factory
from src.storage.models import (
    AnalysisCutoff,
    AnalysisRun,
    ChapterAnnotationRecord,
    CutoffPartition,
    GraphEntity,
    SemanticCommand,
)
from src.storage.repositories.graph.repository import GraphRepository
from src.storage.repositories.pipeline_cases import FollowUpCaseInput, follow_up_case_id
from src.storage.repositories.pipeline_continuity import PipelineContinuityRepository
from src.storage.repositories.pipeline_identity import identity_conflicts
from src.storage.repositories.pipeline_projection import PipelineProjectionRepository
from src.storage.repositories.pipeline_visibility import cutoff_view
from tests.storage.test_pipeline_continuity_projection import _continuity, _evidence, _project, _source
from tests.storage.test_pipeline_reducers import _command

pytestmark = pytest.mark.usefixtures("pipeline_run_cleanup")


def _identity_cases(db_session, *, two: bool = False):
    run_id, parent_id, source_hash = _source(db_session, domain="relation")
    factory = get_session_factory()
    repository = PipelineContinuityRepository(factory)
    receipt = _continuity(run_id, parent_id, source_hash)
    claim = repository.claim(receipt, parent_id)
    issue_kinds = ["身份线索一", "身份线索二"] if two else ["身份线索"]
    seeds = [FollowUpCaseInput(type=kind, description="核对两种称呼的身份", keys=["顾霜"],
                              target_ref={"domain": "entity", "entity_id": mention_uuid(run_id, 1, "顾霜")},
                              evidence=_evidence(run_id)) for kind in issue_kinds]
    repository.commit(receipt, claim, follow_up_cases=seeds)
    projections = PipelineProjectionRepository(factory)
    _project(projections, projections.seal(run_id, round_kind="continuity", round_number=1))
    return run_id, source_hash, [follow_up_case_id(run_id, seed) for seed in seeds]


def _publish(run_id: str, cutoff_hash: str) -> None:
    with get_session_factory()() as session, session.begin():
        session.get(AnalysisRun, run_id).annotation_cutoff_hash = cutoff_hash


def test_same_identity_projects_one_representative_without_renaming_formal_mentions(db_session) -> None:
    run_id, source_hash, case_ids = _identity_cases(db_session)
    factory = get_session_factory()
    with factory() as session:
        formal = {row.annotation_id: row.payload_hash for row in session.execute(select(ChapterAnnotationRecord).where(
            ChapterAnnotationRecord.run_id == run_id,
        )).scalars()}
    receipt = _continuity(run_id, case_ids[0], source_hash)
    repository = PipelineContinuityRepository(factory)
    command_id = repository.commit(receipt, repository.claim(receipt, case_ids[0]), state="resolved",
                                   evidence=_evidence(run_id), resolution={
        "entity_id": mention_uuid(run_id, 1, "顾霜"), "canonical_entity_id": mention_uuid(run_id, 1, "林渡"),
        "identity_kind": "same",
    })
    projections = PipelineProjectionRepository(factory)
    cutoff_hash = projections.seal(run_id, round_kind="continuity", round_number=2)
    _project(projections, cutoff_hash)
    _publish(run_id, cutoff_hash)
    with factory() as session:
        entities = list(session.execute(select(GraphEntity).where(GraphEntity.run_id == run_id)).scalars())
        assert {entity.canonical_name for entity in entities} == {"顾霜", "林渡"}
        involved = [entity for entity in entities if entity.first_seen_chapter == 1]
        representative = min(entity.entity_id for entity in involved)
        assert {entity.attributes["canonical_entity_id"] for entity in involved} == {representative}
        assert all(entity.attributes["canonical_entity_id"] == entity.entity_id
                   for entity in entities if entity.first_seen_chapter == 2)
        graph = GraphRepository(session)
        boundary = graph.resolve_chapter_boundary(run_id)
        aliases = build_alias_resolution(graph.fetch_relation_snapshots(boundary),
                                         entities=graph.fetch_entity_snapshots(boundary))
        assert aliases.resolve_entity_id(mention_uuid(run_id, 1, "顾霜")) == representative
        assert aliases.resolve_entity_id(mention_uuid(run_id, 1, "林渡")) == representative
        assert {row.annotation_id: row.payload_hash for row in session.execute(select(ChapterAnnotationRecord).where(
            ChapterAnnotationRecord.run_id == run_id,
        )).scalars()} == formal
        view = cutoff_view(session, session.get(AnalysisCutoff, cutoff_hash))
        identity = next(domain for domain in view["domain_values"] if domain["target"].startswith("alias:"))
        assert identity["state"] == "resolved" and len(identity["formal_values"]) == 2
        assert session.execute(select(SemanticCommand).where(
            SemanticCommand.parent_command_id == command_id,
        )).scalar_one().command_kind == "identity_binding"


def test_same_and_different_claims_remain_contested_with_both_evidence(db_session) -> None:
    run_id, source_hash, cases = _identity_cases(db_session, two=True)
    factory = get_session_factory()
    repository = PipelineContinuityRepository(factory)
    for case_id, kind in zip(cases, ("same", "different"), strict=True):
        receipt = _continuity(run_id, case_id, source_hash)
        repository.commit(receipt, repository.claim(receipt, case_id), state="resolved", evidence=_evidence(run_id),
                          resolution={"entity_id": mention_uuid(run_id, 1, "顾霜"), "identity_kind": kind,
                                      "canonical_entity_id": mention_uuid(run_id, 1, "林渡")})
    projections = PipelineProjectionRepository(factory)
    cutoff_hash = projections.seal(run_id, round_kind="continuity", round_number=2)
    _project(projections, cutoff_hash)
    with factory() as session:
        snapshot = session.get(CutoffPartition, (cutoff_hash, f"alias:{mention_uuid(run_id, 1, '顾霜')}"))
        assert snapshot.projection["contested"]
        assert len(snapshot.projection["assertions"]) == 2
        assert all(assertion["evidence_ids"] and assertion["outcome"] == "conflict"
                   for assertion in snapshot.projection["assertions"])
        entities = list(session.execute(select(GraphEntity).where(GraphEntity.run_id == run_id)).scalars())
        assert all(entity.attributes["canonical_entity_id"] == entity.entity_id for entity in entities)
        assert all(entity.attributes["identity_status"] == "contested"
                   for entity in entities if entity.first_seen_chapter == 1)
        selected = next(assertion["command_ids"][0] for assertion in snapshot.projection["assertions"]
                        if assertion["payload"]["identity_kind"] == "different")
    conflict_case = next(case["case_id"] for case in repository.visible_cases(cutoff_hash)
                         if case["target_ref"].get("partition_key") == f"alias:{mention_uuid(run_id, 1, '顾霜')}")
    receipt = _continuity(run_id, conflict_case, source_hash)
    claim = repository.claim(receipt, conflict_case)
    with pytest.raises(ValueError, match="固定 cutoff"):
        repository.commit(receipt, claim, state="resolved", evidence=_evidence(run_id), resolution={
            "entity_id": mention_uuid(run_id, 1, "顾霜"), "selected_command_id": "0" * 64,
        })
    repository.commit(receipt, claim, state="resolved", evidence=_evidence(run_id), resolution={
        "entity_id": mention_uuid(run_id, 1, "顾霜"), "selected_command_id": selected,
    })
    next_cutoff = projections.seal(run_id, round_kind="continuity", round_number=3)
    _project(projections, next_cutoff)
    with factory() as session:
        resolved = session.get(CutoffPartition, (next_cutoff, f"alias:{mention_uuid(run_id, 1, '顾霜')}"))
        assert not resolved.projection["contested"]
        assertions = [assertion for assertion in resolved.projection["assertions"]
                      if assertion["kind"] == "identity_binding"]
        assert {assertion["outcome"] for assertion in assertions} == {"accepted", "rejected"}
        assert session.get(CutoffPartition, (cutoff_hash, resolved.partition_key)).projection["contested"]
        for entity in session.execute(select(GraphEntity).where(GraphEntity.run_id == run_id)).scalars():
            assert entity.attributes["canonical_entity_id"] == entity.entity_id
            if entity.first_seen_chapter == 1:
                assert entity.attributes["different_entity_ids"] and entity.attributes["identity_status"] == "resolved"


def test_type_conflict_is_explicitly_arbitrated_without_rewriting_formal_commands(db_session) -> None:
    run_id, _, source_hash = _source(db_session, domain="relation")
    factory = get_session_factory()
    with factory() as session, session.begin():
        original = session.execute(select(SemanticCommand).where(
            SemanticCommand.run_id == run_id, SemanticCommand.command_kind == "entity_mention",
            SemanticCommand.origin_chapter_id == 1,
            SemanticCommand.payload["name"].as_string() == "顾霜",
        ).limit(1)).scalar_one()
        command_id = stable_digest(run_id, "formal-type-conflict")
        payload = {**original.payload, "entity_type": "organization"}
        session.add(SemanticCommand(
            command_id=command_id, run_id=run_id, command_kind="entity_mention", partition_key=original.partition_key,
            origin_annotation_id=original.origin_annotation_id, origin_chapter_id=original.origin_chapter_id,
            origin_chapter_sequence=original.origin_chapter_sequence, command_path="test/type-conflict",
            effective_document_position=original.effective_document_position, payload=payload,
            payload_hash=stable_digest(payload), evidence_ids=original.evidence_ids,
            author_work_id=original.author_work_id,
        ))
        session.flush()
    projections = PipelineProjectionRepository(factory)
    _project(projections, projections.seal(run_id, round_kind="continuity", round_number=1))
    repository = PipelineContinuityRepository(factory)
    boundary = projections.latest_released(run_id)["cutoff_hash"]
    case_id = next(case["case_id"] for case in repository.visible_cases(boundary)
                   if case["target_ref"].get("entity_id") == mention_uuid(run_id, 1, "顾霜"))
    receipt = _continuity(run_id, case_id, source_hash)
    claim = repository.claim(receipt, case_id)
    with pytest.raises(ValueError, match="已提出的类型"):
        repository.commit(receipt, claim, state="resolved", evidence=_evidence(run_id), resolution={
            "entity_id": mention_uuid(run_id, 1, "顾霜"), "identity_kind": "type_conflict", "entity_type": "item",
        })
    repository.commit(receipt, claim, state="resolved", evidence=_evidence(run_id), resolution={
        "entity_id": mention_uuid(run_id, 1, "顾霜"), "identity_kind": "type_conflict", "entity_type": "character",
    })
    cutoff_hash = projections.seal(run_id, round_kind="continuity", round_number=2)
    _project(projections, cutoff_hash)
    with factory() as session:
        assert session.get(GraphEntity, mention_uuid(run_id, 1, "顾霜")).entity_type == "character"
        assert session.get(SemanticCommand, command_id).payload["entity_type"] == "organization"
        snapshot = session.get(CutoffPartition, (cutoff_hash, original.partition_key))
        assert not snapshot.projection["contested"]


def test_transitive_same_identity_cannot_hide_different_constraint() -> None:
    commands = [_command(identifier, "identity_binding", {
        "entity_id": source, "canonical_entity_id": target, "identity_kind": kind,
    }) for identifier, source, target, kind in [("ab", "a", "b", "same"), ("bc", "b", "c", "same"),
                                               ("ac", "c", "a", "different")]]
    assert identity_conflicts(commands) == ["ab", "ac", "bc"]
