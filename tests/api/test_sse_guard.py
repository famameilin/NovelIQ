"""SSE task ownership checks against persisted analysis runs."""

from __future__ import annotations

import uuid

from src.api.routes.sse import _task_run_belongs_to_novel
from src.storage.db import get_session_factory
from src.storage.repositories import RunRepository
from tests.support.analysis_factories import insert_test_novel


def test_sse_guard_accepts_persisted_task_only_for_its_novel() -> None:
    novel_id = uuid.uuid4().hex[:8]
    insert_test_novel(novel_id)
    with get_session_factory()() as session:
        task_id = RunRepository(session).create_run(novel_id=novel_id)[:8]

    assert _task_run_belongs_to_novel(task_id, novel_id)
    assert not _task_run_belongs_to_novel(task_id, "other")
    assert not _task_run_belongs_to_novel("deadbeef", novel_id)
