"""
创建时间: 2026-03-12
创建者: TraeAI
任务: 项目文件结构整理与拆解 - 从 unified_client.py 拆分标注专用客户端

本模块包含文本标注相关的模型客户端，负责对文本块进行语义标注。

修改时间: 2026-03-14
修改者: TraeAI
任务: Chunk 双次调用分析拆分
修改内容:
- 添加双次调用模式支持（第一次：基础标注，第二次：伏笔分析）
- 添加并行和串行两种执行模式

修改时间: 2026-03-16
修改者: TraeAI
任务: 重构本地标注客户端集成 Instructor
修改内容:
- 集成 Instructor 实现结构化输出
- `_call_annotation_api` 方法支持 `response_model` 参数

修改时间: 2026-03-18
修改者: TraeAI
任务: code-quality-refactor - Task 9 拆分annotation_client
修改内容:
- 将数据类和异常移至 annotation/context.py
- 将Phase1逻辑移至 annotation/phase1.py
- 将Phase2逻辑移至 annotation/phase2.py
- 将双阶段逻辑移至 annotation/two_phase.py
- 将API调用相关逻辑移至 annotation/api_call.py
- 移除未使用的委托方法，简化代码
- 移除未使用的方法（_get_instructor_client, _should_use_stream, _validate_and_retry_annotation）
- 为委托方法添加 @deprecated 装饰器
"""

from __future__ import annotations

import warnings
from typing import Any, Dict, List, Type, TypeVar

from loguru import logger

from src.config import TaskModelConfig, TaskType, settings
from src.config.analysis_logger import AnalysisLogger

from .annotation import (
    PHASE_MAX_RETRIES,
    AnnotationContext,
    NameValidationMaxRetriesExceededError,
    Phase1MaxRetriesExceededError,
    Phase2MaxRetriesExceededError,
    TwoPhaseAnnotationResult,
    _build_messages,
    execute_validation_retry_call,
    extract_names_from_annotation,
    log_annotation_result,
    log_annotation_start as _log_annotation_start_impl,
    log_prompt_response,
    parse_annotation as _parse_annotation_impl,
    process_annotation_response,
    validate_annotation as _validate_annotation_impl,
)
from .annotation.two_phase import annotate_chunk_two_phase as _annotate_chunk_two_phase_impl
from .base import BaseModelClient, TokenUsageCallback
from .litellm_utils import get_model_with_provider
from .schema import ChunkAnnotation, ForeshadowingResult
from .validator import validate_names_in_sources

T = TypeVar("T")


def _deprecated(message: str):
    """
    弃用装饰器

    创建时间: 2026-03-18
    创建者: TraeAI
    任务: code-quality-refactor - 为委托方法添加弃用警告
    """
    def decorator(func):
        def wrapper(*args, **kwargs):
            warnings.warn(
                f"{func.__name__} is deprecated: {message}",
                DeprecationWarning,
                stacklevel=2
            )
            return func(*args, **kwargs)
        wrapper.__name__ = func.__name__
        wrapper.__doc__ = func.__doc__
        return wrapper
    return decorator


