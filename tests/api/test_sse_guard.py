"""SSE task ownership checks against persisted analysis runs."""

from __future__ import annotations

from src.api.routes.sse import _task_run_belongs_to_novel
from src.storage import new_id
from src.storage.db import get_session_factory
from src.storage.repositories import RunRepository
from tests.support.analysis_factories import insert_test_novel
from tests.support.storage_fixtures import fixture_id, task_for_run


def test_sse_guard_accepts_persisted_task_only_for_its_novel() -> None:
    novel_id = new_id()
    insert_test_novel(novel_id)
    with get_session_factory()() as session:
        run_id = RunRepository(session).create_run(novel_id=novel_id)
        session.commit()
        task_id = task_for_run(run_id, session)

    assert _task_run_belongs_to_novel(task_id, novel_id)
    assert not _task_run_belongs_to_novel(task_id, fixture_id(__name__, "other"))
    assert not _task_run_belongs_to_novel("deadbeef", novel_id)
