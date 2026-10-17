"""阶段 emitter 提交语义测试：发事件前必须先提交编排器 session

创建时间: 2026-10-03
创建者: Trae
任务: 验证 2026-10-03 死锁修复（run 08f9ba42）
说明: 编排器 session 事务跨阶段存活时，阶段内写入对 analysis_runs 行持有的锁
（外键 FOR KEY SHARE / 显式 FOR SHARE）会与 emit 路径 to_thread 的 UPDATE
行锁互斥，编排器 await 自己堵住的 UPDATE 即永久死锁。emitter 先 commit 再 emit。
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest

from src.sse.events import StreamEvent
from src.storage.db import get_session, get_session_factory
from src.storage.models import AnalysisRun, Novel
from src.work.task_manager import TaskManager
from src.workflows.analysis.stage_orchestrator import StageOrchestratorMixin
from src.workflows.progress import AnalysisEventBus

pytestmark = pytest.mark.asyncio


async def test_stage_emitter_rolls_back_and_reraises_when_commit_fails(monkeypatch) -> None:
    """提交失败必须回滚救回会话再原样上抛：不允许中间态毒化会话流入下游

    2026-10-17 run 52cbb1ac 实证：管线会话一次提交中途被打断留在 PREPARED 后，
    任意后续 SQL 都抛 "session is in 'prepared' state"；诊断工具读取被伪装成
    "依赖故障"，真实原因与失败点全部丢失。emitter 是管线会话的提交闸门，
    失败时先 rollback（PREPARED 态允许回滚）再上抛，失败当场可归因。
    """
    factory = get_session_factory()
    session = factory()
    rollbacks: list[bool] = []
    real_rollback = session.rollback

    def interrupted_commit() -> None:
        raise RuntimeError("commit interrupted")

    def counting_rollback() -> None:
        rollbacks.append(True)
        real_rollback()

    monkeypatch.setattr(session, "commit", interrupted_commit)
    monkeypatch.setattr(session, "rollback", counting_rollback)

    class _Bus:
        async def emit(self, event: StreamEvent) -> None:
            raise AssertionError("提交失败时不得继续发事件")

    emitter = StageOrchestratorMixin._make_stage_emitter(_Bus(), "diagnose", session)
    with pytest.raises(RuntimeError, match="commit interrupted"):
        await emitter(StreamEvent(action="progress"))
    assert rollbacks == [True]
    session.close()


async def test_stage_emitter_commits_session_before_emit() -> None:
    """emitter 发事件前提交 session：编排器事务持有的 analysis_runs 行锁不再阻塞 emit 写回

    无此提交语义时，本测试的 FOR SHARE 会让 emit 内 to_thread(UPDATE analysis_runs)
    永久等待，asyncio.wait_for 超时即失败。
    """
    task_id = str(uuid4())  # 36 字符：update_task 直接按 run_id 解析（len!=8 走直通用法）
    novel_id = uuid4().hex[:8]
    factory = get_session_factory()
    with get_session() as session:
        session.add(Novel(novel_id=novel_id, title="emitter 提交语义测试"))
        session.flush()
        session.add(AnalysisRun(run_id=task_id, novel_id=novel_id, status="running", stage="aggregate"))
    try:
        task_manager = TaskManager()
        task_manager.set_db_session_factory(factory)
        task_manager.create_task(task_id, novel_id)
        bus = AnalysisEventBus(task_id, task_manager)

        # 模拟阶段内已发生的写与行锁：编排器 session 持 analysis_runs 行 FOR SHARE 未提交
        orchestrator_session = factory()
        locked = orchestrator_session.get(AnalysisRun, task_id, with_for_update={"read": True})
        assert locked is not None
        assert orchestrator_session.in_transaction()

        emitter = StageOrchestratorMixin._make_stage_emitter(bus, "aggregate", orchestrator_session)
        event = StreamEvent(action="complete", stage="aggregate", current=1, total=1, percent=90.0)

        with patch("src.sse.manager.event_manager") as mock_em:
            mock_em.send = AsyncMock()
            await asyncio.wait_for(emitter(event), timeout=15.0)

        # 提交语义生效：编排器事务已结束，阶段写入对其它连接可见
        assert not orchestrator_session.in_transaction()
        orchestrator_session.close()
        with get_session() as verify:
            row = verify.get(AnalysisRun, task_id)
            assert row is not None
            assert row.stage == "aggregate"
            assert row.progress == 90.0
    finally:
        with get_session() as cleanup:
            run = cleanup.get(AnalysisRun, task_id)
            if run is not None:
                cleanup.delete(run)
            novel = cleanup.get(Novel, novel_id)
            if novel is not None:
                cleanup.delete(novel)
