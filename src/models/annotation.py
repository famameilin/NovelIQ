"""
AnnotationClient 模块

修改历史:

说明:
- 此类继承自 BaseModelClient，同时支持本地和云端
- 核心逻辑已移至 src.models.local.annotation 子包
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any, TypeVar

from pydantic import BaseModel

from src.api.models.events import StreamEvent
from src.config import TaskModelConfig, TaskType
from src.config.analysis_logger import AnalysisLogger
from src.models.local.base import BaseModelClient, TokenUsageCallback
from src.models.local.schema import ChunkAnnotation
from src.models.structured_output import StructuredOutputError, StructuredOutputRequest, call_structured_output

from .local.annotation import (
    AnnotationContext,
    MultiPhaseAnnotationResult,
    log_prompt_response,
    process_annotation_response,
)
from .local.annotation import (
    log_annotation_start as _log_annotation_start_impl,
)
from .local.annotation import (
    parse_annotation as _parse_annotation_impl,
)
from .local.annotation import (
    should_use_stream as _should_use_stream_impl,
)
from .local.annotation import (
    validate_annotation as _validate_annotation_impl,
)
from .local.annotation.multi_phase import annotate_chunk_multi_phase as _annotate_chunk_multi_phase_impl

T = TypeVar("T", bound=BaseModel)


class AnnotationClient(BaseModelClient):
    """
    统一标注客户端

    提供文本块的语义标注功能，支持单阶段和双阶段标注模式。
    同时支持本地和云端模型，通过 base_url 自动检测。
    """

    def __init__(
        self,
        task_type: TaskType = "annotation",
        config: TaskModelConfig | None = None,
        client: Any | None = None,
        analysis_logger: AnalysisLogger | None = None,
        token_usage_callback: TokenUsageCallback | None = None,
        novel_id: str | None = None,
        session: Any | None = None,
    ) -> None:
        """
        初始化 annotation 客户端。

        结构化输出机制说明:
        - 已移除 instructor_client_factory 参数，结构化输出不再依赖 Instructor 库
        - 统一走项目级 structured_output 适配层 (src.models.structured_output)
        - 通过 call_structured_output() 函数处理 json_schema / json_object 模式
        - 适配层自动根据 provider 能力选择最佳结构化输出方式
        """
        super().__init__(
            task_type=task_type,
            config=config,
            client=client,
            analysis_logger=analysis_logger,
            token_usage_callback=token_usage_callback,
            novel_id=novel_id,
            session=session,
        )
        self._emitter: Callable[[StreamEvent], Awaitable[None]] | None = None

    async def annotate_chunk(
        self,
        text: str,
        prev_summary: str | None = None,
        alias_map: dict[str, str] | None = None,
        chunk_id: int | None = None,
        global_context: str | None = None,
        active_entities: str | None = None,
        evidence_bundle: Any | None = None,
        phase1_bundle: Any | None = None,
        phase2_bundle: Any | None = None,
        phase3_bundle: Any | None = None,
        phase4_bundle: Any | None = None,
        phase4_request_template: Any | None = None,
        evidence_service: Any | None = None,
        novel_title: str | None = None,
        main_characters: str | None = None,
        position_pct: float | None = None,
        chapter_id: int | None = None,
        fallback_client: AnnotationClient | None = None,
        run_id: str | None = None,
        emitter: Callable[[StreamEvent], Awaitable[None]] | None = None,
        disambig_context: str | None = None,
    ) -> MultiPhaseAnnotationResult:
        # 设置当前 emitter，供所有 phase 调用链使用
        self._emitter = emitter

        ctx = AnnotationContext(
            text=text,
            prev_summary=prev_summary,
            alias_map=alias_map,
            chunk_id=chunk_id,
            global_context=global_context,
            active_entities=active_entities,
            disambig_context=disambig_context,
            phase1_bundle=phase1_bundle or evidence_bundle,
            phase2_bundle=phase2_bundle or evidence_bundle,
            phase3_bundle=phase3_bundle or phase1_bundle or evidence_bundle,
            phase4_bundle=phase4_bundle or evidence_bundle,
            phase4_request_template=phase4_request_template,
            evidence_service=evidence_service,
            novel_title=novel_title,
            main_characters=main_characters,
            position_pct=position_pct,
            chapter_id=chapter_id,
            fallback_client=fallback_client,
            run_id=run_id,
        )

        return await _annotate_chunk_multi_phase_impl(
            client=self,
            text=ctx.text,
            prev_summary=ctx.prev_summary,
            alias_map=ctx.alias_map,
            chunk_id=ctx.chunk_id,
            global_context=ctx.global_context,
            active_entities=ctx.active_entities,
            disambig_context=ctx.disambig_context,
            phase1_bundle=ctx.phase1_bundle,
            phase2_bundle=ctx.phase2_bundle,
            phase3_bundle=ctx.phase3_bundle,
            phase4_bundle=ctx.phase4_bundle,
            phase4_request_template=ctx.phase4_request_template,
            evidence_service=ctx.evidence_service,
            novel_title=ctx.novel_title,
            main_characters=ctx.main_characters,
            position_pct=ctx.position_pct,
            chapter_id=ctx.chapter_id,
            fallback_client=ctx.fallback_client,
            run_id=ctx.run_id,
            emitter=emitter,
        )

    async def _call_annotation_api(
        self,
        messages: list[dict],
        enable_thinking: bool,
        chunk_id: int | None,
        response_model: type[T] | None = None,
        emitter: Callable[[StreamEvent], Awaitable[None]] | None = None,
        call_type: str | None = None,
    ) -> Any:
        """
        调用 annotation 模型 API。
        """
        if not self._config.model:
            raise ValueError("model is required")

        if self._client is None:
            raise ValueError("client is required")

        is_cloud = self._is_cloud_api()
        active_emitter = emitter or self._emitter

        if response_model is not None:
            try:
                structured_result = await call_structured_output(
                    self,
                    StructuredOutputRequest(
                        messages=messages,
                        response_model=response_model,
                        call_type=call_type or "annotation",
                        enable_thinking=enable_thinking,
                        timeout=self._config.timeout_s,
                        stream=_should_use_stream_impl(self._config, is_cloud),
                        stream_emitter=active_emitter,
                    ),
                )
            except StructuredOutputError as exc:
                # 结构化解析失败时，模型响应可能已经返回，必须保留 token 补记。
                if call_type and exc.raw_response is not None:
                    token_task_type = "annotation" if self._task_type == "annotation_fallback" else None
                    self._record_estimated_token_usage_from_response(
                        messages,
                        exc.raw_response,
                        call_type,
                        chunk_id,
                        task_type=token_task_type,
                    )
                raise
            return structured_result.parsed, structured_result.raw_response

        request_params: dict[str, Any] = {
            "model": self._config.model,
            "messages": messages,
            "temperature": self._config.temperature,
            "top_p": self._config.top_p,
        }

        if enable_thinking:
            request_params["reasoning_effort"] = "medium"
            request_params["extra_body"] = {"think": True}

        response = await self._call_api_stream(request_params, is_cloud=is_cloud, emitter=active_emitter)
        return response

    def _parse_annotation(self, content: str) -> ChunkAnnotation:
        return _parse_annotation_impl(content)

    def _validate_annotation(
        self,
        result: ChunkAnnotation,
        sources: dict,
        chunk_id: int | None,
        content_clean: str = "",
    ) -> ChunkAnnotation:
        return _validate_annotation_impl(result, sources, chunk_id, content_clean)

    def _process_annotation_response(
        self,
        response: Any,
        is_cloud: bool,
        chunk_id: int | None = None,
        phase: str = "",
    ) -> tuple[str, str | None, Any]:
        return process_annotation_response(
            response=response,
            is_cloud=is_cloud,
            novel_id=self._novel_id,
            chunk_id=chunk_id,
            phase=phase,
        )

    def _log_annotation_start(
        self,
        is_cloud: bool,
        text: str,
        prev_summary: str | None,
        chunk_id: int | None,
        phase: str = "",
    ) -> None:
        _log_annotation_start_impl(
            novel_id=self._novel_id,
            task_type=self._task_type,
            model=self._config.model,
            thinking_enabled=self._config.thinking_enabled,
            is_cloud=is_cloud,
            text=text,
            prev_summary=prev_summary,
            chunk_id=chunk_id,
            phase=phase,
        )

    def _log_prompt_response(
        self,
        chunk_id: int | None,
        content_clean: str,
        thinking_content: str | None,
        extraction: Any,
        messages: list[dict],
        text: str,
        prev_summary: str | None,
    ) -> None:
        log_prompt_response(
            analysis_logger=self._analysis_logger,
            chunk_id=chunk_id,
            content_clean=content_clean,
            thinking_content=thinking_content,
            extraction=extraction,
            messages=messages,
            text=text,
            prev_summary=prev_summary,
            model=self._config.model or "",
            task_type=self._task_type,
        )


__all__ = ["AnnotationClient"]
