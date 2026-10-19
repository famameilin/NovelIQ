"原子领取待执行任务"

from __future__ import annotations

from collections.abc import Callable

from src.storage import Storage
from src.storage.id_mapping import task_id_to_run_id


class TaskClaimMixin:
    "仅 pending 状态可领取"

    session_factory: Callable[[], Storage]

    def _prepare_task_execution_claim(self, task_id: str) -> str:
        session = self.session_factory()
        run_id = task_id_to_run_id(task_id, session)
        return "claimed" if session.runs.claim_pending_run(run_id) else "skipped"
