"""
setup 池 / thread ledger 相关仓储操作

收紧 active 池可见性边界与 linked thread 一致性校验，避免 invisible thread merge
          和 setup 误链接污染 ledger
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import func, select

from src.config import settings
from src.models.local.schema import (
    ForeshadowingPayoffLikelihood,
    ForeshadowingResult,
    ForeshadowingSetupStatus,
    ForeshadowingThreadStrength,
)
from src.storage.models import ForeshadowingThread, ForeshadowingThreadHit

ACTIVE_SETUP_POOL_LIMIT = settings.analysis.agents.annotation.active_setup_pool_limit
_VALID_PAYOFF_LIKELIHOODS = {"high", "medium"}
_VALID_THREAD_CONFIDENCES = {"high", "medium"}
_VALID_RUNTIME_SETUP_STATUSES = {"open", "reinforced", "likely_paid_off"}
_EXPECTATION_BASE_SCORE_BY_PAYOFF = {
    "high": 0.62,
    "medium": 0.38,
}
_EXPECTATION_STATUS_BONUS = {
    "open": -0.07,
    "reinforced": 0.03,
    "likely_paid_off": 0.28,
}
_EXPECTATION_STRENGTH_BONUS = {
    "high": 0.03,
    "medium": 0.0,
}
_EXPECTATION_STATUS_WEIGHT = {
    "open": 0.75,
    "reinforced": 1.0,
    "likely_paid_off": 1.2,
}


def _get_active_setup_pool_limit() -> int:
    """
    读取当前 setup 池上限配置

    active pool limit 现在来自 settings，不能再让默认参数在模块导入时把旧值固化
    """

    configured_limit = settings.analysis.agents.annotation.active_setup_pool_limit
    return configured_limit if configured_limit > 0 else ACTIVE_SETUP_POOL_LIMIT


@dataclass(frozen=True)
class ActiveSetupPoolEntry:
    """
    Phase2 prompt 用的活跃 setup 摘要

    prompt 只需要稳定摘要字段，不应直接暴露 ORM 对象给消息层
    """

    setup_id: str
    setup_summary: str
    setup_kind: str
    expected_payoff_family: str
    payoff_likelihood: str
    confidence: str
    strength: str
    status: str
    last_chunk_id: int


@dataclass(frozen=True)
class ForeshadowingThreadProjection:
    """
    thread 同步后的 chunk 视图投影

    chunk_annotation 需要写入“实际归属到哪个 thread”的结果，
    不能直接复用 chunk_foreshadowing 的原始 Phase2 输出
    """

    setup_id: str
    setup_summary: str
    expected_payoff_family: str
    payoff_likelihood: ForeshadowingPayoffLikelihood
    setup_status: ForeshadowingSetupStatus


@dataclass(frozen=True)
class ForeshadowingThreadView:
    """
    结果接口使用的 thread 汇总视图

    API 需要稳定的序列化视图，避免把 ORM 细节泄漏到 route 层
    """

    setup_id: str
    first_chunk_id: int
    last_chunk_id: int
    anchor_chunk_ids: list[int]
    setup_summary: str
    setup_kind: str
    expected_payoff_family: str
    payoff_likelihood: str
    confidence: str
    strength: str
    status: str
    active: bool
    latest_reason: str
    latest_why_unresolved_now: str


def _normalize_setup_summary(value: str) -> str:
    """
    标准化 setup_summary 以做 exact-match 去重

    v1 明确不做模糊语义 merge，只做“同 kind + 同 payoff + 同标准化 summary”的保守并线
    """

    return re.sub(r"[\W_]+", "", value, flags=re.UNICODE).strip().lower()


def _utcnow_naive() -> datetime:
    """
    返回用于当前无时区列的 UTC 时间戳

    Python 已弃用 datetime.utcnow()；这里统一生成“语义上是 UTC、落库仍保持 naive”的时间值，
    避免 warning 并保持现有表结构兼容
    """

    return datetime.now(UTC).replace(tzinfo=None)


def _normalize_thread_confidence(value: str | None) -> str:
    """
    2026-04-29，任务：伏笔回收预期 v2 口径修复
    新建原因：thread ledger 新增 confidence 后，旧库历史行和测试桩仍可能没有该列值；
              这里统一把缺失值收口为 high，保持老数据的既有语义。
    """

    return value if value in _VALID_THREAD_CONFIDENCES else "high"


def _require_result_confidence(result: ForeshadowingResult) -> str:
    """
    2026-04-29，任务：伏笔回收预期 v2 口径修复
    新建原因：medium/high 的差异现在需要进入 thread ledger；storage 层不能再默默丢掉
              Phase2 已经明确给出的 confidence。
    """

    if result.confidence not in _VALID_THREAD_CONFIDENCES:
        raise ValueError("positive foreshadowing result requires confidence to be high or medium")
    return result.confidence


def _merge_thread_confidence(*, prior_confidence: str | None, incoming_confidence: str) -> str:
    """
    2026-04-29，任务：伏笔回收预期 v2 口径修复
    新建原因：thread 级 confidence 表示“这条 setup 目前被确认到的最高稳定置信度”；
              一旦某次命中已经达到 high，不应再被后续较弱 hit 降回 medium。
    """

    normalized_prior = _normalize_thread_confidence(prior_confidence)
    if normalized_prior == "high" or incoming_confidence == "high":
        return "high"
    return "medium"


def _derive_thread_strength(
    *,
    payoff_likelihood: str,
    confidence: str,
    status: str,
    hit_count: int,
    prior_strength: str | None = None,
) -> ForeshadowingThreadStrength:
    """
    计算 thread 强度

    thread 强度不由模型直接输出，而是根据命中次数、当前状态、payoff 预期和
    thread confidence 在仓储层稳定推导
    """

    if prior_strength == "high":
        return "high"
    if status == "likely_paid_off":
        return "high"
    if payoff_likelihood == "high" and confidence == "high":
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
    插入一条 thread 命中记录

    命中明细需要单独留存，后续 API 才能回放 anchor_chunk_ids 与 latest_reason
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
            created_at=_utcnow_naive(),
        )
    )


def _count_thread_hits(session, setup_id: str) -> int:
    """
    统计某条 thread 的命中次数

    强度推导依赖命中次数，不能在调用方手工拼
    """

    stmt = select(func.count()).select_from(ForeshadowingThreadHit).where(ForeshadowingThreadHit.setup_id == setup_id)
    return int(session.execute(stmt).scalar_one())


def _count_thread_hits_for_run(session, run_id: str) -> dict[str, int]:
    """
    2026-04-29，任务：伏笔回收预期 v2 口径修复
    新建原因：expectation v2 需要按 thread 命中次数加权，统一在仓储层用语义字段聚合 hit_count。
    """

    stmt = (
        select(ForeshadowingThreadHit.setup_id, func.count(ForeshadowingThreadHit.hit_id).label("hit_count"))
        .where(ForeshadowingThreadHit.run_id == run_id)
        .group_by(ForeshadowingThreadHit.setup_id)
    )
    rows = session.execute(stmt).all()
    return {row.setup_id: int(row.hit_count) for row in rows}


def _require_result_payoff_likelihood(result: ForeshadowingResult) -> ForeshadowingPayoffLikelihood:
    """
    2026-04-29，任务：伏笔回收预期 v2 口径修复
    新建原因：本轮不兼容旧 positive 缺字段输出，ledger 写入必须显式要求 high/medium payoff_likelihood。
    """

    if result.payoff_likelihood not in _VALID_PAYOFF_LIKELIHOODS:
        raise ValueError("positive foreshadowing result requires payoff_likelihood to be high or medium")
    return result.payoff_likelihood


def _require_result_setup_status(result: ForeshadowingResult) -> ForeshadowingSetupStatus:
    """
    2026-04-29，任务：伏笔回收预期 v2 口径修复
    新建原因：ledger 写入不再为旧 positive 输出补默认 status，缺失或不匹配时必须显式失败。
    """

    if result.setup_status not in _VALID_RUNTIME_SETUP_STATUSES:
        raise ValueError("positive foreshadowing result requires setup_status")
    if result.is_new_setup and result.setup_status != "open":
        raise ValueError("new setup result requires setup_status=open")
    if not result.is_new_setup and result.setup_status == "open":
        raise ValueError("linked setup result requires setup_status to be reinforced or likely_paid_off")
    return result.setup_status


def _select_visible_active_threads(
    session,
    *,
    run_id: str,
    max_chunk_id: int,
    limit: int | None = None,
) -> list[ForeshadowingThread]:
    """
    读取当前 chunk 真正“可见”的 active setup 集合

    prompt 侧和仓储侧 exact-match 必须共享同一套可见性边界，
    不能一边只看前 30 条、一边扫描所有 active thread
    """

    pool_limit = limit if limit is not None else _get_active_setup_pool_limit()
    stmt = (
        select(ForeshadowingThread)
        .where(
            ForeshadowingThread.run_id == run_id,
            ForeshadowingThread.active.is_(True),
            ForeshadowingThread.last_chunk_id <= max_chunk_id,
        )
        .order_by(ForeshadowingThread.last_chunk_id.desc(), ForeshadowingThread.updated_at.desc())
        .limit(pool_limit)
    )
    return session.execute(stmt).scalars().all()


def _result_matches_thread_identity(
    result: ForeshadowingResult,
    *,
    setup_summary: str,
    setup_kind: str,
    expected_payoff_family: str,
) -> bool:
    """
    判断 Phase2 返回结果是否与目标 thread 身份一致

    linked_setup_id 不能只验证“存在于可见池”，还要确认模型返回的稳定字段
    与目标 thread 摘要一致，避免误把命中记到错误 setup 上
    """

    if _normalize_setup_summary(result.setup_summary) != _normalize_setup_summary(setup_summary):
        return False
    if (result.setup_kind or "其他").strip() != (setup_kind or "其他").strip():
        return False
    return result.expected_payoff_family.strip() == expected_payoff_family.strip()


def _find_exact_matching_active_thread(
    session,
    *,
    run_id: str,
    chunk_id: int,
    result: ForeshadowingResult,
) -> ForeshadowingThread | None:
    """
    用精确规则查找应并入的已有 active thread

    v1 只允许 exact-match 去重，防止 setup 池在没有明确证据时发生过度合并
    """

    normalized_summary = _normalize_setup_summary(result.setup_summary)
    for thread in _select_visible_active_threads(
        session,
        run_id=run_id,
        max_chunk_id=chunk_id - 1,
    ):
        if thread.setup_kind != result.setup_kind:
            continue
        if thread.expected_payoff_family != result.expected_payoff_family:
            continue
        if _normalize_setup_summary(thread.setup_summary) == normalized_summary:
            return thread
    return None


def _archive_overflow_threads(session, *, run_id: str, limit: int | None = None) -> None:
    """
    按 last_chunk_id 从近到远保留 active 池，超限部分归档

    活跃池上限是固定工程口径，归档规则必须统一收口到仓储层

    `active` 已经足够表达“是否仍在 prompt 可见池”；
    出池时不能再覆盖 thread 语义状态，否则 diagnosis 的 expectation 会误读 lifecycle
    """

    pool_limit = limit if limit is not None else _get_active_setup_pool_limit()
    # 仓库 session 显式关闭了 autoflush；
    # 这里必须先 flush，后面的 active 查询才能看到刚刚插入/更新的 thread，
    # 否则 overflow 判断会基于旧快照，留下“prompt 不可见但 active=true”的脏 thread
    session.flush()
    stmt = (
        select(ForeshadowingThread)
        .where(ForeshadowingThread.run_id == run_id, ForeshadowingThread.active.is_(True))
        .order_by(ForeshadowingThread.last_chunk_id.desc(), ForeshadowingThread.updated_at.desc())
    )
    active_threads = session.execute(stmt).scalars().all()
    if len(active_threads) <= pool_limit:
        return

    for thread in active_threads[pool_limit:]:
        thread.active = False
        thread.updated_at = _utcnow_naive()


def fetch_active_foreshadowing_threads_for_prompt(
    session,
    run_id: str,
    *,
    max_chunk_id: int,
    limit: int | None = None,
) -> list[ActiveSetupPoolEntry]:
    """
    查询当前 chunk 可见的活跃 setup 池

    Phase2 在调用前必须读取“截至 chunk_id-1 可见”的活跃池，不能偷看当前或后文状态
    """

    rows = _select_visible_active_threads(
        session,
        run_id=run_id,
        max_chunk_id=max_chunk_id,
        limit=limit,
    )
    return [
        ActiveSetupPoolEntry(
            setup_id=row.setup_id,
            setup_summary=row.setup_summary,
            setup_kind=row.setup_kind,
            expected_payoff_family=row.expected_payoff_family,
            payoff_likelihood=row.payoff_likelihood,
            confidence=_normalize_thread_confidence(getattr(row, "confidence", None)),
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
    将一条 Phase2 positive 结果同步到 thread ledger

    thread 状态更新、命中插入、出池归档必须作为单一事务步骤执行，避免 chunk 视图和 ledger 漂移

    修改时间: 2026-04-29
    任务: foreshadow-expectation-v2
    修改原因: ledger 写入不再兼容 positive 缺失 payoff_likelihood 的旧输出，必须显式携带 high/medium。
    """

    if not result.has_foreshadowing:
        raise ValueError("sync_foreshadowing_thread only accepts positive foreshadowing results")

    result_payoff_likelihood = _require_result_payoff_likelihood(result)
    result_confidence = _require_result_confidence(result)
    result_setup_status = _require_result_setup_status(result)
    now = _utcnow_naive()

    if result.is_new_setup:
        matched_thread = _find_exact_matching_active_thread(
            session,
            run_id=run_id,
            chunk_id=chunk_id,
            result=result,
        )
        if matched_thread is not None:
            hit_count = _count_thread_hits(session, matched_thread.setup_id) + 1
            merged_confidence = _merge_thread_confidence(
                prior_confidence=getattr(matched_thread, "confidence", None),
                incoming_confidence=result_confidence,
            )
            matched_thread.last_chunk_id = chunk_id
            matched_thread.payoff_likelihood = result_payoff_likelihood
            matched_thread.confidence = merged_confidence
            matched_thread.strength = _derive_thread_strength(
                payoff_likelihood=matched_thread.payoff_likelihood,
                confidence=matched_thread.confidence,
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
                payoff_likelihood=result_payoff_likelihood,
                setup_status="reinforced",
            )

        setup_id = str(uuid4())
        thread_confidence = result_confidence
        strength = _derive_thread_strength(
            payoff_likelihood=result_payoff_likelihood,
            confidence=thread_confidence,
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
                confidence=thread_confidence,
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
    if not _result_matches_thread_identity(
        result,
        setup_summary=thread.setup_summary,
        setup_kind=thread.setup_kind,
        expected_payoff_family=thread.expected_payoff_family,
    ):
        raise ValueError(f"linked_setup_id payload does not match setup thread identity: {result.linked_setup_id}")

    hit_count = _count_thread_hits(session, thread.setup_id) + 1
    thread_confidence = _merge_thread_confidence(
        prior_confidence=getattr(thread, "confidence", None),
        incoming_confidence=result_confidence,
    )
    thread.last_chunk_id = chunk_id
    thread.payoff_likelihood = result_payoff_likelihood
    thread.confidence = thread_confidence
    thread.strength = _derive_thread_strength(
        payoff_likelihood=thread.payoff_likelihood,
        confidence=thread.confidence,
        status=result_setup_status,
        hit_count=hit_count,
        prior_strength=thread.strength,
    )
    thread.status = result_setup_status
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
        payoff_likelihood=result_payoff_likelihood,
        setup_status=result_setup_status,
    )


