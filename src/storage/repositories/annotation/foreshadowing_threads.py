"""
创建时间: 2026-04-26
修改者: Codex
任务: phase2-setup-pool
说明: setup 池 / thread ledger 相关仓储操作。
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from uuid import uuid4

from sqlalchemy import func, select

from src.models.local.schema import (
    ForeshadowingPayoffLikelihood,
    ForeshadowingResult,
    ForeshadowingSetupStatus,
    ForeshadowingThreadStrength,
)
from src.storage.models import ForeshadowingThread, ForeshadowingThreadHit

ACTIVE_SETUP_POOL_LIMIT = 30
_VALID_PAYOFF_LIKELIHOODS = {"high", "medium", "low"}
_VALID_RUNTIME_SETUP_STATUSES = {"open", "reinforced", "likely_paid_off"}


@dataclass(frozen=True)
class ActiveSetupPoolEntry:
    """
    Phase2 prompt 用的活跃 setup 摘要。

    创建时间: 2026-04-26
    任务: phase2-setup-pool
    新建原因: prompt 只需要稳定摘要字段，不应直接暴露 ORM 对象给消息层。
    """

    setup_id: str
    setup_summary: str
    setup_kind: str
    expected_payoff_family: str
    payoff_likelihood: str
    strength: str
    status: str
    last_chunk_id: int


@dataclass(frozen=True)
class ForeshadowingThreadProjection:
    """
    thread 同步后的 chunk 视图投影。

    创建时间: 2026-04-26
    任务: phase2-setup-pool
    新建原因: chunk_annotation 需要写入“实际归属到哪个 thread”的结果，
    不能直接复用 chunk_foreshadowing 的原始 Phase2 输出。
    """

    setup_id: str
    setup_summary: str
    expected_payoff_family: str
    payoff_likelihood: ForeshadowingPayoffLikelihood
    setup_status: ForeshadowingSetupStatus


@dataclass(frozen=True)
class ForeshadowingThreadView:
    """
    结果接口使用的 thread 汇总视图。

    创建时间: 2026-04-26
    任务: phase2-setup-pool
    新建原因: API 需要稳定的序列化视图，避免把 ORM 细节泄漏到 route 层。
    """

    setup_id: str
    first_chunk_id: int
    last_chunk_id: int
    anchor_chunk_ids: list[int]
    setup_summary: str
    setup_kind: str
    expected_payoff_family: str
    payoff_likelihood: str
    strength: str
    status: str
    active: bool
    latest_reason: str
    latest_why_unresolved_now: str


def _normalize_setup_summary(value: str) -> str:
    """
    标准化 setup_summary 以做 exact-match 去重。

    创建时间: 2026-04-26
    任务: phase2-setup-pool
    新建原因: v1 明确不做模糊语义 merge，只做“同 kind + 同 payoff + 同标准化 summary”的保守并线。
    """

    return re.sub(r"[\W_]+", "", value, flags=re.UNICODE).strip().lower()


def _derive_thread_strength(
    *,
    payoff_likelihood: str,
    status: str,
    hit_count: int,
    prior_strength: str | None = None,
) -> ForeshadowingThreadStrength:
    """
    计算 thread 强度。

    创建时间: 2026-04-26
    任务: phase2-setup-pool
    新建原因: thread 强度不由模型直接输出，而是根据命中次数、当前状态和 payoff 预期在仓储层稳定推导。
    """

    if prior_strength == "high":
        return "high"
    if status == "likely_paid_off":
        return "high"
    if payoff_likelihood == "high":
        return "high"
    if hit_count >= 2:
        return "high"
    return "medium"


def _insert_thread_hit(
    session,
    *,
    setup_id: str,
    run_id: str,
    chunk_id: int,
    result: ForeshadowingResult,
    is_new_setup: bool,
) -> None:
    """
    插入一条 thread 命中记录。

    创建时间: 2026-04-26
    任务: phase2-setup-pool
    新建原因: 命中明细需要单独留存，后续 API 才能回放 anchor_chunk_ids 与 latest_reason。
    """

    session.add(
        ForeshadowingThreadHit(
            setup_id=setup_id,
            run_id=run_id,
            chunk_id=chunk_id,
            anchor_text=result.anchor_text,
            anchor_reason=result.anchor_reason,
            why_unresolved_now=result.why_unresolved_now,
            is_new_setup=is_new_setup,
            created_at=datetime.utcnow(),
        )
    )


def _count_thread_hits(session, setup_id: str) -> int:
    """
    统计某条 thread 的命中次数。

    创建时间: 2026-04-26
    任务: phase2-setup-pool
    新建原因: 强度推导依赖命中次数，不能在调用方手工拼。
    """

    stmt = select(func.count()).select_from(ForeshadowingThreadHit).where(ForeshadowingThreadHit.setup_id == setup_id)
    return int(session.execute(stmt).scalar_one())


def _find_exact_matching_active_thread(
    session,
    *,
    run_id: str,
    chunk_id: int,
    result: ForeshadowingResult,
) -> ForeshadowingThread | None:
    """
    用精确规则查找应并入的已有 active thread。

    创建时间: 2026-04-26
    任务: phase2-setup-pool
    新建原因: v1 只允许 exact-match 去重，防止 setup 池在没有明确证据时发生过度合并。
    """

    stmt = (
        select(ForeshadowingThread)
        .where(
            ForeshadowingThread.run_id == run_id,
            ForeshadowingThread.active.is_(True),
            ForeshadowingThread.last_chunk_id <= chunk_id - 1,
            ForeshadowingThread.setup_kind == result.setup_kind,
            ForeshadowingThread.expected_payoff_family == result.expected_payoff_family,
        )
        .order_by(ForeshadowingThread.last_chunk_id.desc(), ForeshadowingThread.updated_at.desc())
    )
    normalized_summary = _normalize_setup_summary(result.setup_summary)
    for thread in session.execute(stmt).scalars().all():
        if _normalize_setup_summary(thread.setup_summary) == normalized_summary:
            return thread
    return None


def _archive_overflow_threads(session, *, run_id: str, limit: int = ACTIVE_SETUP_POOL_LIMIT) -> None:
    """
    按 last_chunk_id 从近到远保留 active 池，超限部分归档。

    创建时间: 2026-04-26
    任务: phase2-setup-pool
    新建原因: 活跃池上限是固定工程口径，归档规则必须统一收口到仓储层。
    """

    stmt = (
        select(ForeshadowingThread)
        .where(ForeshadowingThread.run_id == run_id, ForeshadowingThread.active.is_(True))
        .order_by(ForeshadowingThread.last_chunk_id.desc(), ForeshadowingThread.updated_at.desc())
    )
    active_threads = session.execute(stmt).scalars().all()
    if len(active_threads) <= limit:
        return

    for thread in active_threads[limit:]:
        thread.active = False
        thread.status = "archived"
        thread.updated_at = datetime.utcnow()


def fetch_active_foreshadowing_threads_for_prompt(
    session,
    run_id: str,
    *,
    max_chunk_id: int,
    limit: int = ACTIVE_SETUP_POOL_LIMIT,
) -> list[ActiveSetupPoolEntry]:
    """
    查询当前 chunk 可见的活跃 setup 池。

    创建时间: 2026-04-26
    任务: phase2-setup-pool
    新建原因: Phase2 在调用前必须读取“截至 chunk_id-1 可见”的活跃池，不能偷看当前或后文状态。
    """

    stmt = (
        select(ForeshadowingThread)
        .where(
            ForeshadowingThread.run_id == run_id,
            ForeshadowingThread.active.is_(True),
            ForeshadowingThread.last_chunk_id <= max_chunk_id,
        )
        .order_by(ForeshadowingThread.last_chunk_id.desc(), ForeshadowingThread.updated_at.desc())
        .limit(limit)
    )
    rows = session.execute(stmt).scalars().all()
    return [
        ActiveSetupPoolEntry(
            setup_id=row.setup_id,
            setup_summary=row.setup_summary,
            setup_kind=row.setup_kind,
            expected_payoff_family=row.expected_payoff_family,
            payoff_likelihood=row.payoff_likelihood,
            strength=row.strength,
            status=row.status,
            last_chunk_id=row.last_chunk_id,
        )
        for row in rows
    ]


def sync_foreshadowing_thread(
    session,
    *,
    run_id: str,
    chunk_id: int,
    result: ForeshadowingResult,
) -> ForeshadowingThreadProjection:
    """
    将一条 Phase2 positive 结果同步到 thread ledger。

    创建时间: 2026-04-26
    任务: phase2-setup-pool
    新建原因: thread 状态更新、命中插入、出池归档必须作为单一事务步骤执行，避免 chunk 视图和 ledger 漂移。
    """

    if not result.has_foreshadowing:
        raise ValueError("sync_foreshadowing_thread only accepts positive foreshadowing results")

    now = datetime.utcnow()

    if result.is_new_setup:
        matched_thread = _find_exact_matching_active_thread(
            session,
            run_id=run_id,
            chunk_id=chunk_id,
            result=result,
        )
        if matched_thread is not None:
            hit_count = _count_thread_hits(session, matched_thread.setup_id) + 1
            matched_thread.last_chunk_id = chunk_id
            matched_thread.payoff_likelihood = result.payoff_likelihood or matched_thread.payoff_likelihood
            matched_thread.strength = _derive_thread_strength(
                payoff_likelihood=matched_thread.payoff_likelihood,
                status="reinforced",
                hit_count=hit_count,
                prior_strength=matched_thread.strength,
            )
            matched_thread.status = "reinforced"
            matched_thread.active = True
            matched_thread.updated_at = now
            _insert_thread_hit(
                session,
                setup_id=matched_thread.setup_id,
                run_id=run_id,
                chunk_id=chunk_id,
                result=result,
                is_new_setup=False,
            )
            _archive_overflow_threads(session, run_id=run_id)
            return ForeshadowingThreadProjection(
                setup_id=matched_thread.setup_id,
                setup_summary=matched_thread.setup_summary,
                expected_payoff_family=matched_thread.expected_payoff_family,
                payoff_likelihood=(
                    matched_thread.payoff_likelihood
                    if matched_thread.payoff_likelihood in _VALID_PAYOFF_LIKELIHOODS
                    else "medium"
                ),
                setup_status="reinforced",
            )

        setup_id = str(uuid4())
        result_payoff_likelihood: ForeshadowingPayoffLikelihood = result.payoff_likelihood or "medium"
        strength = _derive_thread_strength(
            payoff_likelihood=result_payoff_likelihood,
            status="open",
            hit_count=1,
        )
        session.add(
            ForeshadowingThread(
                setup_id=setup_id,
                run_id=run_id,
                first_chunk_id=chunk_id,
                last_chunk_id=chunk_id,
                setup_summary=result.setup_summary,
                setup_kind=result.setup_kind or "其他",
                expected_payoff_family=result.expected_payoff_family,
                payoff_likelihood=result_payoff_likelihood,
                strength=strength,
                status="open",
                active=True,
                created_at=now,
                updated_at=now,
            )
        )
        _insert_thread_hit(
            session,
            setup_id=setup_id,
            run_id=run_id,
            chunk_id=chunk_id,
            result=result,
            is_new_setup=True,
        )
        _archive_overflow_threads(session, run_id=run_id)
        return ForeshadowingThreadProjection(
            setup_id=setup_id,
            setup_summary=result.setup_summary,
            expected_payoff_family=result.expected_payoff_family,
            payoff_likelihood=result_payoff_likelihood,
            setup_status="open",
        )

    thread = session.get(ForeshadowingThread, result.linked_setup_id)
    if thread is None or thread.run_id != run_id:
        raise ValueError(f"Unknown setup thread: {result.linked_setup_id}")

    hit_count = _count_thread_hits(session, thread.setup_id) + 1
    thread.last_chunk_id = chunk_id
    thread.payoff_likelihood = result.payoff_likelihood or thread.payoff_likelihood
    thread.strength = _derive_thread_strength(
        payoff_likelihood=thread.payoff_likelihood,
        status=result.setup_status or "reinforced",
        hit_count=hit_count,
        prior_strength=thread.strength,
    )
    thread.status = result.setup_status or "reinforced"
    thread.active = True
    thread.updated_at = now
    _insert_thread_hit(
        session,
        setup_id=thread.setup_id,
        run_id=run_id,
        chunk_id=chunk_id,
        result=result,
        is_new_setup=False,
    )
    _archive_overflow_threads(session, run_id=run_id)
    return ForeshadowingThreadProjection(
        setup_id=thread.setup_id,
        setup_summary=thread.setup_summary,
        expected_payoff_family=thread.expected_payoff_family,
        payoff_likelihood=(
            thread.payoff_likelihood
            if thread.payoff_likelihood in _VALID_PAYOFF_LIKELIHOODS
            else "medium"
        ),
        setup_status=thread.status if thread.status in _VALID_RUNTIME_SETUP_STATUSES else "reinforced",
    )


def calculate_foreshadow_expectation(session, run_id: str) -> float | None:
    """
    基于 thread ledger 计算伏笔回收预期。

    创建时间: 2026-04-26
    任务: phase2-setup-pool
    新建原因: diagnosis 展示值改由 setup ledger 驱动，不能再把 cloud_analysis 当成唯一真相源。
    """

    stmt = select(ForeshadowingThread).where(
        ForeshadowingThread.run_id == run_id,
        ForeshadowingThread.status != "false_positive",
    )
    threads = session.execute(stmt).scalars().all()
    if not threads:
        return None

    weighted_total = 0.0
    for thread in threads:
        if thread.status == "likely_paid_off":
            weighted_total += 1.0
        elif thread.payoff_likelihood == "high":
            weighted_total += 0.7
        elif thread.payoff_likelihood == "medium":
            weighted_total += 0.4

    return round(weighted_total / len(threads), 4)


def fetch_foreshadowing_threads(session, run_id: str) -> list[ForeshadowingThreadView]:
    """
    查询某次 run 的全部 setup thread 视图。

    创建时间: 2026-04-26
    任务: phase2-setup-pool
    新建原因: 结果接口与导出都需要统一的 thread 汇总视图，避免 route 层手写聚合。
    """

    threads_stmt = (
        select(ForeshadowingThread)
        .where(ForeshadowingThread.run_id == run_id)
        .order_by(ForeshadowingThread.first_chunk_id, ForeshadowingThread.last_chunk_id)
    )
    threads = session.execute(threads_stmt).scalars().all()
    if not threads:
        return []

    hits_stmt = (
        select(ForeshadowingThreadHit)
        .where(ForeshadowingThreadHit.run_id == run_id)
        .order_by(ForeshadowingThreadHit.setup_id, ForeshadowingThreadHit.chunk_id, ForeshadowingThreadHit.hit_id)
    )
    hits = session.execute(hits_stmt).scalars().all()
    hits_by_setup: dict[str, list[ForeshadowingThreadHit]] = {}
    for hit in hits:
        hits_by_setup.setdefault(hit.setup_id, []).append(hit)

    results: list[ForeshadowingThreadView] = []
    for thread in threads:
        thread_hits = hits_by_setup.get(thread.setup_id, [])
        anchor_chunk_ids = sorted({hit.chunk_id for hit in thread_hits})
        latest_hit = thread_hits[-1] if thread_hits else None
        results.append(
            ForeshadowingThreadView(
                setup_id=thread.setup_id,
                first_chunk_id=thread.first_chunk_id,
                last_chunk_id=thread.last_chunk_id,
                anchor_chunk_ids=anchor_chunk_ids,
                setup_summary=thread.setup_summary,
                setup_kind=thread.setup_kind,
                expected_payoff_family=thread.expected_payoff_family,
                payoff_likelihood=thread.payoff_likelihood,
                strength=thread.strength,
                status=thread.status,
                active=bool(thread.active),
                latest_reason=latest_hit.anchor_reason if latest_hit else "",
                latest_why_unresolved_now=latest_hit.why_unresolved_now if latest_hit else "",
            )
        )
    return results
