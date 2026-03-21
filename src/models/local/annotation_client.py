"""
AnnotationClient 模块

创建时间: 2026-03-12
创建者: TraeAI
任务: 项目文件结构整理与拆解 - 从 unified_client.py 拆分标注专用客户端

修改历史:
- 2026-03-14: 添加双次调用模式支持（第一次：基础标注，第二次：伏笔分析）
- 2026-03-16: 集成 Instructor 实现结构化输出
- 2026-03-18: 拆分核心逻辑到 annotation/ 子包，简化此类

说明:
- 此类现在主要作为协调器，核心逻辑已移至 src.models.local.annotation 子包
"""

from __future__ import annotations

from typing import Any, Dict, List, Type, TypeVar

from src.config import TaskModelConfig, TaskType
from src.config.analysis_logger import AnalysisLogger

from .annotation import (
    AnnotationContext,
    TwoPhaseAnnotationResult,
    log_annotation_start as _log_annotation_start_impl,
    log_prompt_response,
    parse_annotation as _parse_annotation_impl,
    process_annotation_response,
    validate_annotation as _validate_annotation_impl,
)
from pydantic import BaseModel

from .annotation.two_phase import annotate_chunk_two_phase as _annotate_chunk_two_phase_impl
from .base import BaseModelClient, TokenUsageCallback
from .schema import ChunkAnnotation

T = TypeVar("T", bound=BaseModel)


class AnnotationClient(BaseModelClient):
    """
    标注客户端

    提供文本块的语义标注功能，支持单阶段和双阶段标注模式。

    修改时间: 2026-03-18
    修改者: TraeAI
    任务: code-quality-refactor - Task 8 拆分annotation_client
    修改内容: 将核心逻辑委托给子模块函数
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
        """
        初始化标注客户端

        创建时间: 2026-03-12
        创建者: TraeAI
        任务: 项目文件结构整理与拆解 - 从 unified_client.py 拆分标注专用客户端

        修改时间: 2026-03-18
        修改者: TraeAI
        任务: code-quality-refactor - 修复与 UnifiedModelClient 的兼容性
        修改内容: 添加 task_type 和 instructor_client_factory 参数

        修改时间: 2026-03-19
        修改者: TraeAI
        任务: 支持传入 session 用于保存模型交互记录
        修改内容: 添加 session 参数
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
        self._instructor_client_factory = instructor_client_factory

    def annotate_chunk(
        self,
        text: str,
        prev_summary: str | None = None,
        alias_map: Dict[str, str] | None = None,
        chunk_id: int | None = None,
        global_context: str | None = None,
        prev_chunk_text: str | None = None,
        active_entities: str | None = None,
        rag_evidence: str | None = None,
        known_aliases: str | None = None,
        next_chunk_text: str | None = None,
        novel_title: str | None = None,
        main_characters: str | None = None,
        position_pct: float | None = None,
        chapter_id: int | None = None,
        cloud_client: "AnnotationClient | None" = None,
        run_id: str | None = None,
        character_appearances: List[dict] | None = None,
    ) -> TwoPhaseAnnotationResult:
        """
        对文本块进行语义标注

        修改时间: 2026-03-19
        创建者: TraeAI
        任务: 统一字段命名，添加 run_id 支持
        修改内容: 移除 prev_tail_text 和 next_preview，统一使用 prev_chunk_text 和 next_chunk_text，添加 run_id

        修改时间: 2026-03-21
        创建者: TraeAI
        任务: fix-validate-names-from-character-appearances
        修改内容: 添加 character_appearances 参数支持
        """
        ctx = AnnotationContext(
            text=text,
            prev_summary=prev_summary,
            alias_map=alias_map,
            chunk_id=chunk_id,
            global_context=global_context,
            prev_chunk_text=prev_chunk_text,
            active_entities=active_entities,
            rag_evidence=rag_evidence,
            known_aliases=known_aliases,
            next_chunk_text=next_chunk_text,
            novel_title=novel_title,
            main_characters=main_characters,
            position_pct=position_pct,
            chapter_id=chapter_id,
            cloud_client=cloud_client,
            run_id=run_id,
            character_appearances=character_appearances,
        )

        return _annotate_chunk_two_phase_impl(
                client=self,
                text=ctx.text,
                prev_summary=ctx.prev_summary,
                alias_map=ctx.alias_map,
                chunk_id=ctx.chunk_id,
                global_context=ctx.global_context,
                prev_chunk_text=ctx.prev_chunk_text,
                active_entities=ctx.active_entities,
                rag_evidence=ctx.rag_evidence,
                known_aliases=ctx.known_aliases,
                next_chunk_text=ctx.next_chunk_text,
                novel_title=ctx.novel_title,
                main_characters=ctx.main_characters,
                position_pct=ctx.position_pct,
                chapter_id=ctx.chapter_id,
                cloud_client=ctx.cloud_client,
                run_id=ctx.run_id,
                character_appearances=ctx.character_appearances,
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

        修改时间: 2026-03-21
        修改者: TraeAI
        任务: migrate-litellm-to-openai-sdk
        修改内容: 使用 OpenAI SDK，移除 extra_body，添加 reasoning_effort 支持

        修改时间: 2026-03-21
        修改者: TraeAI
        任务: 修复 Ollama thinking 模式控制
        修改内容: 当 enable_thinking=False 时，传递 reasoning_effort="none" 禁用 thinking
        """
        if not self._config.model:
            raise ValueError("model is required")

        if self._client is None:
            raise ValueError("client is required")

        request_params: dict[str, Any] = {
            "model": self._config.model,
            "messages": messages,
            "temperature": self._config.temperature,
            "top_p": self._config.top_p,
        }

        if enable_thinking:
            request_params["reasoning_effort"] = "medium"
        else:
            request_params["reasoning_effort"] = "none"

        if response_model is not None:
            request_params["response_format"] = self._build_json_schema(response_model)

        is_cloud = self._is_cloud_api()
        response = self._call_api_stream(request_params, is_cloud=is_cloud)

        if response_model is not None:
            parsed_result = self._parse_structured_response(response, response_model)
            return parsed_result, response

        return response

    def _parse_annotation(self, content: str) -> ChunkAnnotation:
        """解析标注结果（委托给子模块）"""
        return _parse_annotation_impl(content)

    def _validate_annotation(
        self,
        result: ChunkAnnotation,
        sources: dict,
        chunk_id: int | None,
        content_clean: str = "",
    ) -> ChunkAnnotation:
        """验证标注结果（委托给子模块）"""
        return _validate_annotation_impl(result, sources, chunk_id, content_clean)

    def _process_annotation_response(
        self,
        response: Any,
        is_cloud: bool,
        chunk_id: int | None = None,
        phase: str = "",
    ) -> tuple[str, str | None, Any]:
        """处理响应（委托给子模块）"""
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
        """记录标注开始日志（委托给子模块）"""
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
        messages: List[dict],
        text: str,
        prev_summary: str | None,
    ) -> None:
        """记录prompt和response日志（委托给子模块）"""
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
