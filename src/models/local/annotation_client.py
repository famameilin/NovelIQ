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
- 添加 `_build_annotation_messages_v2`、`_annotate_chunk_phase1`、`_annotate_chunk_phase2`、`_build_foreshadowing_messages` 方法

修改时间: 2026-03-16
修改者: TraeAI
任务: 重构本地标注客户端集成 Instructor
修改内容:
- 集成 Instructor 实现结构化输出
- 使用 `instructor.from_litellm()` 创建客户端
- `_call_annotation_api` 方法支持 `response_model` 参数
- 简化 `_parse_annotation` 方法，Instructor 自动解析
- Phase2 伏笔分析使用 Instructor 结构化输出
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Type, TypeVar, cast

from loguru import logger

from src.config import TaskModelConfig, TaskType, settings
from src.config.analysis_logger import AnalysisLogger

from .base import BaseModelClient, TokenUsageCallback
from .litellm_utils import get_model_with_provider
from .parser import (
    build_annotation,
    extract_thinking_unified,
    make_empty_annotation,
    parse_active_entities,
    try_parse_json,
    validate_foreshadowing_result,
)
from .prompts import (
    FEW_SHOT_EXAMPLES,
    FEW_SHOT_EXAMPLES_V2,
    FORESHADOWING_EXAMPLES,
    FORESHADOWING_SYSTEM_PROMPT,
    FORESHADOWING_USER_TEMPLATE,
    FORMAT_REQUIREMENTS,
    FORMAT_REQUIREMENTS_V2,
    SYSTEM_PROMPT,
    SYSTEM_PROMPT_V2,
    USER_TEMPLATE_V2,
    build_retry_prompt,
)
from .schema import ChunkAnnotation, ForeshadowingResult
from .validator import validate_names_in_sources

T = TypeVar("T")

# 使用配置类替代魔法数字
from src.config.schemas import ANNOTATION_CONFIG
PHASE_MAX_RETRIES = ANNOTATION_CONFIG.phase_max_retries


@dataclass
class AnnotationContext:
    """
    标注上下文参数

    创建时间: 2026-03-17
    创建者: TraeAI
    任务: code-quality-refactor - 简化annotate_chunk参数
    说明: 封装annotate_chunk的多参数，减少函数签名复杂度
    """

    text: str
    prev_summary: str | None = None
    alias_map: Dict[str, str] | None = None
    chunk_id: int | None = None
    global_context: str | None = None
    prev_tail_text: str | None = None
    active_entities: str | None = None
    rag_evidence: str | None = None
    known_aliases: str | None = None
    next_preview: str | None = None
    prev_chunk_text: str | None = None
    next_chunk_text: str | None = None
    novel_title: str | None = None
    main_characters: str | None = None
    position_pct: float | None = None
    chapter_id: int | None = None
    cloud_client: "AnnotationClient | None" = None


class Phase1MaxRetriesExceededError(Exception):
    """
    Phase1重试次数耗尽异常

    创建时间: 2026-03-14
    创建者: TraeAI
    任务: Phase1/Phase2独立重试机制
    """

    pass


class NameValidationMaxRetriesExceededError(Exception):
    """
    名字验证重试次数耗尽异常

    创建时间: 2026-03-14
    创建者: TraeAI
    任务: 名字验证失败后抛异常触发云端fallback

    修改时间: 2026-03-14
    修改者: TraeAI
    任务: 简化重试逻辑
    修改内容: 添加 invalid_names 属性，方便重试时获取无效名字列表
    """

    def __init__(self, message: str, invalid_names: list[str] | None = None, bad_output: str = ""):
        super().__init__(message)
        self.invalid_names = invalid_names or []
        self.bad_output = bad_output



class Phase2MaxRetriesExceededError(Exception):
    """
    Phase2重试次数耗尽异常

    创建时间: 2026-03-14
    创建者: TraeAI
    任务: Phase1/Phase2独立重试机制
    """

    pass


@dataclass
class TwoPhaseAnnotationResult:
    """双次调用标注结果"""

    annotation: ChunkAnnotation
    foreshadowing: ForeshadowingResult | None = None


