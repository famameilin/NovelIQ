"""
创建时间: 2026-03-18
创建者: TraeAI
任务: code-quality-refactor - Task 9 拆分annotation_client
说明: Phase2 伏笔分析逻辑

修改时间: 2026-03-18
修改者: TraeAI
任务: code-quality-refactor - Task 3 统一重试机制
修改内容: 使用 AnnotationRetryHandler 统一重试逻辑

修改时间: 2026-03-19
修改者: TraeAI
任务: 添加模型交互记录保存
修改内容: 添加 save_model_interaction 工具函数

修改时间: 2026-03-27
修改者: TraeAI
任务: 创建统一的模型交互记录接口
修改内容: 使用 record_model_interaction 替代本地 _save_interaction 函数

修改时间: 2026-04-23
任务: annotation-projector-runtime-landing
修改内容: Phase2 单次结构化调用改为复用薄 phase runtime，避免重复维护交互记录与 token 估算。
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from src.config import settings
from src.models.local.retry_handler import AnnotationRetryHandler, RetryConfig
from src.models.local.schema import ForeshadowingResult

from .context import Phase2MaxRetriesExceededError
from .messages import _build_foreshadowing_messages
from .runtime import AnnotationPhaseCallSpec, execute_phase_call

if TYPE_CHECKING:
    from src.models.annotation import AnnotationClient


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

    创建时间: 2026-03-18
    创建者: TraeAI
    任务: code-quality-refactor - 提取Phase2单次调用逻辑

    修改时间: 2026-04-09
    修改者: TraeAI
    任务: 重构 AnnotationClient 使用 async
    修改内容: 改为 async def

    修改时间: 2026-04-22
    修改者: Codex
    任务: unify-estimated-token-accounting
    修改内容: Phase2 token_usage 改为统一估算口径，不再依赖 provider usage

    修改时间: 2026-04-22
    修改者: Codex
    任务: fix-token-coverage-fallback-bucket
    修改内容: fallback 标注客户端执行 Phase2 时，token_usage 仍归入 annotation 主业务桶，
              避免 coverage 把已入账调用误判成缺口

    修改时间: 2026-04-23
    任务: annotation-projector-runtime-landing
    修改内容: 委托 execute_phase_call 统一 response processing、thinking 持久化与 token usage。
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
    prev_chunk_text: str | None = None,
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

    创建时间: 2026-03-14
    创建者: TraeAI
    任务: Chunk 双次调用分析拆分

    修改时间: 2026-04-09
    修改者: TraeAI
    任务: 重构 AnnotationClient 使用 async
    修改内容: 改为 async def

    修改时间: 2026-04-26
    修改者: Codex
    任务: phase2-strong-foreshadowing
    修改内容:
    - 删除 next_chunk_text 残留透传，避免 Phase2 接口继续暗示存在后文输入
    - 增加共享 evidence 开关，支持在不改默认行为的前提下做 targeted ablation
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
        # 中文注释：活跃池只允许看到当前 chunk 之前已经落库的 thread，
        # 这里固定读取 chunk_id-1 可见状态，避免 Phase2 因同 chunk 内的其他副作用“偷看现在”。
        active_setup_pool = AnnotationRepository(client._session).fetch_active_foreshadowing_threads_for_prompt(
            run_id,
            max_chunk_id=chunk_id - 1,
        )

    # 中文注释：Phase2 只消费调用方已经准备好的 evidence_bundle，
    # 避免在本阶段继续分叉出新的取证链路，扩大这轮收口任务的边界。
    # include_phase2_evidence=False 时只关闭 prompt 注入，不改上游取证与调度路径，
    # 方便做方案文档要求的 targeted ablation。
    include_evidence_blocks = settings.analysis.multi_phase_annotation.include_phase2_evidence
    messages = _build_foreshadowing_messages(
        text=text,
        prev_chunk_summary=prev_chunk_summary,
        chunk_id=chunk_id,
        prev_chunk_text=prev_chunk_text,
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
    校验 Phase2 返回的 linked_setup_id 是否来自当前可见活跃池。

    创建时间: 2026-04-26
    任务: phase2-setup-pool
    新建原因: 无效 linked id 应该在 Phase2 重试阶段被显式打回，而不是拖到落库时才暴露。
    """

    if not result.has_foreshadowing or result.is_new_setup:
        return

    visible_setup_ids = {entry.setup_id for entry in active_setup_pool}
    if result.linked_setup_id not in visible_setup_ids:
        raise ValueError(f"linked_setup_id is not in active setup pool: {result.linked_setup_id}")