def _clamp_expectation_score(value: float) -> float:
    """
    2026-04-29，任务：伏笔回收预期 v2 口径修复
    新建原因：单条 thread 的 score 由多个语义项相加，最终必须稳定收口到 0-1 区间。
    """

    return max(0.0, min(1.0, value))


def _get_hit_score_bonus(hit_count: int) -> float:
    """
    2026-04-29，任务：伏笔回收预期 v2 口径修复
    新建原因：命中次数是 thread 被持续强化的证据，需要进入单条 thread 的预期分。
    """

    if hit_count >= 3:
        return 0.08
    if hit_count == 2:
        return 0.04
    return 0.0


def _get_hit_weight_bonus(hit_count: int) -> float:
    """
    2026-04-29，任务：伏笔回收预期 v2 口径修复
    新建原因：多次命中的 thread 应在聚合时获得更高权重，避免单次 open thread 与强化 thread 等权。
    """

    if hit_count >= 3:
        return 0.20
    if hit_count == 2:
        return 0.10
    return 0.0


def _calculate_thread_expectation_score(thread: ForeshadowingThread, *, hit_count: int) -> float:
    """
    2026-04-29，任务：伏笔回收预期 v2 口径修复
    新建原因：用 payoff/status/strength/hit_count 共同决定单条 thread 预期，
              不再把 open/high 与 reinforced/high 等同处理。
    """

    if thread.payoff_likelihood not in _EXPECTATION_BASE_SCORE_BY_PAYOFF:
        raise ValueError(f"Unsupported payoff_likelihood for foreshadow expectation: {thread.payoff_likelihood}")
    if thread.status not in _EXPECTATION_STATUS_BONUS:
        raise ValueError(f"Unsupported setup status for foreshadow expectation: {thread.status}")
    if thread.strength not in _EXPECTATION_STRENGTH_BONUS:
        raise ValueError(f"Unsupported thread strength for foreshadow expectation: {thread.strength}")
    if hit_count < 1:
        raise ValueError(f"Foreshadowing thread has no hits: {thread.setup_id}")

    raw_score = (
        _EXPECTATION_BASE_SCORE_BY_PAYOFF[thread.payoff_likelihood]
        + _EXPECTATION_STATUS_BONUS[thread.status]
        + _EXPECTATION_STRENGTH_BONUS[thread.strength]
        + _get_hit_score_bonus(hit_count)
    )
    return _clamp_expectation_score(raw_score)