class AnnotationClient(BaseModelClient):
    """
    标注客户端

    提供文本块的语义标注功能，支持单阶段和双阶段标注模式。

    修改时间: 2026-03-18
    修改者: TraeAI
    任务: code-quality-refactor - Task 9 拆分annotation_client
    修改内容: 将核心逻辑委托给子模块函数，移除未使用的方法
    """

    def __init__(
        self,
        config: TaskModelConfig | None = None,
        client: Any | None = None,
        analysis_logger: AnalysisLogger | None = None,
        token_usage_callback: TokenUsageCallback | None = None,
        novel_id: str | None = None,
    ) -> None:
        """
        初始化标注客户端

        创建时间: 2026-03-12
        创建者: TraeAI
        任务: 项目文件结构整理与拆解 - 从 unified_client.py 拆分标注专用客户端
        """
        super().__init__(
            task_type=TaskType.ANNOTATE,
            config=config,
            client=client,
            analysis_logger=analysis_logger,
            token_usage_callback=token_usage_callback,
            novel_id=novel_id,
        )

    def _execute_single_call(
        self,
        ctx: AnnotationContext,
        messages: list[dict],
    ) -> tuple[ChunkAnnotation, Any]:
        """
        执行单次标注调用

        创建时间: 2026-03-17
        创建者: TraeAI
        任务: code-quality-refactor - 提取单次调用逻辑
        """
        is_cloud = self._is_cloud_api()
        enable_thinking = self._config.thinking_enabled
        response = self._call_annotation_api(messages, enable_thinking, ctx.chunk_id)

        content_clean, thinking_content, extraction = self._process_annotation_response(
            response, is_cloud, ctx.chunk_id, "single_call"
        )

        self._log_prompt_response(
            ctx.chunk_id, content_clean, thinking_content, extraction, messages, ctx.text, ctx.prev_summary
        )

        result = self._parse_annotation(content_clean)

        sources = {
            "text": ctx.text,
            "prev_tail_text": ctx.prev_tail_text or "",
            "active_entities": [],
            "alias_map": ctx.alias_map or {},
            "next_preview": ctx.next_preview or "",
        }

        result = self._validate_annotation(result, sources, ctx.chunk_id, content_clean)

        self._record_token_usage(response, "single_call", ctx.chunk_id)

        return result, response

    def _build_foreshadowing_from_annotation(
        self,
        annotation: ChunkAnnotation,
    ) -> ForeshadowingResult | None:
        """
        从标注结果构建伏笔分析结果

        创建时间: 2026-03-17
        创建者: TraeAI
        任务: code-quality-refactor - 提取伏笔构建逻辑
        """
        if not annotation.has_foreshadowing:
            return None

        return ForeshadowingResult(
            has_foreshadowing=True,
            foreshadowing_type=annotation.foreshadowing_type,
            anchor_text="",
            anchor_reason=annotation.foreshadowing_desc or "",
            confidence="high",
        )

    def annotate_chunk(
        self,
        text: str,
        prev_summary: str | None = None,
        alias_map: Dict[str, str] | None = None,
        chunk_id: int | None = None,
        global_context: str | None = None,
        prev_tail_text: str | None = None,
        active_entities: str | None = None,
        rag_evidence: str | None = None,
        known_aliases: str | None = None,
        next_preview: str | None = None,
        prev_chunk_text: str | None = None,
        next_chunk_text: str | None = None,
        novel_title: str | None = None,
        main_characters: str | None = None,
        position_pct: float | None = None,
        chapter_id: int | None = None,
        cloud_client: "AnnotationClient | None" = None,
    ) -> TwoPhaseAnnotationResult:
        """
        对文本块进行语义标注

        修改时间: 2026-03-17
        创建者: TraeAI
        任务: code-quality-refactor - 重构annotate_chunk
        修改内容:
        - 提取_execute_single_call方法
        - 提取_build_foreshadowing_from_annotation方法
        - 简化主函数逻辑
        """
        ctx = AnnotationContext(
            text=text,
            prev_summary=prev_summary,
            alias_map=alias_map,
            chunk_id=chunk_id,
            global_context=global_context,
            prev_tail_text=prev_tail_text,
            active_entities=active_entities,
            rag_evidence=rag_evidence,
            known_aliases=known_aliases,
            next_preview=next_preview,
            prev_chunk_text=prev_chunk_text,
            next_chunk_text=next_chunk_text,
            novel_title=novel_title,
            main_characters=main_characters,
            position_pct=position_pct,
            chapter_id=chapter_id,
            cloud_client=cloud_client,
        )

        if settings.analysis.two_phase_annotation.enabled:
            return self._annotate_chunk_two_phase_from_context(ctx)

        return self._annotate_single_call_with_retry(ctx)

    def _annotate_single_call_with_retry(
        self,
        ctx: AnnotationContext,
    ) -> TwoPhaseAnnotationResult:
        """
        单次标注调用（带重试）

        创建时间: 2026-03-17
        创建者: TraeAI
        任务: code-quality-refactor - 提取单次调用逻辑
        """
        messages = _build_messages(
            ctx.text,
            ctx.prev_summary,
            ctx.alias_map,
            ctx.global_context,
            ctx.prev_tail_text,
            ctx.active_entities,
            ctx.rag_evidence,
            ctx.known_aliases,
            ctx.next_preview,
            ctx.chunk_id,
        )

        is_cloud = self._is_cloud_api()
        self._log_annotation_start(is_cloud, ctx.text, ctx.prev_summary, ctx.chunk_id, "single_call")

        last_error: Exception | None = None
        for attempt in range(PHASE_MAX_RETRIES):
            try:
                annotation, _ = self._execute_single_call(ctx, messages)
                foreshadowing = self._build_foreshadowing_from_annotation(annotation)
                return TwoPhaseAnnotationResult(annotation=annotation, foreshadowing=foreshadowing)
            except Exception as e:
                last_error = e
                logger.error(
                    "single_call attempt {}/{} failed: {} chunk_id={}",
                    attempt + 1, PHASE_MAX_RETRIES, str(e), ctx.chunk_id
                )

        if ctx.cloud_client is not None:
            try:
                annotation, _ = ctx.cloud_client._execute_single_call(ctx, messages)
                foreshadowing = self._build_foreshadowing_from_annotation(annotation)
                return TwoPhaseAnnotationResult(annotation=annotation, foreshadowing=foreshadowing)
            except Exception as e:
                last_error = e

        raise Phase1MaxRetriesExceededError(
            f"single_call failed after {PHASE_MAX_RETRIES} retries: {str(last_error)}"
        )

    def _annotate_chunk_two_phase_from_context(
        self,
        ctx: AnnotationContext,
    ) -> TwoPhaseAnnotationResult:
        """
        双阶段标注（从上下文）

        创建时间: 2026-03-17
        修改者: TraeAI
        任务: code-quality-refactor - 提取双阶段调用逻辑
        """
        return _annotate_chunk_two_phase_impl(
            client=self,
            text=ctx.text,
            prev_summary=ctx.prev_summary,
            alias_map=ctx.alias_map,
            chunk_id=ctx.chunk_id,
            global_context=ctx.global_context,
            prev_tail_text=ctx.prev_tail_text,
            active_entities=ctx.active_entities,
            rag_evidence=ctx.rag_evidence,
            known_aliases=ctx.known_aliases,
            next_preview=ctx.next_preview,
            prev_chunk_text=ctx.prev_chunk_text,
            next_chunk_text=ctx.next_chunk_text,
            novel_title=ctx.novel_title,
            main_characters=ctx.main_characters,
            position_pct=ctx.position_pct,
            chapter_id=ctx.chapter_id,
            cloud_client=ctx.cloud_client,
        )

    @_deprecated("use src.models.local.annotation.api_call.log_annotation_start instead")
    def _log_annotation_start(
        self,
        is_cloud: bool,
        text: str,
        prev_summary: str | None,
        chunk_id: int | None,
        phase: str = "",
    ) -> None:
        """
        封装标注开始日志

        .. deprecated::
            使用 src.models.local.annotation.api_call.log_annotation_start 代替

        创建时间: 2026-03-13
        创建者: TraeAI
        任务: refactor-model-interaction-layer

        修改时间: 2026-03-18
        修改者: TraeAI
        任务: code-quality-refactor - Task 9 拆分annotation_client
        修改内容: 委托给 annotation/api_call.py
        """
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

    @_deprecated("use src.models.local.annotation.api_call.parse_annotation instead")
    def _parse_annotation(self, content: str) -> ChunkAnnotation:
        """
        解析标注结果

        .. deprecated::
            使用 src.models.local.annotation.api_call.parse_annotation 代替

        修改时间: 2026-03-16
        创建者: TraeAI
        任务: 重构本地标注客户端集成 Instructor

        修改时间: 2026-03-18
        修改者: TraeAI
        任务: code-quality-refactor - Task 9 拆分annotation_client
        修改内容: 委托给 annotation/api_call.py
        """
        return _parse_annotation_impl(content, None)

    @_deprecated("use src.models.local.annotation.api_call.extract_names_from_annotation instead")
    def _extract_names_from_annotation(self, annotation: ChunkAnnotation) -> list[str]:
        """
        从标注结果中提取所有名字

        .. deprecated::
            使用 src.models.local.annotation.api_call.extract_names_from_annotation 代替

        创建时间: 2026-03-18
        修改者: TraeAI
        任务: code-quality-refactor - Task 9 拆分annotation_client
        修改内容: 委托给 annotation/api_call.py
        """
        return extract_names_from_annotation(annotation)

    @_deprecated("use src.models.local.annotation.api_call.execute_validation_retry_call instead")
    def _execute_validation_retry_call(
        self,
        retry_messages: list[dict],
        chunk_id: int | None,
    ) -> tuple[ChunkAnnotation, str]:
        """
        执行单次验证重试调用

        .. deprecated::
            使用 src.models.local.annotation.api_call.execute_validation_retry_call 代替

        创建时间: 2026-03-17
        创建者: TraeAI
        任务: code-quality-refactor - 提取API调用逻辑

        修改时间: 2026-03-18
        修改者: TraeAI
        任务: code-quality-refactor - Task 9 拆分annotation_client
        修改内容: 委托给 annotation/api_call.py
        """
        return execute_validation_retry_call(
            client=self,
            retry_messages=retry_messages,
            chunk_id=chunk_id,
            config=self._config,
            parse_annotation_func=self._parse_annotation,
        )

    @_deprecated("use src.models.local.validator.validate_names_in_sources directly instead")
    def _validate_annotation_names(
        self,
        annotation: ChunkAnnotation,
        sources: dict,
    ) -> list[str]:
        """
        验证标注结果中的名字

        .. deprecated::
            使用 src.models.local.validator.validate_names_in_sources 直接调用代替

        创建时间: 2026-03-17
        创建者: TraeAI
        任务: code-quality-refactor - 提取名字验证逻辑

        修改时间: 2026-03-18
        修改者: TraeAI
        任务: code-quality-refactor - Task 9 拆分annotation_client
        修改内容: 使用 annotation/api_call.py 中的函数
        """
        names_in_result = self._extract_names_from_annotation(annotation)
        return validate_names_in_sources(names_in_result, sources)

    @_deprecated("use src.models.local.annotation.validation.retry_with_validation instead")
    def _retry_with_validation(
        self,
        original_user_prompt: str,
        bad_output: str,
        invalid_names: list[str],
        sources: dict,
        chunk_id: int | None,
        max_retries: int,
    ) -> tuple[ChunkAnnotation, list[str]]:
        """
        名字验证失败后的内部重试

        .. deprecated::
            使用 src.models.local.annotation.validation.retry_with_validation 代替

        修改时间: 2026-03-17
        创建者: TraeAI
        任务: code-quality-refactor - 重构_retry_with_validation

        修改时间: 2026-03-18
        修改者: TraeAI
        任务: code-quality-refactor - Task 9 拆分annotation_client
        修改内容: 委托给 annotation/validation.py
        """
        from src.models.local.annotation.validation import retry_with_validation

        return retry_with_validation(
            original_user_prompt=original_user_prompt,
            bad_output=bad_output,
            invalid_names=invalid_names,
            sources=sources,
            chunk_id=chunk_id,
            max_retries=max_retries,
            execute_retry_call_func=self._execute_validation_retry_call,
            validate_names_func=self._validate_annotation_names,
        )

    def _call_annotation_api(
        self,
        messages: List[dict],
        enable_thinking: bool,
        chunk_id: int | None,
        response_model: Type[T] | None = None,
    ) -> Any:
        """
        封装API调用逻辑

        创建时间: 2026-03-13
        创建者: TraeAI
        任务: refactor-model-interaction-layer

        修改时间: 2026-03-16
        修改者: TraeAI
        任务: 重构本地标注客户端集成 Instructor
        修改内容: 
        1. 添加 response_model 参数支持结构化输出
        2. 添加模型名称 provider 前缀处理
        
        修改时间: 2026-03-16
        修改者: TraeAI
        任务: 修复thinking参数传递方式
        修改内容:
        1. 将thinking参数作为顶级参数传递
        2. 添加timeout参数支持
        
        修改时间: 2026-03-16
        修改者: TraeAI
        任务: 启用云端Stream模式
        修改内容: 添加流式响应模式支持

        修改时间: 2026-03-17
        修改者: TraeAI
        任务: 移除 Instructor 依赖
        修改内容: 使用 LiteLLM 的 JSON Schema 模式替代 Instructor
        """
        if not self._config.model:
            raise ValueError("model is required")

        model_name = get_model_with_provider(self._config.model, self._config)
        thinking_params = self._get_thinking_params(enable_thinking)
        extra_body = self._build_extra_body(enable_thinking)

        if self._client is None:
            raise ValueError("client is required")
        
        request_params: dict[str, Any] = {
            "model": model_name,
            "messages": messages,
            "temperature": self._config.temperature,
            "top_p": self._config.top_p,
            "presence_penalty": self._config.presence_penalty,
            "extra_body": extra_body,
        }
        
        if response_model is not None:
            request_params["response_format"] = self._build_json_schema(response_model)
        
        request_params.update(thinking_params)
        
        is_cloud = self._is_cloud_api()
        response = self._call_api_stream(request_params, is_cloud=is_cloud)
        
        if response_model is not None:
            parsed_result = self._parse_structured_response(response, response_model)
            return parsed_result, response
        
        return response

    @_deprecated("use src.models.local.annotation.response.process_annotation_response instead")
    def _process_annotation_response(
        self,
        response: Any,
        is_cloud: bool,
        chunk_id: int | None = None,
        phase: str = "",
    ) -> tuple[str, str | None, Any]:
        """
        封装响应处理和thinking提取

        .. deprecated::
            使用 src.models.local.annotation.response.process_annotation_response 代替

        创建时间: 2026-03-13
        创建者: TraeAI
        任务: refactor-model-interaction-layer

        修改时间: 2026-03-18
        修改者: TraeAI
        任务: code-quality-refactor - Task 9 拆分annotation_client
        修改内容: 委托给 annotation/response.py
        """
        return process_annotation_response(
            response=response,
            is_cloud=is_cloud,
            novel_id=self._novel_id,
            chunk_id=chunk_id,
            phase=phase,
        )

    @_deprecated("use src.models.local.annotation.api_call.validate_annotation instead")
    def _validate_annotation(
        self,
        result: ChunkAnnotation,
        sources: dict,
        chunk_id: int | None,
        content_clean: str = "",
    ) -> ChunkAnnotation:
        """
        验证标注结果中的人名是否在原文中出现

        .. deprecated::
            使用 src.models.local.annotation.api_call.validate_annotation 代替

        创建时间: 2026-03-14
        创建者: TraeAI
        任务: 简化重试逻辑

        修改时间: 2026-03-18
        修改者: TraeAI
        任务: code-quality-refactor - Task 9 拆分annotation_client
        修改内容: 委托给 annotation/api_call.py
        """
        return _validate_annotation_impl(result, sources, chunk_id, content_clean)

    @_deprecated("use src.models.local.annotation.response.log_prompt_response instead")
    def _log_prompt_response(
        self,
        chunk_id: int | None,
        content_clean: str,
        thinking_content: str | None,
        extraction: Any,
        messages: List[dict],
        text: str,
        prev_summary: str | None,
    ) -> None:
        """
        封装prompt和response日志记录

        .. deprecated::
            使用 src.models.local.annotation.response.log_prompt_response 代替

        创建时间: 2026-03-13
        创建者: TraeAI
        任务: refactor-model-interaction-layer

        修改时间: 2026-03-18
        修改者: TraeAI
        任务: code-quality-refactor - Task 9 拆分annotation_client
        修改内容: 委托给 annotation/response.py
        """
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

    @_deprecated("use src.models.local.annotation.response.log_annotation_result instead")
    def _log_annotation_result(
        self,
        chunk_id: int | None,
        result: Any,
        content_clean: str,
        thinking_content: str | None,
        extraction: Any,
    ) -> None:
        """
        封装标注结果日志记录

        .. deprecated::
            使用 src.models.local.annotation.response.log_annotation_result 代替

        创建时间: 2026-03-13
        创建者: TraeAI
        任务: refactor-model-interaction-layer

        修改时间: 2026-03-18
        修改者: TraeAI
        任务: code-quality-refactor - Task 9 拆分annotation_client
        修改内容: 委托给 annotation/response.py
        """
        log_annotation_result(
            analysis_logger=self._analysis_logger,
            chunk_id=chunk_id,
            result=result,
            content_clean=content_clean,
            thinking_content=thinking_content,
            extraction=extraction,
        )
