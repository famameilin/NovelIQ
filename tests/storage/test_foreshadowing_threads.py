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
from src.storage.models import Chunk, ForeshadowingThread, ForeshadowingThreadHit
from src.storage.repositories import AnnotationRepository, RunRepository
from src.storage.repositories.annotation.foreshadowing_threads import (
    ACTIVE_SETUP_POOL_LIMIT,
    _archive_overflow_threads,
    _find_exact_matching_active_thread,
    calculate_foreshadow_expectation,
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


def _make_thread(
    *,
    run_id: str,
    setup_id: str,
    chunk_id: int,
    summary: str,
    payoff_likelihood: str = "high",
    confidence: str = "high",
    strength: str = "medium",
    status: str = "open",
) -> ForeshadowingThread:
    """
    构造最小可持久化的 active thread ORM 对象。

    创建时间: 2026-04-26
    修改者: Codex
    任务: fix-phase2-setup-pool-review-findings
    新建原因: overflow / visible-pool 测试只关心 thread 主表，不需要每次手写整段 ORM 初始化。

    修改时间: 2026-04-29
    任务: foreshadow-expectation-v2
    修改原因: expectation v2 测试需要构造不同 payoff/status/strength 组合，helper 改为可参数化。
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
        payoff_likelihood=payoff_likelihood,
        confidence=confidence,
        strength=strength,
        status=status,
        active=True,
        created_at=base_time,
        updated_at=base_time,
    )


def _add_thread_hits(db_session, *, run_id: str, setup_id: str, chunk_ids: list[int]) -> None:
    """
    2026-04-29，任务：伏笔回收预期 v2 口径修复
    新建原因：expectation v2 按 hit_count 聚合，测试需要通过真实 chunk + hit 行覆盖 SQL 统计路径。
    """

    base_time = datetime(2026, 4, 29, 12, 0, 0)
    for chunk_id in chunk_ids:
        db_session.add(
            Chunk(
                chunk_id=chunk_id,
                run_id=run_id,
                text=f"测试 chunk {chunk_id}",
            )
        )
        db_session.add(
            ForeshadowingThreadHit(
                setup_id=setup_id,
                run_id=run_id,
                chunk_id=chunk_id,
                anchor_text=f"测试锚点 {chunk_id}",
                anchor_reason="具体钩子：测试锚点。未闭合原因：当前还没有解释测试锚点。",
                why_unresolved_now="当前还没有解释测试锚点。",
                is_new_setup=chunk_id == chunk_ids[0],
                created_at=base_time + timedelta(minutes=chunk_id),
            )
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


def test_calculate_foreshadow_expectation_returns_none_without_threads(db_session, insert_test_novel) -> None:
    """
    创建时间: 2026-04-29
    任务: foreshadow-expectation-v2
    新建原因: setup ledger 为空时，正式预期仍应返回 None，不能伪造 0 或旧 fallback。
    """

    run_id = _create_run(db_session, insert_test_novel, "fst005")

    assert calculate_foreshadow_expectation(db_session, run_id) is None


def test_calculate_foreshadow_expectation_distinguishes_open_and_reinforced_high_threads(
    db_session,
    insert_test_novel,
) -> None:
    """
    创建时间: 2026-04-29
    任务: foreshadow-expectation-v2
    新建原因: v2 公式必须让 open/high/hit1 与 reinforced/high/hit2 拉开分数，不再同为 0.7。
    """

    open_run_id = _create_run(db_session, insert_test_novel, "fst006")
    reinforced_run_id = _create_run(db_session, insert_test_novel, "fst007")
    db_session.add(
        _make_thread(
            run_id=open_run_id,
            setup_id="open-high-hit1",
            chunk_id=1,
            summary="open high setup",
            strength="high",
            status="open",
        )
    )
    _add_thread_hits(db_session, run_id=open_run_id, setup_id="open-high-hit1", chunk_ids=[1])
    db_session.add(
        _make_thread(
            run_id=reinforced_run_id,
            setup_id="reinforced-high-hit2",
            chunk_id=2,
            summary="reinforced high setup",
            strength="high",
            status="reinforced",
        )
    )
    _add_thread_hits(db_session, run_id=reinforced_run_id, setup_id="reinforced-high-hit2", chunk_ids=[1, 2])
    db_session.commit()

    open_score = calculate_foreshadow_expectation(db_session, open_run_id)
    reinforced_score = calculate_foreshadow_expectation(db_session, reinforced_run_id)

    assert open_score == 0.58
    assert reinforced_score == 0.72
    assert open_score < reinforced_score


def test_calculate_foreshadow_expectation_distinguishes_high_and_medium_confidence_open_threads(
    db_session,
    insert_test_novel,
) -> None:
    """
    创建时间: 2026-04-29
    任务: fix-phase2-medium-confidence-thread-semantics
    新建原因: medium confidence 入池后仍需在 ledger 预期里保留“尚不够稳”的差异，
              不能和同 payoff/status/hit_count 的 high thread 完全同分。
    """

    high_run_id = _create_run(db_session, insert_test_novel, "fst014")
    medium_run_id = _create_run(db_session, insert_test_novel, "fst015")
    db_session.add(
        _make_thread(
            run_id=high_run_id,
            setup_id="open-high-confidence",
            chunk_id=1,
            summary="high confidence setup",
            confidence="high",
            strength="high",
            status="open",
        )
    )
    _add_thread_hits(db_session, run_id=high_run_id, setup_id="open-high-confidence", chunk_ids=[1])
    db_session.add(
        _make_thread(
            run_id=medium_run_id,
            setup_id="open-medium-confidence",
            chunk_id=1,
            summary="medium confidence setup",
            confidence="medium",
            strength="medium",
            status="open",
        )
    )
    _add_thread_hits(db_session, run_id=medium_run_id, setup_id="open-medium-confidence", chunk_ids=[1])
    db_session.commit()

    high_score = calculate_foreshadow_expectation(db_session, high_run_id)
    medium_score = calculate_foreshadow_expectation(db_session, medium_run_id)

    assert high_score == 0.58
    assert medium_score == 0.55
    assert medium_score < high_score


def test_calculate_foreshadow_expectation_medium_thread_lowers_distribution(
    db_session,
    insert_test_novel,
) -> None:
    """
    创建时间: 2026-04-29
    任务: foreshadow-expectation-v2
    新建原因: medium payoff 需要真实进入聚合并拉低分布，避免 ledger 继续稳定贴住 0.7。
    """

    high_run_id = _create_run(db_session, insert_test_novel, "fst008")
    mixed_run_id = _create_run(db_session, insert_test_novel, "fst009")
    db_session.add(
        _make_thread(
            run_id=high_run_id,
            setup_id="high-only",
            chunk_id=1,
            summary="high only setup",
            strength="high",
        )
    )
    _add_thread_hits(db_session, run_id=high_run_id, setup_id="high-only", chunk_ids=[1])
    db_session.add_all(
        [
            _make_thread(
                run_id=mixed_run_id,
                setup_id="mixed-high",
                chunk_id=1,
                summary="mixed high setup",
                strength="high",
            ),
            _make_thread(
                run_id=mixed_run_id,
                setup_id="mixed-medium",
                chunk_id=2,
                summary="mixed medium setup",
                payoff_likelihood="medium",
                strength="medium",
            ),
        ]
    )
    _add_thread_hits(db_session, run_id=mixed_run_id, setup_id="mixed-high", chunk_ids=[1])
    _add_thread_hits(db_session, run_id=mixed_run_id, setup_id="mixed-medium", chunk_ids=[2])
    db_session.commit()

    high_only_score = calculate_foreshadow_expectation(db_session, high_run_id)
    mixed_score = calculate_foreshadow_expectation(db_session, mixed_run_id)

    assert high_only_score == 0.58
    assert mixed_score is not None
    assert mixed_score < high_only_score
    assert mixed_score != 0.7


def test_calculate_foreshadow_expectation_paid_off_scores_above_reinforced(
    db_session,
    insert_test_novel,
) -> None:
    """
    创建时间: 2026-04-29
    任务: foreshadow-expectation-v2
    新建原因: likely_paid_off 应作为生命周期推进进入最终指标，分数必须高于普通 reinforced。
    """

    reinforced_run_id = _create_run(db_session, insert_test_novel, "fst010")
    paid_off_run_id = _create_run(db_session, insert_test_novel, "fst011")
    db_session.add(
        _make_thread(
            run_id=reinforced_run_id,
            setup_id="reinforced-score",
            chunk_id=1,
            summary="reinforced score setup",
            strength="high",
            status="reinforced",
        )
    )
    _add_thread_hits(db_session, run_id=reinforced_run_id, setup_id="reinforced-score", chunk_ids=[1, 2])
    db_session.add(
        _make_thread(
            run_id=paid_off_run_id,
            setup_id="paid-off-score",
            chunk_id=1,
            summary="paid off score setup",
            strength="high",
            status="likely_paid_off",
        )
    )
    _add_thread_hits(db_session, run_id=paid_off_run_id, setup_id="paid-off-score", chunk_ids=[1, 2])
    db_session.commit()

    reinforced_score = calculate_foreshadow_expectation(db_session, reinforced_run_id)
    paid_off_score = calculate_foreshadow_expectation(db_session, paid_off_run_id)

    assert reinforced_score == 0.72
    assert paid_off_score == 0.97
    assert reinforced_score < paid_off_score


def test_calculate_foreshadow_expectation_hit_count_changes_score(db_session, insert_test_novel) -> None:
    """
    创建时间: 2026-04-29
    任务: foreshadow-expectation-v2
    新建原因: hit_count 是持续强化证据，同一 status/payoff/strength 下也应改变单条 thread 分数。
    """

    hit1_run_id = _create_run(db_session, insert_test_novel, "fst012")
    hit3_run_id = _create_run(db_session, insert_test_novel, "fst013")
    db_session.add(
        _make_thread(
            run_id=hit1_run_id,
            setup_id="open-hit1",
            chunk_id=1,
            summary="open hit1 setup",
            strength="high",
        )
    )
    _add_thread_hits(db_session, run_id=hit1_run_id, setup_id="open-hit1", chunk_ids=[1])
    db_session.add(
        _make_thread(
            run_id=hit3_run_id,
            setup_id="open-hit3",
            chunk_id=1,
            summary="open hit3 setup",
            strength="high",
        )
    )
    _add_thread_hits(db_session, run_id=hit3_run_id, setup_id="open-hit3", chunk_ids=[1, 2, 3])
    db_session.commit()

    hit1_score = calculate_foreshadow_expectation(db_session, hit1_run_id)
    hit3_score = calculate_foreshadow_expectation(db_session, hit3_run_id)

    assert hit1_score == 0.58
    assert hit3_score == 0.66
    assert hit1_score < hit3_score


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


def test_sync_foreshadowing_thread_persists_medium_confidence_and_keeps_new_thread_weaker(
    db_session,
    insert_test_novel,
) -> None:
    """
    创建时间: 2026-04-29
    任务: fix-phase2-medium-confidence-thread-semantics
    新建原因: medium positive 现在允许入池，但第一次入 ledger 时必须显式保留 medium
              并避免与 high payoff 新 thread 直接同强度。
    """

    run_id = _create_run(db_session, insert_test_novel, "fst016")
    db_session.add(
        Chunk(
            chunk_id=1,
            run_id=run_id,
            text="那枚玉佩在夜里自行发热。",
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
        setup_summary="玉佩在夜里自行发热",
        why_unresolved_now="当前还没有解释它为何会发热。",
        expected_payoff_family="能力触发",
        payoff_likelihood="high",
        is_new_setup=True,
        linked_setup_id=None,
        setup_status="open",
        confidence="medium",
    )

    projection = sync_foreshadowing_thread(
        db_session,
        run_id=run_id,
        chunk_id=1,
        result=result,
    )

    stored = db_session.get(ForeshadowingThread, projection.setup_id)
    assert stored is not None
    assert stored.confidence == "medium"
    assert stored.strength == "medium"


def test_fetch_active_foreshadowing_threads_for_prompt_exposes_confidence(db_session, insert_test_novel) -> None:
    """
    创建时间: 2026-04-29
    任务: fix-phase2-medium-confidence-thread-semantics
    新建原因: Active_Setup_Pool 需要显式带出 thread confidence，避免后续 Phase2 把 medium
              与 high setup 当成相同强度上下文。
    """

    run_id = _create_run(db_session, insert_test_novel, "fst017")
    db_session.add(
        _make_thread(
            run_id=run_id,
            setup_id="setup-medium-confidence",
            chunk_id=3,
            summary="中等置信度 setup",
            confidence="medium",
        )
    )
    db_session.commit()

    visible_pool = fetch_active_foreshadowing_threads_for_prompt(
        db_session,
        run_id=run_id,
        max_chunk_id=3,
    )

    assert len(visible_pool) == 1
    assert visible_pool[0].setup_id == "setup-medium-confidence"
    assert visible_pool[0].confidence == "medium"


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
