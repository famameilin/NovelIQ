"""两个独立 Python 进程竞争真实 PostgreSQL 的全局工作与物理请求槽位"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import timedelta

import pytest
from sqlalchemy import select

from src.storage.db import get_session_factory
from src.storage.models import AgentWorkItem
from src.storage.repositories.provider_permits import ProviderLimits, ProviderPermitRepository
from tests.storage.test_pipeline_work import _queue

pytestmark = pytest.mark.usefixtures("pipeline_run_cleanup")

_CHILD = """
import json, os, sys
from loguru import logger
logger.remove()
from src.storage.db import get_session_factory
from src.storage.repositories.pipeline_work import PipelineWorkRepository
from src.storage.repositories.provider_permits import ProviderPermitRepository
factory = get_session_factory()
queue = PipelineWorkRepository(factory)
owner = f'process-{os.getpid()}'
claimed = []
for attempt in range(3):
    receipt = queue.claim(owner=owner, run_id=sys.argv[1])
    if receipt is not None:
        claimed.append(receipt.work_id)
permit = ProviderPermitRepository(factory).acquire(provider_key=sys.argv[2], owner=owner, reserved_tokens=10)
print(json.dumps({'work_ids': claimed, 'permit': permit.permit_id if permit else None}))
"""


def test_process_exit_does_not_bypass_global_limits_and_expired_work_is_reclaimed() -> None:
    run_id, queue = _queue()
    for chapter_id in range(6):
        queue.enqueue(run_id=run_id, work_kind="formal_current", logical_key=f"chapter:{chapter_id}",
                      cutoff_hash="source", payload={"chapter_id": chapter_id})
    permits = ProviderPermitRepository(get_session_factory())
    key = permits.configure(ProviderLimits("https://multiprocess.example/v1", run_id, "chat_completions", 1))
    environment = {**os.environ, "PYTHONUTF8": "1", "MODEL_POOL": json.dumps([
        {"model_id": "test-model", "base_url": "https://test.example/v1", "api_key": "test-key",
         "weight": 1, "max_in_flight": 2},
    ]), "DIAGNOSIS_MODEL_ID": "test-model"}
    children = [subprocess.Popen([sys.executable, "-c", _CHILD, run_id, key], env=environment,
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding="utf-8")
                for _ in range(2)]
    try:
        reports = []
        for child in children:
            output, errors = child.communicate(timeout=12)
            assert child.returncode == 0, errors
            reports.append(json.loads(output))
    finally:
        for child in children:
            if child.poll() is None:
                child.kill()
                child.communicate(timeout=3)
    work_ids = [work_id for report in reports for work_id in report["work_ids"]]
    assert len(work_ids) == len(set(work_ids)) == 6
    assert sum(report["permit"] is not None for report in reports) == 1
    assert queue.claim(owner="parent", run_id=run_id) is None
    assert permits.acquire(provider_key=key, owner="parent", reserved_tokens=10) is None
    with get_session_factory()() as session, session.begin():
        work = session.get(AgentWorkItem, work_ids[0])
        work.lease_expires_at -= timedelta(hours=1)
    recovered = queue.claim(owner="replacement", run_id=run_id)
    assert recovered is not None and recovered.work_id == work_ids[0] and recovered.attempt_epoch == 2
    with get_session_factory()() as session:
        active = list(session.execute(select(AgentWorkItem).where(
            AgentWorkItem.run_id == run_id, AgentWorkItem.state == "running",
        )).scalars())
        assert len(active) == 6
