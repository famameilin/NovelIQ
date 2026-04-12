"""
AnnotationClient 模块

创建时间: 2026-03-12
创建者: TraeAI
任务: 项目文件结构整理与拆解 - 拆分标注专用客户端

修改历史:
- 2026-03-14: 添加双次调用模式支持（第一次：基础标注，第二次：伏笔分析）
- 2026-03-16: 集成 Instructor 实现结构化输出
- 2026-03-18: 拆分核心逻辑到 annotation/ 子包，简化此类
- 2026-03-23: 移动到 src/models/annotation.py（统一客户端架构）
- 2026-03-29: extra_body 只包含 think 参数（云端模型不支持 thinking 字段）
- 2026-04-07: 添加 stream_callback 参数支持（websocket-streaming-progress）
- 2026-04-09: 重构为 async def（适配 BaseModelClient._call_api_stream 异步化）

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
from src.rag import EvidenceBundle

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
        instructor_client_factory: Any | None = None,
        session: Any | None = None,
    ) -> None:
        super().__init__(
            task_type=task_type,
            config=config,
            client=client,
            analysis_logger=analysis_logger,
            token_usage_callback=token_usage_callback,
            novel_id=novel_id,
            session=session,
        )
        self._instructor_client_factory = instructor_client_factory
        self._emitter: Callable[[StreamEvent], Awaitable[None]] | None = None

    async def annotate_chunk(
        self,
        text: str,
        prev_summary: str | None = None,
        alias_map: dict[str, str] | None = None,
        chunk_id: int | None = None,
        global_context: str | None = None,
        active_entities: str | None = None,
        novel_title: str | None = None,
        main_characters: str | None = None,
        position_pct: float | None = None,
        chapter_id: int | None = None,
        cloud_client: AnnotationClient | None = None,
        run_id: str | None = None,
        emitter: Callable[[StreamEvent], Awaitable[None]] | None = None,
        disambig_context: str | None = None,
        evidence_bundle: EvidenceBundle | None = None,
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
            evidence_bundle=evidence_bundle,
            novel_title=novel_title,
            main_characters=main_characters,
            position_pct=position_pct,
            chapter_id=chapter_id,
            cloud_client=cloud_client,
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
            evidence_bundle=ctx.evidence_bundle,
            novel_title=ctx.novel_title,
            main_characters=ctx.main_characters,
            position_pct=ctx.position_pct,
            chapter_id=ctx.chapter_id,
            cloud_client=ctx.cloud_client,
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
    ) -> Any:
        if not self._config.model:
            raise ValueError("model is required")

        if self._client is None:
            raise ValueError("client is required")

        is_cloud = self._is_cloud_api()

        request_params: dict[str, Any] = {
            "model": self._config.model,
            "messages": messages,
            "temperature": self._config.temperature,
            "top_p": self._config.top_p,
        }

        if enable_thinking:
            request_params["reasoning_effort"] = "medium"
            request_params["extra_body"] = {"think": True}
        else:
            request_params["reasoning_effort"] = "none"
            request_params["extra_body"] = {"think": False}

        if response_model is not None:
            request_params["response_format"] = self._build_json_schema(response_model)

        active_emitter = emitter or self._emitter
        response = await self._call_api_stream(request_params, is_cloud=is_cloud, emitter=active_emitter)

        if response_model is not None:
            parsed_result = self._parse_structured_response(response, response_model)
            return parsed_result, response

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