class AnnotationClient(BaseModelClient):
    """
    标注专用客户端

    负责对文本块进行语义标注，包括人物、关系、对话、事件类型等。

    修改时间: 2026-03-12
    修改者: TraeAI
    修改内容: 添加 task_type 参数支持，用于云端标注fallback

    修改时间: 2026-03-16
    修改者: TraeAI
    任务: 重构本地标注客户端集成 Instructor
    修改内容: 添加 _instructor_client 属性，使用 instructor.from_litellm() 创建客户端

    修改时间: 2026-03-16
    修改者: TraeAI
    任务: 支持依赖注入 instructor_client_factory，便于测试
    """

    def __init__(
        self,
        task_type: TaskType = "annotation",
        config: TaskModelConfig | None = None,
        client: Any | None = None,
        analysis_logger: AnalysisLogger | None = None,
        token_usage_callback: Optional[TokenUsageCallback] = None,
        novel_id: Optional[str] = None,
        instructor_client_factory: Optional[Any] = None,
    ) -> None:
        super().__init__(
            task_type=task_type,
            config=config,
            client=client,
            analysis_logger=analysis_logger,
            token_usage_callback=token_usage_callback,
            novel_id=novel_id,
        )
        self._instructor_client: Any = None
        self._instructor_client_factory = instructor_client_factory

    def _execute_single_call(
        self,
        ctx: AnnotationContext,
        messages: list[dict],
        retry_messages: list[dict] | None = None,
    ) -> tuple[ChunkAnnotation, str]:
        """
        执行单次标注调用

        创建时间: 2026-03-17
        创建者: TraeAI
        任务: code-quality-refactor - 提取_do_single_call方法
        说明: 从annotate_chunk中提取的内嵌函数，用于单次标注调用
        """
        current_messages = retry_messages if retry_messages else messages

        enable_thinking = self._config.thinking_enabled
        response = self._call_annotation_api(current_messages, enable_thinking, ctx.chunk_id)

        content_clean, thinking_content, extraction = self._process_annotation_response(
            response, self._is_cloud_api(), ctx.chunk_id, "phase1"
        )

        self._log_prompt_response(
            ctx.chunk_id, content_clean, thinking_content, extraction,
            current_messages, ctx.text, ctx.prev_summary
        )

        annotation = self._parse_annotation(content_clean)

        parsed_active_entities = parse_active_entities(ctx.active_entities)
        sources = {
            "text": ctx.text,
            "prev_tail_text": ctx.prev_tail_text or "",
            "active_entities": parsed_active_entities,
            "alias_map": ctx.alias_map or {},
            "next_preview": ctx.next_preview or "",
        }

        annotation = self._validate_annotation(annotation, sources, ctx.chunk_id, content_clean)

        self._record_token_usage(response, "single_call", ctx.chunk_id)

        return annotation, content_clean

    def _build_foreshadowing_from_annotation(
        self,
        annotation: ChunkAnnotation,
    ) -> "ForeshadowingResult | None":
        """
        从标注结果构建ForeshadowingResult

        创建时间: 2026-03-17
        创建者: TraeAI
        任务: code-quality-refactor - 提取重复代码
        说明: 单阶段模式下从annotation中提取foreshadowing数据
        """
        if hasattr(annotation, 'has_foreshadowing') and annotation.has_foreshadowing:
            return ForeshadowingResult(
                has_foreshadowing=annotation.has_foreshadowing,
                foreshadowing_type=getattr(annotation, 'foreshadowing_type', None),
                foreshadowing_desc=getattr(annotation, 'foreshadowing_desc', ''),
                confidence='medium'
            )
        return None

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
        修改者: TraeAI
        任务: code-quality-refactor - 重构annotate_chunk
        修改内容:
        - 提取_execute_single_call方法
        - 提取_build_foreshadowing_from_annotation方法
        - 简化主函数逻辑
        """
        # 构建上下文
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

        # 双阶段模式
        if settings.analysis.two_phase_annotation.enabled:
            return self._annotate_chunk_two_phase_from_context(ctx)

        # 单阶段模式
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

        修改时间: 2026-03-18
        修改者: TraeAI
        任务: code-quality-refactor - 统一重试机制
        修改内容: 使用 RetryableOperation 替换自定义重试逻辑
        """
        messages = self._build_messages(
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

        # 使用 RetryableOperation 执行带重试的调用
        from src.workflows.retry_utils import MaxRetriesExceededError, RetryableOperation

        operation = RetryableOperation(
            max_retries=PHASE_MAX_RETRIES,
            retryable_exceptions=(ConnectionError, TimeoutError),
            operation_name=f"single_call chunk_id={ctx.chunk_id}",
        )

        try:
            annotation, _ = operation.execute(self._execute_single_call, ctx, messages)
            foreshadowing = self._build_foreshadowing_from_annotation(annotation)
            return TwoPhaseAnnotationResult(annotation=annotation, foreshadowing=foreshadowing)
        except MaxRetriesExceededError:
            # 云端fallback
            if ctx.cloud_client is not None:
                logger.info("single_call local retries exhausted, trying cloud fallback chunk_id={}", ctx.chunk_id)
                try:
                    annotation, _ = ctx.cloud_client._execute_single_call(ctx, messages)
                    foreshadowing = self._build_foreshadowing_from_annotation(annotation)
                    return TwoPhaseAnnotationResult(annotation=annotation, foreshadowing=foreshadowing)
                except Exception as e:
                    raise Phase1MaxRetriesExceededError(
                        f"single_call failed after {PHASE_MAX_RETRIES} retries and cloud fallback: {str(e)}"
                    ) from e
            raise

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
        return self._annotate_chunk_two_phase(
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

    def _annotate_chunk_two_phase(
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
        双次调用标注模式

        创建时间: 2026-03-14
        创建者: TraeAI
        任务: Chunk 双次调用分析拆分

        修改时间: 2026-03-14
        修改者: TraeAI
        任务: Phase1/Phase2独立重试机制
        修改内容: 添加 cloud_client 参数传递给 Phase1/Phase2
        """
        parallel = settings.analysis.two_phase_annotation.parallel

        if parallel:
            return self._annotate_chunk_two_phase_parallel(
                text=text,
                alias_map=alias_map,
                chunk_id=chunk_id,
                prev_chunk_text=prev_chunk_text,
                next_chunk_text=next_chunk_text,
                novel_title=novel_title,
                main_characters=main_characters,
                position_pct=position_pct,
                chapter_id=chapter_id,
                active_entities=active_entities,
                cloud_client=cloud_client,
            )
        else:
            return self._annotate_chunk_two_phase_serial(
                text=text,
                alias_map=alias_map,
                chunk_id=chunk_id,
                prev_chunk_text=prev_chunk_text,
                next_chunk_text=next_chunk_text,
                novel_title=novel_title,
                main_characters=main_characters,
                position_pct=position_pct,
                chapter_id=chapter_id,
                active_entities=active_entities,
                cloud_client=cloud_client,
            )

    def _annotate_chunk_two_phase_parallel(
        self,
        text: str,
        alias_map: Dict[str, str] | None = None,
        chunk_id: int | None = None,
        prev_chunk_text: str | None = None,
        next_chunk_text: str | None = None,
        novel_title: str | None = None,
        main_characters: str | None = None,
        position_pct: float | None = None,
        chapter_id: int | None = None,
        active_entities: str | None = None,
        cloud_client: "AnnotationClient | None" = None,
    ) -> TwoPhaseAnnotationResult:
        """
        并行双次调用模式

        创建时间: 2026-03-14
        创建者: TraeAI
        任务: Chunk 双次调用分析拆分

        修改时间: 2026-03-14
        修改者: TraeAI
        任务: Phase1/Phase2独立重试机制
        修改内容: 添加 cloud_client 参数传递
        """
        logger.debug("annotate_chunk_two_phase_parallel start chunk_id={}", chunk_id)

        with ThreadPoolExecutor(max_workers=2) as executor:
            phase1_future = executor.submit(
                self._annotate_chunk_phase1,
                text=text,
                alias_map=alias_map,
                chunk_id=chunk_id,
                prev_chunk_text=prev_chunk_text,
                next_chunk_text=next_chunk_text,
                novel_title=novel_title,
                main_characters=main_characters,
                position_pct=position_pct,
                chapter_id=chapter_id,
                active_entities=active_entities,
                cloud_client=cloud_client,
            )
            phase2_future = executor.submit(
                self._annotate_chunk_phase2,
                text=text,
                prev_chunk_summary=None,
                chunk_id=chunk_id,
                prev_chunk_text=prev_chunk_text,
                next_chunk_text=next_chunk_text,
                novel_title=novel_title,
                main_characters=main_characters,
                position_pct=position_pct,
                chapter_id=chapter_id,
                cloud_client=cloud_client,
            )

            annotation = phase1_future.result()
            foreshadowing = phase2_future.result()

        if foreshadowing and validate_foreshadowing_result(foreshadowing, text):
            logger.debug(
                "annotate_chunk_two_phase_parallel found foreshadowing chunk_id={} type={}",
                chunk_id,
                foreshadowing.foreshadowing_type,
            )
        else:
            foreshadowing = None

        logger.debug("annotate_chunk_two_phase_parallel complete chunk_id={}", chunk_id)
        return TwoPhaseAnnotationResult(annotation=annotation, foreshadowing=foreshadowing)

    def _annotate_chunk_two_phase_serial(
        self,
        text: str,
        alias_map: Dict[str, str] | None = None,
        chunk_id: int | None = None,
        prev_chunk_text: str | None = None,
        next_chunk_text: str | None = None,
        novel_title: str | None = None,
        main_characters: str | None = None,
        position_pct: float | None = None,
        chapter_id: int | None = None,
        active_entities: str | None = None,
        cloud_client: "AnnotationClient | None" = None,
    ) -> TwoPhaseAnnotationResult:
        """
        串行双次调用模式

        创建时间: 2026-03-14
        创建者: TraeAI
        任务: Chunk 双次调用分析拆分

        修改时间: 2026-03-14
        修改者: TraeAI
        任务: Phase1/Phase2独立重试机制
        修改内容: 添加 cloud_client 参数传递
        """
        logger.debug("annotate_chunk_two_phase_serial start chunk_id={}", chunk_id)

        annotation = self._annotate_chunk_phase1(
            text=text,
            alias_map=alias_map,
            chunk_id=chunk_id,
            prev_chunk_text=prev_chunk_text,
            next_chunk_text=next_chunk_text,
            novel_title=novel_title,
            main_characters=main_characters,
            position_pct=position_pct,
            chapter_id=chapter_id,
            active_entities=active_entities,
            cloud_client=cloud_client,
        )

        foreshadowing = self._annotate_chunk_phase2(
            text=text,
            prev_chunk_summary=annotation.chunk_summary,
            chunk_id=chunk_id,
            prev_chunk_text=prev_chunk_text,
            next_chunk_text=next_chunk_text,
            novel_title=novel_title,
            main_characters=main_characters,
            position_pct=position_pct,
            chapter_id=chapter_id,
            cloud_client=cloud_client,
        )

        if foreshadowing and validate_foreshadowing_result(foreshadowing, text):
            logger.debug(
                "annotate_chunk_two_phase_serial found foreshadowing chunk_id={} type={}",
                chunk_id,
                foreshadowing.foreshadowing_type,
            )
        else:
            foreshadowing = None

        logger.debug("annotate_chunk_two_phase_serial complete chunk_id={}", chunk_id)
        return TwoPhaseAnnotationResult(annotation=annotation, foreshadowing=foreshadowing)

    def _execute_phase1_call(
        self,
        text: str,
        messages: list[dict],
        alias_map: Dict[str, str] | None,
        active_entities: str | None,
        prev_chunk_text: str | None,
        next_chunk_text: str | None,
        chunk_id: int | None,
        retry_messages: list[dict] | None = None,
    ) -> tuple[ChunkAnnotation, str]:
        """
        执行Phase1单次调用

        创建时间: 2026-03-17
        创建者: TraeAI
        任务: code-quality-refactor - 提取_do_phase1方法
        说明: 从_annotate_chunk_phase1中提取的内嵌函数
        """
        is_cloud = self._is_cloud_api()
        self._log_annotation_start(is_cloud, text, None, chunk_id, "phase1")

        current_messages = retry_messages if retry_messages else messages

        enable_thinking = self._config.thinking_enabled
        response = self._call_annotation_api(current_messages, enable_thinking, chunk_id)

        content_clean, thinking_content, extraction = self._process_annotation_response(
            response, is_cloud, chunk_id, "phase1"
        )

        self._log_prompt_response(
            chunk_id, content_clean, thinking_content, extraction, current_messages, text, None
        )

        result = self._parse_annotation(content_clean)

        sources = {
            "text": text,
            "prev_tail_text": prev_chunk_text or "",
            "active_entities": parse_active_entities(active_entities),
            "alias_map": alias_map or {},
            "next_preview": next_chunk_text or "",
        }

        result = self._validate_annotation(result, sources, chunk_id, content_clean)

        self._record_token_usage(response, "phase1", chunk_id)

        return result, content_clean

    def _annotate_chunk_phase1(
        self,
        text: str,
        alias_map: Dict[str, str] | None = None,
        chunk_id: int | None = None,
        prev_chunk_text: str | None = None,
        next_chunk_text: str | None = None,
        novel_title: str | None = None,
        main_characters: str | None = None,
        position_pct: float | None = None,
        chapter_id: int | None = None,
        active_entities: str | None = None,
        cloud_client: "AnnotationClient | None" = None,
    ) -> ChunkAnnotation:
        """
        第一次调用：基础标注（带独立重试机制）

        创建时间: 2026-03-14
        创建者: TraeAI
        任务: Chunk 双次调用分析拆分

        修改时间: 2026-03-17
        修改者: TraeAI
        任务: code-quality-refactor - 重构_annotate_chunk_phase1
        修改内容:
        - 提取_execute_phase1_call方法
        - 简化重试逻辑
        """
        messages = self._build_annotation_messages_v2(
            text=text,
            alias_map=alias_map,
            chunk_id=chunk_id,
            prev_chunk_text=prev_chunk_text,
            next_chunk_text=next_chunk_text,
            novel_title=novel_title,
            main_characters=main_characters,
            position_pct=position_pct,
            chapter_id=chapter_id,
            active_entities=active_entities,
        )

        # 使用重试处理器执行带重试的调用
        return self._execute_phase1_with_retry(
            text=text,
            messages=messages,
            alias_map=alias_map,
            active_entities=active_entities,
            prev_chunk_text=prev_chunk_text,
            next_chunk_text=next_chunk_text,
            chunk_id=chunk_id,
            cloud_client=cloud_client,
        )

    def _execute_phase1_with_retry(
        self,
        text: str,
        messages: list[dict],
        alias_map: Dict[str, str] | None,
        active_entities: str | None,
        prev_chunk_text: str | None,
        next_chunk_text: str | None,
        chunk_id: int | None,
        cloud_client: "AnnotationClient | None",
    ) -> ChunkAnnotation:
        """
        执行Phase1带重试的调用

        创建时间: 2026-03-17
        创建者: TraeAI
        任务: code-quality-refactor - 提取重试逻辑
        """
        last_error: Exception | None = None
        last_invalid_names: list[str] | None = None
        last_bad_output: str = ""
        content_clean: str = ""

        # 本地重试
        for attempt in range(PHASE_MAX_RETRIES):
            try:
                logger.debug("phase1 attempt {}/{} chunk_id={}", attempt + 1, PHASE_MAX_RETRIES, chunk_id)

                # 构建重试消息
                retry_messages = None
                if last_bad_output and last_invalid_names:
                    original_user_prompt = messages[-1]["content"]
                    retry_prompt = build_retry_prompt(original_user_prompt, last_bad_output, last_invalid_names)
                    retry_messages = messages[:-1] + [{"role": "user", "content": retry_prompt}]

                result, content_clean = self._execute_phase1_call(
                    text, messages, alias_map, active_entities,
                    prev_chunk_text, next_chunk_text, chunk_id, retry_messages
                )

                if attempt > 0:
                    logger.info("phase1 succeeded on attempt {} chunk_id={}", attempt + 1, chunk_id)
                return result

            except NameValidationMaxRetriesExceededError as e:
                last_error = e
                last_invalid_names = e.invalid_names
                last_bad_output = e.bad_output or content_clean
                logger.error("phase1 attempt {}/{} failed: {} chunk_id={}", attempt + 1, PHASE_MAX_RETRIES, str(e), chunk_id)
            except Exception as e:
                last_error = e
                last_invalid_names = None
                last_bad_output = content_clean
                logger.error("phase1 attempt {}/{} failed: {} chunk_id={}", attempt + 1, PHASE_MAX_RETRIES, str(e), chunk_id)

        # 云端fallback
        if cloud_client is not None:
            return self._execute_phase1_cloud_fallback(
                text, messages, alias_map, active_entities,
                prev_chunk_text, next_chunk_text, chunk_id, cloud_client,
                last_invalid_names, last_bad_output
            )

        logger.error("phase1 failed after all retries chunk_id={}: {}", chunk_id, str(last_error))
        raise Phase1MaxRetriesExceededError(f"phase1 failed after {PHASE_MAX_RETRIES} retries: {str(last_error)}")

    def _execute_phase1_cloud_fallback(
        self,
        text: str,
        messages: list[dict],
        alias_map: Dict[str, str] | None,
        active_entities: str | None,
        prev_chunk_text: str | None,
        next_chunk_text: str | None,
        chunk_id: int | None,
        cloud_client: "AnnotationClient",
        last_invalid_names: list[str] | None,
        last_bad_output: str,
    ) -> ChunkAnnotation:
        """
        执行Phase1云端fallback

        创建时间: 2026-03-17
        创建者: TraeAI
        任务: code-quality-refactor - 提取云端fallback逻辑
        """
        logger.warning("phase1 local model failed after {} attempts, falling back to cloud model chunk_id={}", PHASE_MAX_RETRIES, chunk_id)

        try:
            logger.debug("phase1 cloud attempt chunk_id={}", chunk_id)

            # 构建重试消息
            retry_messages = None
            if last_bad_output and last_invalid_names:
                original_user_prompt = messages[-1]["content"]
                retry_prompt = build_retry_prompt(original_user_prompt, last_bad_output, last_invalid_names)
                retry_messages = messages[:-1] + [{"role": "user", "content": retry_prompt}]

            result, _ = cloud_client._execute_phase1_call(
                text, messages, alias_map, active_entities,
                prev_chunk_text, next_chunk_text, chunk_id, retry_messages
            )

            logger.info("phase1 cloud succeeded chunk_id={}", chunk_id)
            return result

        except Exception as e:
            logger.error("phase1 cloud failed: {} chunk_id={}", str(e), chunk_id)
            raise Phase1MaxRetriesExceededError(f"phase1 failed after {PHASE_MAX_RETRIES} local + 1 cloud retries: {str(e)}")

    def _annotate_chunk_phase2(
        self,
        text: str,
        prev_chunk_summary: str | None = None,
        chunk_id: int | None = None,
        prev_chunk_text: str | None = None,
        next_chunk_text: str | None = None,
        novel_title: str | None = None,
        main_characters: str | None = None,
        position_pct: float | None = None,
        chapter_id: int | None = None,
        cloud_client: "AnnotationClient | None" = None,
    ) -> ForeshadowingResult | None:
        """
        第二次调用：伏笔分析（带独立重试机制）

        创建时间: 2026-03-14
        创建者: TraeAI
        任务: Chunk 双次调用分析拆分

        修改时间: 2026-03-14
        修改者: TraeAI
        任务: Phase1/Phase2独立重试机制
        修改内容: 添加独立重试逻辑，本地3次失败后云端fallback

        修改时间: 2026-03-16
        修改者: TraeAI
        任务: 重构本地标注客户端集成 Instructor
        修改内容: 使用 Instructor 结构化输出，直接返回 ForeshadowingResult
        """
        messages = self._build_foreshadowing_messages(
            text=text,
            prev_chunk_summary=prev_chunk_summary,
            chunk_id=chunk_id,
            prev_chunk_text=prev_chunk_text,
            next_chunk_text=next_chunk_text,
            novel_title=novel_title,
            main_characters=main_characters,
            position_pct=position_pct,
            chapter_id=chapter_id,
        )

        def _do_phase2(client: "AnnotationClient") -> ForeshadowingResult:
            is_cloud = client._is_cloud_api()
            client._log_annotation_start(is_cloud, text, prev_chunk_summary, chunk_id, "phase2")

            enable_thinking = client._config.thinking_enabled

            # Use the refactored _call_annotation_api
            result, response = client._call_annotation_api(
                messages=messages,
                enable_thinking=enable_thinking,
                chunk_id=chunk_id,
                response_model=ForeshadowingResult,
            )

            content_clean, thinking_content, extraction = client._process_annotation_response(response, is_cloud, chunk_id, "phase2")

            client._log_prompt_response(
                chunk_id, content_clean, thinking_content, extraction, messages, text, prev_chunk_summary
            )

            client._record_token_usage(response, "phase2", chunk_id)

            return result

        last_error: Exception | None = None
        for attempt in range(PHASE_MAX_RETRIES):
            try:
                logger.debug("phase2 attempt {}/{} chunk_id={}", attempt + 1, PHASE_MAX_RETRIES, chunk_id)
                result = _do_phase2(self)
                if attempt > 0:
                    logger.info("phase2 succeeded on attempt {} chunk_id={}", attempt + 1, chunk_id)
                return result
            except Exception as e:
                last_error = e
                logger.error("phase2 attempt {}/{} failed: {} chunk_id={}", attempt + 1, PHASE_MAX_RETRIES, str(e), chunk_id)

        if cloud_client is not None:
            logger.warning("phase2 local model failed after {} attempts, falling back to cloud model chunk_id={}", PHASE_MAX_RETRIES, chunk_id)
            try:
                logger.debug("phase2 cloud attempt chunk_id={}", chunk_id)
                result = _do_phase2(cloud_client)
                logger.info("phase2 cloud succeeded chunk_id={}", chunk_id)
                return result
            except Exception as e:
                last_error = e
                logger.error("phase2 cloud failed: {} chunk_id={}", str(e), chunk_id)

        logger.error("phase2 failed after all retries chunk_id={}: {}", chunk_id, str(last_error))
        raise Phase2MaxRetriesExceededError(f"phase2 failed after {PHASE_MAX_RETRIES} local + 1 cloud retries: {str(last_error)}")

    def _build_annotation_messages_v2(
        self,
        text: str,
        alias_map: Dict[str, str] | None = None,
        chunk_id: int | None = None,
        prev_chunk_text: str | None = None,
        next_chunk_text: str | None = None,
        novel_title: str | None = None,
        main_characters: str | None = None,
        position_pct: float | None = None,
        chapter_id: int | None = None,
        active_entities: str | None = None,
    ) -> List[dict]:
        """
        构建第一次调用（基础标注）的messages

        创建时间: 2026-03-14
        创建者: TraeAI
        任务: Chunk 双次调用分析拆分
        """
        messages = [{"role": "system", "content": SYSTEM_PROMPT_V2}]

        for example in FEW_SHOT_EXAMPLES_V2:
            messages.append({"role": "user", "content": example["user"]})
            messages.append({"role": "assistant", "content": example["assistant"]})

        alias_map_str = "{}"
        if alias_map:
            canonical_to_aliases: dict[str, list[str]] = {}
            for alias, canonical in alias_map.items():
                if canonical not in canonical_to_aliases:
                    canonical_to_aliases[canonical] = []
                canonical_to_aliases[canonical].append(alias)
            lines = []
            for canonical, aliases in canonical_to_aliases.items():
                alias_str = "、".join(aliases)
                lines.append(f"- {alias_str} → {canonical}")
            alias_map_str = "\n".join(lines)

        active_entities_str = active_entities or "[]"

        user_content = USER_TEMPLATE_V2.format(
            novel_title=novel_title or "未知",
            main_characters=main_characters or "",
            position_pct=position_pct or 0.0,
            chapter_id=chapter_id or 0,
            alias_map=alias_map_str,
            active_entities=active_entities_str,
            prev_chunk_text=prev_chunk_text or "（无前文）",
            chunk_text=text,
            next_chunk_text=next_chunk_text or "（无后文）",
        )

        user_content += "\n\n" + FORMAT_REQUIREMENTS_V2

        if chunk_id is not None:
            user_content += f"\n\n<Current_Chunk_ID>{chunk_id}</Current_Chunk_ID>"

        messages.append({"role": "user", "content": user_content})
        return messages

    def _build_foreshadowing_messages(
        self,
        text: str,
        prev_chunk_summary: str | None = None,
        chunk_id: int | None = None,
        prev_chunk_text: str | None = None,
        next_chunk_text: str | None = None,
        novel_title: str | None = None,
        main_characters: str | None = None,
        position_pct: float | None = None,
        chapter_id: int | None = None,
    ) -> List[dict]:
        """
        构建第二次调用（伏笔分析）的messages

        创建时间: 2026-03-14
        创建者: TraeAI
        任务: Chunk 双次调用分析拆分
        """
        messages = [{"role": "system", "content": FORESHADOWING_SYSTEM_PROMPT}]

        messages.append({"role": "user", "content": FORESHADOWING_EXAMPLES})

        user_content = FORESHADOWING_USER_TEMPLATE.format(
            novel_title=novel_title or "未知",
            main_characters=main_characters or "",
            position_pct=position_pct or 0.0,
            chapter_id=chapter_id or 0,
            prev_chunk_summary=prev_chunk_summary or "（无前文摘要）",
            prev_chunk_text=prev_chunk_text or "（无前文）",
            chunk_text=text,
            next_chunk_text=next_chunk_text or "（无后文）",
        )

        messages.append({"role": "user", "content": user_content})
        return messages

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

        创建时间: 2026-03-13
        创建者: TraeAI
        任务: refactor-model-interaction-layer
        说明: 从 annotate_chunk 拆分出的开始日志逻辑

        修改时间: 2026-03-17
        修改者: TraeAI
        任务: 优化云端模型日志，显示更多调用信息
        修改内容: 添加 novel_id、phase 参数到日志
        """
        if is_cloud:
            logger.info(
                "[云端模型] annotate_chunk 开始: novel_id={} chunk_id={} phase={} task_type={} model={} text_len={} thinking_enabled={}",
                self._novel_id,
                chunk_id,
                phase,
                self._task_type,
                self._config.model,
                len(text),
                self._config.thinking_enabled,
            )
        else:
            logger.debug(
                "annotate_chunk start: novel_id={} chunk_id={} phase={} task_type={} model={} text_len={} has_summary={} thinking_enabled={}",
                self._novel_id,
                chunk_id,
                phase,
                self._task_type,
                self._config.model,
                len(text),
                prev_summary is not None,
                self._config.thinking_enabled,
            )

    def _build_messages(
        self,
        text: str,
        prev_summary: str | None = None,
        alias_map: Dict[str, str] | None = None,
        global_context: str | None = None,
        prev_tail_text: str | None = None,
        active_entities: str | None = None,
        rag_evidence: str | None = None,
        known_aliases: str | None = None,
        next_preview: str | None = None,
        chunk_id: int | None = None,
    ) -> List[dict]:
        system_content = SYSTEM_PROMPT
        if global_context:
            system_content = f"{SYSTEM_PROMPT}\n\n{global_context}"
        messages = [{"role": "system", "content": system_content}]
        for example in FEW_SHOT_EXAMPLES:
            messages.append({"role": "user", "content": example["user"]})
            messages.append({"role": "assistant", "content": example["assistant"]})
        user_parts = []
        if prev_summary:
            user_parts.append(f"【前文摘要】\n{prev_summary}")
        if prev_tail_text:
            user_parts.append(f"<Previous_Context>\n{prev_tail_text}\n</Previous_Context>")
        if active_entities:
            user_parts.append(f"<Active_Entities>\n{active_entities}\n</Active_Entities>")
        if known_aliases:
            user_parts.append(known_aliases)
        if rag_evidence:
            user_parts.append(rag_evidence)
        if alias_map:
            # 修改时间: 2026-03-12
            # 修改者: TraeAI
            # 任务: 优化别名对照表格式，合并同一正式名的别名
            canonical_to_aliases: dict[str, list[str]] = {}
            for alias, canonical in alias_map.items():
                if canonical not in canonical_to_aliases:
                    canonical_to_aliases[canonical] = []
                canonical_to_aliases[canonical].append(alias)
            lines = []
            for canonical, aliases in canonical_to_aliases.items():
                alias_str = "、".join(aliases)
                lines.append(f"- {alias_str} → {canonical}")
            alias_section = "【人物别名对照表】\n" + "\n".join(lines)
            alias_section += "\n请在输出 characters[].name 时，统一使用正式名（箭头右侧的名字）。"
            user_parts.append(alias_section)
        if next_preview:
            user_parts.append(f"<Next_Preview>\n{next_preview}\n</Next_Preview>")
        user_parts.append(f"【待分析文本】\n{text}")
        user_parts.append(FORMAT_REQUIREMENTS)
        if chunk_id is not None:
            user_parts.append(f"<Current_Chunk_ID>{chunk_id}</Current_Chunk_ID>")
        user_content = "\n\n".join(user_parts)
        messages.append({"role": "user", "content": user_content})
        return messages

    def _parse_annotation(self, content: str) -> ChunkAnnotation:
        """
        解析标注结果

        修改时间: 2026-03-16
        修改者: TraeAI
        任务: 重构本地标注客户端集成 Instructor
        修改内容: 添加说明，此方法作为 fallback 使用，Instructor 会自动解析
        """
        parsed = try_parse_json(content)
        if parsed is None:
            logger.error(
                "json parse failed after all fix attempts, content preview: {}", content[:500] if content else "empty"
            )
            return make_empty_annotation()
        if not isinstance(parsed, dict):
            logger.error("annotate_chunk response not dict, got type: {}", type(parsed).__name__)
            return make_empty_annotation()
        return build_annotation(parsed)

    def _extract_names_from_annotation(self, annotation: ChunkAnnotation) -> list[str]:
        names: set[str] = set()
        for character in annotation.characters:
            if character.name:
                names.add(character.name)
        for relation in annotation.relations:
            if relation.from_name:
                names.add(relation.from_name)
            if relation.to_name:
                names.add(relation.to_name)
        for dialogue in annotation.dialogues:
            if dialogue.speaker:
                names.add(dialogue.speaker)
        return list(names)

    def _execute_validation_retry_call(
        self,
        retry_messages: list[dict],
        chunk_id: int | None,
    ) -> tuple[ChunkAnnotation, str]:
        """
        执行单次验证重试调用

        创建时间: 2026-03-17
        创建者: TraeAI
        任务: code-quality-refactor - 提取API调用逻辑
        说明: 从_retry_with_validation中提取的API调用逻辑
        """
        model_name = get_model_with_provider(self._config.model, self._config)
        if not model_name:
            raise ValueError("model is required")
        if self._client is None:
            raise ValueError("client is required")

        enable_thinking = self._config.thinking_enabled
        thinking_params = self._get_thinking_params(enable_thinking)
        extra_body = self._build_extra_body(enable_thinking)

        request_params = {
            "model": model_name,
            "messages": cast(Any, retry_messages),
            "temperature": self._config.temperature,
            "top_p": self._config.top_p,
            "presence_penalty": self._config.presence_penalty,
            "extra_body": extra_body,
        }
        request_params.update(thinking_params)

        response = self._client.chat.completions.create(**request_params)
        message = response.choices[0].message
        content = message.content or ""

        extraction = extract_thinking_unified(
            content=content,
            reasoning_content=getattr(message, "reasoning_content", None),
            support_reasoning_content=True,
            support_think_tags=True,
        )

        thinking_content = extraction.thinking_content
        content_clean = extraction.content_without_thinking

        logger.info(
            "annotate_chunk retry response: thinking_chars={} response_chars={}",
            len(thinking_content) if thinking_content else 0,
            len(content_clean),
        )

        result = self._parse_annotation(content_clean)
        return result, content_clean

    def _validate_annotation_names(
        self,
        annotation: ChunkAnnotation,
        sources: dict,
    ) -> list[str]:
        """
        验证标注结果中的名字

        创建时间: 2026-03-17
        创建者: TraeAI
        任务: code-quality-refactor - 提取名字验证逻辑
        说明: 提取名字并验证是否在有效来源中
        """
        names_in_result = self._extract_names_from_annotation(annotation)
        return validate_names_in_sources(names_in_result, sources)

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

        修改时间: 2026-03-17
        修改者: TraeAI
        任务: code-quality-refactor - 重构_retry_with_validation
        修改内容:
        - 提取_execute_validation_retry_call方法
        - 提取_validate_annotation_names方法
        - 简化主函数逻辑
        """
        result: ChunkAnnotation = make_empty_annotation()
        current_invalid_names = invalid_names
        retry_prompt = build_retry_prompt(original_user_prompt, bad_output, invalid_names)

        for retry_count in range(max_retries):
            logger.info(
                "annotate_chunk retry attempt {}/{} chunk_id={}",
                retry_count + 1,
                max_retries,
                chunk_id,
            )

            retry_messages = [{"role": "user", "content": retry_prompt}]

            try:
                result, content_clean = self._execute_validation_retry_call(
                    retry_messages, chunk_id
                )

                current_invalid_names = self._validate_annotation_names(result, sources)

                if not current_invalid_names:
                    logger.info(
                        "annotate_chunk retry succeeded on attempt {} chunk_id={}",
                        retry_count + 1,
                        chunk_id,
                    )
                    return result, []

                logger.warning(
                    "annotate_chunk retry {} still has invalid names: {} chunk_id={}",
                    retry_count + 1,
                    current_invalid_names,
                    chunk_id,
                )

                retry_prompt = build_retry_prompt(
                    original_user_prompt, content_clean, current_invalid_names
                )

            except Exception as e:
                logger.error(
                    "annotate_chunk retry {} failed with error: {} chunk_id={}",
                    retry_count + 1,
                    str(e),
                    chunk_id,
                )

        return result, current_invalid_names

    # _get_instructor_client 方法已移除（返回None的废弃方法）
    # _build_json_schema 方法已移至 BaseModelClient 基类
    # 创建时间: 2026-03-17
    # 修改者: TraeAI
    # 任务: code-quality-refactor - 清理注释代码

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
        说明: 从 annotate_chunk 拆分出的API调用逻辑

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

        # use_stream 检查已移至调用方，此处不再需要
        # use_stream = self._should_use_stream()

        if self._client is None:
            raise ValueError("client is required")
        
        request_params: dict[str, Any] = {
            "model": model_name,
            "messages": cast(Any, messages),
            "temperature": self._config.temperature,
            "top_p": self._config.top_p,
            "presence_penalty": self._config.presence_penalty,
            "extra_body": extra_body,
        }
        
        if response_model is not None:
            request_params["response_format"] = self._build_json_schema(response_model)
        
        request_params.update(thinking_params)
        
        # 默认使用流式模式，传入 is_cloud 参数控制控制台输出
        is_cloud = self._is_cloud_api()
        response = self._call_annotation_api_stream(request_params, is_cloud=is_cloud)
        
        if response_model is not None:
            parsed_result = self._parse_structured_response(response, response_model)
            return parsed_result, response
        
        return response

    def _parse_structured_response(self, response: Any, response_model: Type[T]) -> T:
        """
        解析结构化响应

        创建时间: 2026-03-17
        创建者: TraeAI
        任务: 移除 Instructor 依赖
        说明: 从响应中提取 JSON 并解析为 Pydantic 模型
        """
        if not response.choices:
            raise ValueError("Empty response from API")
        
        content = response.choices[0].message.content
        if not content:
            raise ValueError("Empty content in response")
        
        # 确保 content 是字符串类型
        if not isinstance(content, str):
            raise ValueError(f"Content must be a string, got {type(content).__name__}")
        
        json_data = try_parse_json(content)
        if json_data is None:
            raise ValueError(f"Failed to parse JSON from response: {content[:200]}")

        return response_model.model_validate(json_data)

    # _parse_structured_response, _call_annotation_api_stream, _build_stream_response
    # 方法已移至 BaseModelClient 基类
    # 创建时间: 2026-03-17
    # 修改者: TraeAI
    # 任务: code-quality-refactor - 提取API调用基类

    def _should_use_stream(self) -> bool:
        """
        判断是否应该使用流式响应模式

        创建时间: 2026-03-16
        创建者: TraeAI
        任务: 启用云端Stream模式
        说明: 根据配置和是否为云端API决定是否使用流式模式
        """
        if not self._config.stream_enabled:
            return False
        
        is_cloud = self._is_cloud_api()
        if self._config.stream_cloud_only and not is_cloud:
            return False
        
        return True

    # _call_annotation_api_stream, _build_stream_response 方法已移至 BaseModelClient 基类
    # 创建时间: 2026-03-17
    # 修改者: TraeAI
    # 任务: code-quality-refactor - 提取API调用基类

    def _call_annotation_api_stream(self, request_params: dict[str, Any], is_cloud: bool = False) -> Any:
        """
        流式API调用 - 使用基类方法

        创建时间: 2026-03-16
        修改时间: 2026-03-17
        修改者: TraeAI
        任务: code-quality-refactor - 使用基类 _call_api_stream 方法
        """
        return self._call_api_stream(request_params, is_cloud)

    # _build_stream_response 方法已移至 BaseModelClient 基类
    # 创建时间: 2026-03-17
    # 修改者: TraeAI
    # 任务: code-quality-refactor - 提取API调用基类

    def _process_annotation_response(
        self,
        response: Any,
        is_cloud: bool,
        chunk_id: int | None = None,
        phase: str = "",
    ) -> tuple[str, str | None, Any]:
        """
        封装响应处理和thinking提取

        创建时间: 2026-03-13
        创建者: TraeAI
        任务: refactor-model-interaction-layer
        说明: 从 annotate_chunk 拆分出的响应处理逻辑

        修改时间: 2026-03-17
        修改者: TraeAI
        任务: 优化云端模型日志，显示更多调用信息
        修改内容: 添加 chunk_id、phase、novel_id 参数到日志

        返回: (content_clean, thinking_content, extraction)
        """
        message = response.choices[0].message
        content = message.content or ""
        reasoning_content = getattr(message, "reasoning_content", None)

        extraction = extract_thinking_unified(
            content=content,
            reasoning_content=reasoning_content,
            support_reasoning_content=True,
            support_think_tags=True,
        )

        thinking_content = extraction.thinking_content
        content_clean = extraction.content_without_thinking

        has_thinking = bool(thinking_content and thinking_content.strip())
        has_response = bool(content_clean and content_clean.strip())

        if is_cloud:
            logger.info(
                "[云端模型] annotate_chunk 响应: novel_id={} chunk_id={} phase={} has_thinking={} thinking_chars={} has_response={} response_chars={}",
                self._novel_id,
                chunk_id,
                phase,
                has_thinking,
                len(thinking_content) if thinking_content else 0,
                has_response,
                len(content_clean),
            )
        else:
            logger.info(
                "annotate_chunk response: novel_id={} chunk_id={} phase={} has_thinking={} thinking_chars={} has_response={} response_chars={}",
                self._novel_id,
                chunk_id,
                phase,
                has_thinking,
                len(thinking_content) if thinking_content else 0,
                has_response,
                len(content_clean),
            )
            logger.debug(
                "annotate_chunk response received: novel_id={} chunk_id={} phase={} chars={} thinking_chars={} thinking_format={}",
                self._novel_id,
                chunk_id,
                phase,
                len(content_clean),
                len(thinking_content) if thinking_content else 0,
                extraction.thinking_format,
            )

        return content_clean, thinking_content, extraction

    def _validate_annotation(
        self,
        result: ChunkAnnotation,
        sources: dict,
        chunk_id: int | None,
        content_clean: str = "",
    ) -> ChunkAnnotation:
        """
        验证标注结果中的人名是否在原文中出现

        创建时间: 2026-03-14
        创建者: TraeAI
        任务: 简化重试逻辑
        说明: 只验证，不重试。验证失败直接抛异常

        修改时间: 2026-03-16
        修改者: TraeAI
        修改内容: 添加 content_clean 参数，在异常中包含原始输出
        """
        names_in_result = self._extract_names_from_annotation(result)
        invalid_names = validate_names_in_sources(names_in_result, sources)

        if invalid_names:
            logger.error(
                "annotate_chunk found invalid names: {} chunk_id={}",
                invalid_names,
                chunk_id,
            )
            raise NameValidationMaxRetriesExceededError(
                f"名字验证失败: {invalid_names}",
                invalid_names=invalid_names,
                bad_output=content_clean,
            )

        return result

    def _validate_and_retry_annotation(
        self,
        result: ChunkAnnotation,
        original_user_prompt: str,
        content_clean: str,
        sources: dict,
        chunk_id: int | None,
    ) -> ChunkAnnotation:
        """
        封装验证逻辑

        创建时间: 2026-03-13
        创建者: TraeAI
        任务: refactor-model-interaction-layer
        说明: 从 annotate_chunk 拆分出的验证和重试逻辑

        修改时间: 2026-03-14
        修改者: TraeAI
        任务: 名字验证失败后抛异常触发云端fallback
        修改内容: 移除内部重试，验证失败直接抛异常
        """
        names_in_result = self._extract_names_from_annotation(result)
        invalid_names = validate_names_in_sources(names_in_result, sources)

        if invalid_names:
            logger.error(
                "annotate_chunk found invalid names: {} chunk_id={}",
                invalid_names,
                chunk_id,
            )
            raise NameValidationMaxRetriesExceededError(
                f"Name validation failed for chunk_id={chunk_id}: {invalid_names}"
            )

        return result

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

        创建时间: 2026-03-13
        创建者: TraeAI
        任务: refactor-model-interaction-layer
        说明: 从 annotate_chunk 拆分出的prompt/response日志记录逻辑
        """
        if not self._analysis_logger:
            return

        metadata = {
            "model": self._config.model,
            "task_type": self._task_type,
            "text_len": len(text),
            "has_summary": prev_summary is not None,
        }
        if thinking_content:
            metadata["thinking_content"] = thinking_content
            metadata["thinking_format"] = extraction.thinking_format
            metadata["thinking_tokens"] = extraction.thinking_tokens
        self._analysis_logger.log_prompt(
            messages=messages,
            response=content_clean,
            metadata=metadata,
            chunk_id=chunk_id,
        )

    def _log_annotation_result(
        self,
        chunk_id: int | None,
        result: ChunkAnnotation,
        content_clean: str,
        thinking_content: str | None,
        extraction: Any,
    ) -> None:
        """
        封装标注结果日志记录

        创建时间: 2026-03-13
        创建者: TraeAI
        任务: refactor-model-interaction-layer
        说明: 从 annotate_chunk 拆分出的标注结果日志记录逻辑
        """
        if not self._analysis_logger:
            return

        annotation_metadata = {}
        if thinking_content:
            annotation_metadata["thinking_content"] = thinking_content
            annotation_metadata["thinking_format"] = extraction.thinking_format
        self._analysis_logger.log_annotation(
            chunk_id=chunk_id or 0,
            annotation=result.to_dict(),
            raw_response=content_clean,
            metadata=annotation_metadata,
        )
