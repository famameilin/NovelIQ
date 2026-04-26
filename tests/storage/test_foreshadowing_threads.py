"""
创建时间: 2026-04-26
修改者: Codex
任务: fix-phase2-setup-pool-review-findings
说明: 覆盖 setup pool 可见性边界、overflow 归档与 thread 身份校验。
"""

from __future__ import annotations

from datetime import datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import select

from src.models.local.schema import ForeshadowingResult
from src.storage.models import ForeshadowingThread
from src.storage.repositories import AnnotationRepository, RunRepository
from src.storage.repositories.annotation.foreshadowing_threads import (
    ACTIVE_SETUP_POOL_LIMIT,
    _archive_overflow_threads,
    _find_exact_matching_active_thread,
    fetch_active_foreshadowing_threads_for_prompt,
    sync_foreshadowing_thread,
)


def _create_run(db_session, insert_test_novel, novel_id: str) -> str:
    """
    创建供 foreshadowing thread 测试使用的 run。

    创建时间: 2026-04-26
    修改者: Codex
    任务: fix-phase2-setup-pool-review-findings
    新建原因: thread 仓储测试需要真实 run_id 外键，集中 helper 可以避免每个用例重复铺底。
    """

    insert_test_novel(novel_id)
    run_id = str(uuid4())
    RunRepository(db_session).create_run(novel_id=novel_id, run_id=run_id)
    return run_id


def _make_thread(*, run_id: str, setup_id: str, chunk_id: int, summary: str) -> ForeshadowingThread:
    """
    构造最小可持久化的 active thread ORM 对象。

    创建时间: 2026-04-26
    修改者: Codex
    任务: fix-phase2-setup-pool-review-findings
    新建原因: overflow / visible-pool 测试只关心 thread 主表，不需要每次手写整段 ORM 初始化。
    """

    base_time = datetime(2026, 4, 26, 12, 0, 0) + timedelta(minutes=chunk_id)
    return ForeshadowingThread(
        setup_id=setup_id,
        run_id=run_id,
        first_chunk_id=chunk_id,
        last_chunk_id=chunk_id,
        setup_summary=summary,
        setup_kind="异常物件",
        expected_payoff_family="能力触发",
        payoff_likelihood="high",
        strength="medium",
        status="open",
        active=True,
        created_at=base_time,
        updated_at=base_time,
    )


def _valid_new_setup_result(*, summary: str) -> ForeshadowingResult:
    """
    构造仓储层 exact-match 测试用的合法新 setup 结果。

    创建时间: 2026-04-26
    修改者: Codex
    任务: fix-phase2-setup-pool-review-findings
    新建原因: _find_exact_matching_active_thread 只依赖稳定字段，使用集中 helper 更容易看清测试意图。
    """

    return ForeshadowingResult(
        has_foreshadowing=True,
        is_strong_setup=True,
        foreshadowing_type="物件",
        setup_kind="异常物件",
        anchor_text="那枚玉佩在夜里自行发热。",
        anchor_reason="具体钩子：玉佩在夜里自行发热。未闭合原因：当前还没有解释它为何会发热。",
        setup_summary=summary,
        why_unresolved_now="当前还没有解释它为何会发热。",
        expected_payoff_family="能力触发",
        payoff_likelihood="high",
        is_new_setup=True,
        linked_setup_id=None,
        setup_status="open",
        confidence="high",
    )


def test_archive_overflow_threads_flushes_pending_insert_before_limit_check(db_session, insert_test_novel) -> None:
    run_id = _create_run(db_session, insert_test_novel, "fst001")

    existing_threads = [
        _make_thread(
            run_id=run_id,
            setup_id=f"setup-{index:02d}",
            chunk_id=index,
            summary=f"已有 setup {index}",
        )
        for index in range(1, ACTIVE_SETUP_POOL_LIMIT + 1)
    ]
    db_session.add_all(existing_threads)
    db_session.commit()

    pending_thread = _make_thread(
        run_id=run_id,
        setup_id="setup-new",
        chunk_id=ACTIVE_SETUP_POOL_LIMIT + 1,
        summary="新的 setup",
    )
    db_session.add(pending_thread)

    _archive_overflow_threads(db_session, run_id=run_id)

    active_threads = db_session.execute(
        select(ForeshadowingThread)
        .where(ForeshadowingThread.run_id == run_id, ForeshadowingThread.active.is_(True))
        .order_by(ForeshadowingThread.last_chunk_id.desc())
    ).scalars().all()

    oldest_thread = db_session.get(ForeshadowingThread, "setup-01")
    newest_thread = db_session.get(ForeshadowingThread, "setup-new")

    assert len(active_threads) == ACTIVE_SETUP_POOL_LIMIT
    assert oldest_thread is not None and oldest_thread.active is False
    assert oldest_thread.status == "open"
    assert newest_thread is not None and newest_thread.active is True


