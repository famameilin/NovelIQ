"""真实 PostgreSQL 乐观竞争与事务回滚，不以分区锁替代 CAS"""

from concurrent.futures import ThreadPoolExecutor
from threading import Barrier, Lock

import pytest
from sqlalchemy import select

from src.storage.db import get_session_factory
from src.storage.models import AnalysisCutoff, CutoffPartition, EventOutbox, PartitionHead
from src.storage.repositories.pipeline_continuity import PipelineContinuityRepository
from src.storage.repositories.pipeline_projection import PipelineProjectionRepository, ProjectionCASConflict
from tests.storage.test_pipeline_continuity_projection import _continuity, _project, _source

pytestmark = pytest.mark.usefixtures("pipeline_run_cleanup")


def test_two_projectors_retry_cas_without_overwriting_winner(db_session, monkeypatch) -> None:
    run_id, case_id, source_hash = _source(db_session)
    factory = get_session_factory()
    continuity = PipelineContinuityRepository(factory)
    receipt = _continuity(run_id, case_id, source_hash)
    continuity.commit(receipt, continuity.claim(receipt, case_id))
    projections = PipelineProjectionRepository(factory)
    cutoff_hash = projections.seal(run_id, round_kind="continuity", round_number=1)
    target = f"case:{case_id}"
    original_cas = PipelineProjectionRepository._compare_and_swap_head
    barrier = Barrier(2)
    guard = Lock()
    read_epochs: list[int] = []

    def compete(session, head, **values):
        synchronize = False
        if head.partition_key == target:
            with guard:
                synchronize = len(read_epochs) < 2
                if synchronize:
                    read_epochs.append(head.head_epoch)
            if synchronize:
                barrier.wait(timeout=5)
        return original_cas(session, head, **values)

    monkeypatch.setattr(PipelineProjectionRepository, "_compare_and_swap_head", staticmethod(compete))
    monkeypatch.setattr("src.storage.repositories.pipeline_projection.choice",
                        lambda values: target if target in values else values[0])
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: PipelineProjectionRepository(factory).project_next(cutoff_hash), range(2)))
    assert read_epochs == [0, 0] and all(results)
    _project(projections, cutoff_hash)
    with factory() as session:
        head = session.get(PartitionHead, (run_id, target))
        snapshot = session.get(CutoffPartition, (cutoff_hash, target))
        assert head.head_epoch == 1 and head.projection_hash == snapshot.projection_hash
        retries = list(session.execute(select(EventOutbox).where(
            EventOutbox.cutoff_hash == cutoff_hash, EventOutbox.event_type == "projection_cas_conflict",
        )).scalars())
        assert len(retries) == 1 and retries[0].payload["partition_key"] == target
        assert session.get(AnalysisCutoff, cutoff_hash).state == "released"
        state, counts = projections.projection_progress(cutoff_hash)
        assert state == "released" and counts["waiting"] == 0


def test_failed_cas_leaves_no_partial_snapshot_ack_or_head(db_session, monkeypatch) -> None:
    run_id, case_id, source_hash = _source(db_session)
    factory = get_session_factory()
    repository = PipelineContinuityRepository(factory)
    receipt = _continuity(run_id, case_id, source_hash)
    repository.commit(receipt, repository.claim(receipt, case_id))
    projections = PipelineProjectionRepository(factory)
    cutoff_hash = projections.seal(run_id, round_kind="continuity", round_number=1)
    target = f"case:{case_id}"

    def fail(_session, head, **_values):
        raise ProjectionCASConflict(head.partition_key)

    monkeypatch.setattr(PipelineProjectionRepository, "_compare_and_swap_head", staticmethod(fail))
    monkeypatch.setattr("src.storage.repositories.pipeline_projection.choice", lambda _values: target)
    assert not projections.project_next(cutoff_hash)
    with factory() as session:
        assert session.get(PartitionHead, (run_id, target)).head_epoch == 0
        assert session.get(CutoffPartition, (cutoff_hash, target)) is None
        assert session.get(AnalysisCutoff, cutoff_hash).state == "projecting"
        state, counts = projections.projection_progress(cutoff_hash)
        assert state == "projecting" and counts["waiting"] >= 1
