"""RunRepository.claim_pending_run 的 started_at 语义

契约：首次 claim 盖 started_at；已有值一律保留（coalesce）。
"""

from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy import select

from src.storage.models import AnalysisRun
from src.storage.repositories import RunRepository
from tests.support.analysis_factories import insert_test_novel as _insert_test_novel
from tests.support.storage_fixtures import fixture_id

_FIRST_START = datetime(2026, 10, 2, 15, 8, 38)
_LATER = _FIRST_START + timedelta(hours=16, minutes=45)


def _insert_pending_run(db_session, run_id: str, *, started_at: datetime | None) -> None:
    novel_id = fixture_id(__name__, run_id, "novel")
    _insert_test_novel(novel_id, session=db_session)
    db_session.add(AnalysisRun(run_id=run_id, novel_id=novel_id, status="pending", started_at=started_at))
    db_session.commit()


def _started_at(db_session, run_id: str) -> datetime | None:
    return db_session.execute(select(AnalysisRun).where(AnalysisRun.run_id == run_id)).scalar_one().started_at


def test_first_claim_stamps_started_at(db_session) -> None:
    _insert_pending_run(db_session, fixture_id(__name__, "claim-run-fresh"), started_at=None)
    repo = RunRepository(db_session)

    assert (
        repo.claim_pending_run(fixture_id(__name__, "claim-run-fresh"), worker_id="w1", heartbeat_at=_FIRST_START)
        is True
    )
    assert _started_at(db_session, fixture_id(__name__, "claim-run-fresh")) == _FIRST_START


def test_reclaim_preserves_first_started_at(db_session) -> None:
    """诊断重试把 run 打回 pending 再重领：started_at 保留首次值，不被重置成重领时刻"""
    _insert_pending_run(db_session, fixture_id(__name__, "claim-run-retry"), started_at=_FIRST_START)
    repo = RunRepository(db_session)

    # 首次执行后出错 → 打回 pending（update_run_task_fields 不触碰 started_at）→ 重领
    repo.update_run_task_fields(fixture_id(__name__, "claim-run-retry"), status="pending", completed_at=None)
    assert repo.claim_pending_run(fixture_id(__name__, "claim-run-retry"), worker_id="w2", heartbeat_at=_LATER) is True

    assert _started_at(db_session, fixture_id(__name__, "claim-run-retry")) == _FIRST_START