def test_archive_overflow_threads_preserves_semantic_status_when_evicted(db_session, insert_test_novel) -> None:
    """
    创建时间: 2026-04-26
    创建者: Codex
    任务: fix-diagnosis-followup-review-findings
    说明: active pool eviction 只应改变可见性，不应覆盖 thread 语义状态；
    否则 diagnosis 的 foreshadow_expectation 会把 `likely_paid_off` / `reinforced` 误降级。
    """

    run_id = _create_run(db_session, insert_test_novel, "fst004")

    evicted_thread = _make_thread(
        run_id=run_id,
        setup_id="evicted-paid-off",
        chunk_id=1,
        summary="旧 setup",
    )
    evicted_thread.status = "likely_paid_off"
    db_session.add(evicted_thread)
    db_session.add_all(
        [
                _make_thread(
                    run_id=run_id,
                    setup_id=f"overflow-{index:02d}",
                    chunk_id=index,
                    summary=f"已有 setup {index}",
                )
            for index in range(2, ACTIVE_SETUP_POOL_LIMIT + 2)
        ]
    )
    db_session.commit()

    _archive_overflow_threads(db_session, run_id=run_id)

    refreshed = db_session.get(ForeshadowingThread, "evicted-paid-off")
    assert refreshed is not None
    assert refreshed.active is False
    assert refreshed.status == "likely_paid_off"


def test_find_exact_matching_active_thread_ignores_invisible_active_threads_outside_pool_limit(
    db_session,
    insert_test_novel,
) -> None:
    run_id = _create_run(db_session, insert_test_novel, "fst002")

    threads = [
        _make_thread(
            run_id=run_id,
            setup_id="setup-oldest",
            chunk_id=1,
            summary="玉佩出现异常红光，后续可能揭示其能力或来历",
        )
    ]
    threads.extend(
        _make_thread(
            run_id=run_id,
            setup_id=f"setup-visible-{index:02d}",
            chunk_id=index,
            summary=f"其他 setup {index}",
        )
        for index in range(2, ACTIVE_SETUP_POOL_LIMIT + 2)
    )
    db_session.add_all(threads)
    db_session.commit()

    visible_pool = fetch_active_foreshadowing_threads_for_prompt(
        db_session,
        run_id=run_id,
        max_chunk_id=ACTIVE_SETUP_POOL_LIMIT + 1,
    )
    matched_thread = _find_exact_matching_active_thread(
        db_session,
        run_id=run_id,
        chunk_id=ACTIVE_SETUP_POOL_LIMIT + 2,
        result=_valid_new_setup_result(summary="玉佩出现异常红光，后续可能揭示其能力或来历"),
    )

    assert len(visible_pool) == ACTIVE_SETUP_POOL_LIMIT
    assert all(entry.setup_id != "setup-oldest" for entry in visible_pool)
    assert matched_thread is None


def test_sync_foreshadowing_thread_rejects_linked_setup_payload_mismatch(db_session, insert_test_novel) -> None:
    run_id = _create_run(db_session, insert_test_novel, "fst003")

    db_session.add(
        _make_thread(
            run_id=run_id,
            setup_id="setup-1",
            chunk_id=5,
            summary="铜铃在雨夜自行作响，后续可能暴露禁制规则",
        )
    )
    db_session.commit()

    result = ForeshadowingResult(
        has_foreshadowing=True,
        is_strong_setup=True,
        foreshadowing_type="物件",
        setup_kind="异常物件",
        anchor_text="那枚玉佩在夜里自行发热。",
        anchor_reason="具体钩子：玉佩在夜里自行发热。未闭合原因：当前还没有解释它为何会发热。",
        setup_summary="玉佩出现异常红光，后续可能揭示其能力或来历",
        why_unresolved_now="当前还没有解释它为何会发热。",
        expected_payoff_family="能力触发",
        payoff_likelihood="high",
        is_new_setup=False,
        linked_setup_id="setup-1",
        setup_status="reinforced",
        confidence="high",
    )

    with pytest.raises(ValueError, match="does not match setup thread identity"):
        sync_foreshadowing_thread(
            db_session,
            run_id=run_id,
            chunk_id=6,
            result=result,
        )


def test_annotation_repository_delegates_prompt_pool_limit_as_runtime_none(db_session) -> None:
    """
    创建时间: 2026-04-26
    创建者: Codex
    任务: fix-diagnosis-followup-findings
    说明: AnnotationRepository wrapper 不应再把 active setup pool limit 固化为模块常量；
    未显式传 limit 时，必须把 None 透传给底层 helper，由其运行时读取 settings。
    """

    captured: dict[str, object] = {}

    def _fake_fetch(session, run_id: str, *, max_chunk_id: int, limit: int | None = None):
        captured["session"] = session
        captured["run_id"] = run_id
        captured["max_chunk_id"] = max_chunk_id
        captured["limit"] = limit
        return []

    repository = AnnotationRepository(db_session)
    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr(
        "src.storage.repositories.annotation.foreshadowing_threads.fetch_active_foreshadowing_threads_for_prompt",
        _fake_fetch,
    )
    try:
        result = repository.fetch_active_foreshadowing_threads_for_prompt("run-1", max_chunk_id=9)
    finally:
        monkeypatch.undo()

    assert result == []
    assert captured == {
        "session": db_session,
        "run_id": "run-1",
        "max_chunk_id": 9,
        "limit": None,
    }