def _calculate_thread_expectation_weight(thread: ForeshadowingThread, *, hit_count: int) -> float:
    """
    2026-04-29，任务：伏笔回收预期 v2 口径修复
    新建原因：聚合阶段需要让生命周期推进、命中次数和强度影响 thread 权重，提升指标分辨率。
    """

    if thread.status not in _EXPECTATION_STATUS_WEIGHT:
        raise ValueError(f"Unsupported setup status for foreshadow expectation weight: {thread.status}")
    if thread.strength not in _EXPECTATION_STRENGTH_BONUS:
        raise ValueError(f"Unsupported thread strength for foreshadow expectation weight: {thread.strength}")
    if hit_count < 1:
        raise ValueError(f"Foreshadowing thread has no hits: {thread.setup_id}")

    strength_bonus = 0.05 if thread.strength == "high" else 0.0
    return _EXPECTATION_STATUS_WEIGHT[thread.status] + _get_hit_weight_bonus(hit_count) + strength_bonus


def calculate_foreshadow_expectation(session, run_id: str) -> float | None:
    """
    基于 thread ledger 计算伏笔回收预期

    diagnosis 展示值改由 setup ledger 驱动，不能再把 cloud_analysis 当成唯一真相源

    修改时间: 2026-04-29
    任务: foreshadow-expectation-v2
    修改原因: 旧公式只按 payoff_likelihood 三档等权平均，容易塌成 0.7；现在改为 thread 语义加权聚合。
    """

    stmt = select(ForeshadowingThread).where(
        ForeshadowingThread.run_id == run_id,
        ForeshadowingThread.status != "false_positive",
    )
    threads = session.execute(stmt).scalars().all()
    if not threads:
        return None

    hit_counts_by_setup = _count_thread_hits_for_run(session, run_id)
    weighted_total = 0.0
    total_weight = 0.0
    for thread in threads:
        hit_count = hit_counts_by_setup.get(thread.setup_id, 0)
        thread_score = _calculate_thread_expectation_score(thread, hit_count=hit_count)
        thread_weight = _calculate_thread_expectation_weight(thread, hit_count=hit_count)
        weighted_total += thread_score * thread_weight
        total_weight += thread_weight

    if total_weight <= 0:
        raise ValueError(f"Foreshadowing expectation total weight must be positive: run_id={run_id}")
    return round(weighted_total / total_weight, 4)


def fetch_foreshadowing_threads(session, run_id: str) -> list[ForeshadowingThreadView]:
    """
    查询某次 run 的全部 setup thread 视图

    结果接口与导出都需要统一的 thread 汇总视图，避免 route 层手写聚合
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
                confidence=_normalize_thread_confidence(getattr(thread, "confidence", None)),
                strength=thread.strength,
                status=thread.status,
                active=bool(thread.active),
                latest_reason=latest_hit.anchor_reason if latest_hit else "",
                latest_why_unresolved_now=latest_hit.why_unresolved_now if latest_hit else "",
            )
        )
    return results
