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
"""

from __future__ import annotations

import re
import time
from typing import TYPE_CHECKING, Any

from src.config.constants import PHASE_MAX_RETRIES
from src.models.interactions import record_model_interaction
from src.models.local.retry_handler import AnnotationRetryHandler, RetryConfig
from src.models.local.schema import ForeshadowingResult

from .context import Phase2MaxRetriesExceededError
from .messages import _build_foreshadowing_messages

if TYPE_CHECKING:
    from src.models.annotation import AnnotationClient


def _extract_names_from_text(text: str) -> list[str]:
    """从当前 chunk 中提取用于 evidence 过滤的人名候选。"""

    return re.findall(r"[\u4e00-\u9fff]{2,4}", text)


async def _collect_phase2_evidence_bundle(
    *,
    text: str,
    chunk_id: int | None,
    rag_retriever: Any | None,
):
    if rag_retriever is None:
        return None

    names_in_chunk = _extract_names_from_text(text)
    exclude_chunk_ids = [chunk_id] if chunk_id is not None else None

    if rag_retriever.requires_level3():
        if not rag_retriever.is_level3_available():
            raise RuntimeError("Level 3 vector retrieval is required but not available")
        return await rag_retriever.collect_evidence_with_level3(
            names_in_chunk=names_in_chunk,
            current_chunk=chunk_id,
            context_text=text,
            exclude_chunk_ids=exclude_chunk_ids,
        )

    if rag_retriever.is_level3_available():
        return await rag_retriever.collect_evidence_with_level3(
            names_in_chunk=names_in_chunk,
            current_chunk=chunk_id,
            context_text=text,
            exclude_chunk_ids=exclude_chunk_ids,
        )

    return rag_retriever.collect_evidence(
        names_in_chunk=names_in_chunk,
        current_chunk=chunk_id,
    )


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
    """
    start_time = time.time()
    is_cloud = client._is_cloud_api()
    client._log_annotation_start(is_cloud, text, prev_chunk_summary, chunk_id, "phase2")

    enable_thinking = client._config.thinking_enabled

    result, response = await client._call_annotation_api(
        messages=messages,
        enable_thinking=enable_thinking,
        chunk_id=chunk_id,
        response_model=ForeshadowingResult,
    )

    content_clean, thinking_content, extraction = client._process_annotation_response(
        response, is_cloud, chunk_id, "phase2"
    )

    duration_ms = int((time.time() - start_time) * 1000)

    record_model_interaction(
        run_id=run_id,
        chunk_id=chunk_id,
        interaction_type="annotate",
        phase="phase2",
        attempt_number=attempt_number,
        messages=messages,
        response_text=content_clean,
        thinking_content=thinking_content,
        duration_ms=duration_ms,
        model_name=client._config.model if hasattr(client._config, "model") else None,
        model_provider="cloud" if is_cloud else "local",
        session=client._session if hasattr(client, "_session") else None,
    )

    client._log_prompt_response(
        chunk_id, content_clean, thinking_content, extraction, messages, text, prev_chunk_summary
    )

    client._record_token_usage(response, "phase2", chunk_id)

    return result


async def annotate_chunk_phase2(
    client: AnnotationClient,
    text: str,
    prev_chunk_summary: str | None = None,
    chunk_id: int | None = None,
    prev_chunk_text: str | None = None,
    next_chunk_text: str | None = None,
    novel_title: str | None = None,
    main_characters: str | None = None,
    position_pct: float | None = None,
    chapter_id: int | None = None,
    cloud_client: AnnotationClient | None = None,
    run_id: str | None = None,
    rag_retriever: Any | None = None,
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
    """
    from src.models.local.schema import ForeshadowingResult

    config = RetryConfig(
        max_retries=PHASE_MAX_RETRIES,
        operation_name="phase2",
        chunk_id=chunk_id,
    )
    handler = AnnotationRetryHandler[ForeshadowingResult](
        config=config,
        local_client=client,
        cloud_client=cloud_client,
        exception_type=Phase2MaxRetriesExceededError,
    )

    resolved_evidence_bundle = evidence_bundle

    async def _resolve_phase2_messages() -> list[dict]:
        nonlocal resolved_evidence_bundle

        # 中文注释：把 evidence 检索放进重试闭包里，这样向量检索的瞬时失败也能走本地重试和云端兜底；
        # 一旦某次检索成功，就缓存 bundle，避免后续重试重复命中检索层。
        if resolved_evidence_bundle is None:
            resolved_evidence_bundle = await _collect_phase2_evidence_bundle(
                text=text,
                chunk_id=chunk_id,
                rag_retriever=rag_retriever,
            )

        return _build_foreshadowing_messages(
            text=text,
            prev_chunk_summary=prev_chunk_summary,
            chunk_id=chunk_id,
            prev_chunk_text=prev_chunk_text,
            next_chunk_text=next_chunk_text,
            novel_title=novel_title,
            main_characters=main_characters,
            position_pct=position_pct,
            chapter_id=chapter_id,
            evidence_bundle=resolved_evidence_bundle,
        )

    async def operation(
        local_client: AnnotationClient, retry_messages: list[dict] | None = None
    ) -> ForeshadowingResult:
        """执行单次Phase2调用"""
        msgs = retry_messages if retry_messages else await _resolve_phase2_messages()
        return await _do_phase2(local_client, msgs, text, prev_chunk_summary, chunk_id, run_id, handler.state.attempt)

    return await handler.execute(operation)
