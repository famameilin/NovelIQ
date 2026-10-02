"""派生案例只在下一 cutoff 可见，重复发现追加证据，失败整笔回滚"""

from __future__ import annotations

import pytest
from sqlalchemy import select

from src.agents.annotation.fact_graph import mention_uuid
from src.agents.annotation.identity import text_digest
from src.storage.db import get_session_factory
from src.storage.models import AgentWorkItem, CaseClaim, ContinuityCase, Paragraph, SemanticCommand
from src.storage.repositories.pipeline_cases import FollowUpCaseInput, follow_up_case_id
from src.storage.repositories.pipeline_continuity import PipelineContinuityRepository
from src.storage.repositories.pipeline_projection import PipelineProjectionRepository
from src.storage.repositories.pipeline_work import StaleWorkLeaseError
from tests.storage.test_pipeline_continuity_projection import _continuity, _evidence, _project, _source

pytestmark = pytest.mark.usefixtures("pipeline_run_cleanup")


def _seed(run_id: str) -> FollowUpCaseInput:
    return FollowUpCaseInput(
        type="身份疑点", description="后文还有身份线索", keys=["顾霜"],
        target_ref={"domain": "entity", "entity_id": mention_uuid(run_id, 1, "顾霜")}, evidence=_evidence(run_id),
    )


def test_follow_up_is_hidden_until_next_cutoff_and_duplicate_evidence_is_appended(db_session) -> None:
    run_id, case_id, source_hash = _source(db_session)
    factory = get_session_factory()
    repository = PipelineContinuityRepository(factory)
    projections = PipelineProjectionRepository(factory)
    boundary = projections.latest_released(run_id)["cutoff_hash"]
    seed = _seed(run_id)
    seed_id = follow_up_case_id(run_id, seed)
    receipt = _continuity(run_id, case_id, source_hash)
    claim = repository.claim(receipt, case_id)
    repository.commit(receipt, claim, follow_up_cases=[seed, seed])
    assert seed_id not in {case["case_id"] for case in repository.visible_cases(boundary)}
    with factory() as session:
        assert session.get(ContinuityCase, seed_id) is not None
        assert len(list(session.execute(select(SemanticCommand).where(
            SemanticCommand.run_id == run_id, SemanticCommand.command_kind == "case_seed",
        )).scalars())) == 1
    next_cutoff = projections.seal(run_id, round_kind="continuity", round_number=1)
    _project(projections, next_cutoff)
    first = next(case for case in repository.visible_cases(next_cutoff) if case["case_id"] == seed_id)
    initial_evidence = first["source_evidence"]
    assert first["state"] == "pending" and initial_evidence
    receipt = _continuity(run_id, case_id, source_hash, logical_key="second-round")
    claim = repository.claim(receipt, case_id)
    with factory() as session:
        paragraph = session.execute(select(Paragraph).where(
            Paragraph.run_id == run_id, Paragraph.chapter_id == 1,
        )).scalar_one()
        seed.evidence = [{"paragraph_id": paragraph.paragraph_id, "char_start": 0,
                          "char_end": len(paragraph.text), "text_hash": text_digest(paragraph.text)}]
    repository.commit(receipt, claim, follow_up_cases=[seed])
    prior = next(case for case in repository.visible_cases(next_cutoff) if case["case_id"] == seed_id)
    assert prior["source_evidence"] == initial_evidence
    second_cutoff = projections.seal(run_id, round_kind="continuity", round_number=2)
    _project(projections, second_cutoff)
    current = next(case for case in repository.visible_cases(second_cutoff) if case["case_id"] == seed_id)
    assert set(current["source_evidence"]) > set(initial_evidence)
    with factory() as session:
        assert session.get(ContinuityCase, seed_id).source_evidence == initial_evidence


def test_invalid_follow_up_rolls_back_resolution_and_claim_consumption(db_session) -> None:
    run_id, case_id, source_hash = _source(db_session)
    factory = get_session_factory()
    repository = PipelineContinuityRepository(factory)
    receipt = _continuity(run_id, case_id, source_hash)
    claim = repository.claim(receipt, case_id)
    seed = _seed(run_id)
    seed.target_ref.entity_id = "outside-cutoff"
    with pytest.raises(ValueError, match="固定 cutoff"):
        repository.commit(receipt, claim, follow_up_cases=[seed])
    with factory() as session:
        assert session.get(AgentWorkItem, receipt.work_id).state == "running"
        assert session.get(CaseClaim, (case_id, claim.claim_epoch)).status == "active"
        assert not list(session.execute(select(SemanticCommand).where(
            SemanticCommand.author_work_id == receipt.work_id,
        )).scalars())
    repository.commit(receipt, claim)


def test_stale_case_claim_cannot_create_follow_up(db_session) -> None:
    run_id, case_id, source_hash = _source(db_session)
    factory = get_session_factory()
    repository = PipelineContinuityRepository(factory)
    receipt = _continuity(run_id, case_id, source_hash)
    claim = repository.claim(receipt, case_id)
    repository.commit(receipt, claim)
    with pytest.raises(StaleWorkLeaseError):
        repository.commit(receipt, claim, follow_up_cases=[_seed(run_id)])
    with factory() as session:
        assert session.get(ContinuityCase, follow_up_case_id(run_id, _seed(run_id))) is None
