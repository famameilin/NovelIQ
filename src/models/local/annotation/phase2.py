"""
说明: Phase2 伏笔分析逻辑
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from src.config import settings
from src.models.local.retry_handler import AnnotationRetryHandler, RetryConfig
from src.models.local.schema import ForeshadowingResult

from .context import Phase2MaxRetriesExceededError
from .messages import _build_foreshadowing_messages
from .runtime import AnnotationPhaseCallSpec, execute_phase_call

if TYPE_CHECKING:
    from src.models.annotation import AnnotationClient


def _normalize_setup_summary_for_link_check(value: str) -> str:
    """
    标准化 setup_summary，用于 linked_setup_id 身份一致性校验
    """

    return re.sub(r"[\W_]+", "", value, flags=re.UNICODE).strip().lower()


async def _do_phase2(
    client: AnnotationClient,
    messages: list[dict],
    text: str,
    prev_chunk_summary: str | None,
    chunk_id: int | None,
    run_id: str | None = None,
    attempt_number: int = 1,
) -> ForeshadowingResult:
    """
    执行Phase2单次调用
    """
    is_cloud = client._is_cloud_api()
    client._log_annotation_start(is_cloud, text, prev_chunk_summary, chunk_id, "phase2")

    call_result = await execute_phase_call(
        client,
        AnnotationPhaseCallSpec(
            phase="phase2",
            interaction_type="annotate",
            call_type="phase2",
            messages=messages,
            response_model=ForeshadowingResult,
            chunk_id=chunk_id,
            run_id=run_id,
            attempt_number=attempt_number,
        ),
    )

    if call_result.extraction is not None:
        client._log_prompt_response(
            chunk_id,
            call_result.content_clean,
            call_result.thinking_content,
            call_result.extraction,
            messages,
            text,
            prev_chunk_summary,
        )

    return call_result.parsed


async def annotate_chunk_phase2(
    client: AnnotationClient,
    text: str,
    prev_chunk_summary: str | None = None,
    chunk_id: int | None = None,
    novel_title: str | None = None,
    main_characters: str | None = None,
    position_pct: float | None = None,
    chapter_id: int | None = None,
    fallback_client: AnnotationClient | None = None,
    run_id: str | None = None,
    evidence_bundle=None,
) -> ForeshadowingResult | None:
    """
    第二次调用：伏笔分析（带独立重试机制）
    """
    from src.models.local.schema import ForeshadowingResult
    from src.storage.repositories import AnnotationRepository

    phase_max_retries = settings.runtime.annotation.phase_max_retries
    config = RetryConfig(
        max_retries=phase_max_retries,
        operation_name="phase2",
        chunk_id=chunk_id,
    )
    handler = AnnotationRetryHandler[ForeshadowingResult](
        config=config,
        primary_client=client,
        fallback_client=fallback_client,
        exception_type=Phase2MaxRetriesExceededError,
    )

    active_setup_pool = []
    if run_id and chunk_id is not None and getattr(client, "_session", None) is not None and chunk_id > 0:
        # 活跃池只允许看到当前 chunk 之前已经落库的 thread，
        # 这里固定读取 chunk_id-1 可见状态，避免 Phase2 因同 chunk 内的其他副作用“偷看现在”
        active_setup_pool = AnnotationRepository(client._session).fetch_active_foreshadowing_threads_for_prompt(
            run_id,
            max_chunk_id=chunk_id - 1,
        )

    # Phase2 只消费调用方已经准备好的 evidence_bundle，
    # 避免在本阶段继续分叉出新的取证链路，扩大这轮收口任务的边界
    # include_phase2_evidence=False 时只关闭 prompt 注入，不改上游取证与调度路径，
    # 方便做方案文档要求的 targeted ablation
    include_evidence_blocks = settings.analysis.multi_phase_annotation.include_phase2_evidence
    messages = _build_foreshadowing_messages(
        text=text,
        prev_chunk_summary=prev_chunk_summary,
        chunk_id=chunk_id,
        novel_title=novel_title,
        main_characters=main_characters,
        position_pct=position_pct,
        chapter_id=chapter_id,
        evidence_bundle=evidence_bundle,
        include_evidence_blocks=include_evidence_blocks,
        active_setup_pool=active_setup_pool,
    )

    async def operation(
        primary_client: AnnotationClient,
        retry_messages: list[dict] | None = None,
    ) -> ForeshadowingResult:
        """执行单次Phase2调用"""
        msgs = retry_messages if retry_messages else messages
        result = await _do_phase2(
            primary_client,
            msgs,
            text,
            prev_chunk_summary,
            chunk_id,
            run_id,
            handler.state.attempt,
        )
        _validate_phase2_active_setup_link(result, active_setup_pool)
        return result

    return await handler.execute(operation)


def _validate_phase2_active_setup_link(
    result: ForeshadowingResult,
    active_setup_pool,
) -> None:
    """
    校验 Phase2 返回的 linked_setup_id 是否来自当前可见活跃池
    """

    if not result.has_foreshadowing or result.is_new_setup:
        return

    matched_entry = next(
        (entry for entry in active_setup_pool if entry.setup_id == result.linked_setup_id),
        None,
    )
    if matched_entry is None:
        raise ValueError(f"linked_setup_id is not in active setup pool: {result.linked_setup_id}")
    if _normalize_setup_summary_for_link_check(result.setup_summary) != _normalize_setup_summary_for_link_check(
        str(getattr(matched_entry, "setup_summary", ""))
    ):
        raise ValueError(f"linked_setup_id summary does not match active setup pool: {result.linked_setup_id}")
    if (result.setup_kind or "其他") != str(getattr(matched_entry, "setup_kind", "其他")):
        raise ValueError(f"linked_setup_id setup_kind does not match active setup pool: {result.linked_setup_id}")
    if result.expected_payoff_family.strip() != str(getattr(matched_entry, "expected_payoff_family", "")).strip():
        raise ValueError(
            f"linked_setup_id expected_payoff_family does not match active setup pool: {result.linked_setup_id}"
        )
