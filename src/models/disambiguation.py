"""
DisambiguationClient 模块

创建时间: 2026-03-12
创建者: TraeAI
任务: 项目文件结构整理与拆解 - 拆分消歧专用客户端

修改时间: 2026-03-23
修改者: TraeAI
任务: unify-model-client-architecture
修改内容: 移动到 src/models/disambiguation.py（统一客户端架构）

修改时间: 2026-03-27
修改者: TraeAI
任务: disambiguation-state-three-layer
修改内容: 将 alias_map 改为 canonical_decisions

说明:
- 此类继承自 BaseModelClient，同时支持本地和云端
- 核心逻辑委托给 src.models.local.disambiguation 子模块
"""

from __future__ import annotations

from typing import Any

from src.config import TaskModelConfig, TaskType
from src.config.analysis_logger import AnalysisLogger
from src.models.disambiguation_types import NameCountCandidate
from src.models.local.base import BaseModelClient, TokenUsageCallback

from .local.disambiguation import (
    DisambiguationPromptContext,
    ExtendedDisambigResult,
    build_anonymous_disambig_messages,
    build_disambiguate_messages,
    build_extended_result_from_response,
    build_result_from_response,
    call_disambiguate_api,
    log_disambiguate_response,
    log_disambiguate_result,
    log_disambiguate_start,
)


class DisambiguationClient(BaseModelClient):
    """
    统一消歧客户端

    负责处理人物别名识别和匿名人物识别。
    同时支持本地和云端模型，通过 base_url 自动检测。
    """

    def __init__(
        self,
        task_type: TaskType = "incremental_disambig",
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

    async def disambiguate_characters(
        self,
        candidates: list[NameCountCandidate],
        context_sentences: dict[str, str] | None = None,
        existing_names: list[str] | None = None,
        prompt_context: DisambiguationPromptContext | None = None,
    ) -> ExtendedDisambigResult:
        if not candidates:
            return ExtendedDisambigResult(
                canonical_decisions={},
                entity_types={},
                entity_relations=[],
                alias_confidence={},
            )
        is_cloud = self._is_cloud_api()
        log_disambiguate_start(
            "disambiguate_characters",
            len(candidates),
            is_cloud,
            self._novel_id,
            self._task_type,
            self._config.model,
            self._config.thinking_enabled,
        )
        messages = build_disambiguate_messages(
            candidates,
            context_sentences,
            existing_names,
            prompt_context=prompt_context,
        )
        try:
            response = await call_disambiguate_api(
                client=self,
                config=self._config,
                messages=messages,
                log_type="disambiguate_characters",
            )
            log_disambiguate_response(
                "disambiguate_characters",
                len(response.canonical_decisions),
                is_cloud,
                self._novel_id,
            )
            metadata = {
                "model": self._config.model,
                "task_type": self._task_type,
                "candidates_count": len(candidates),
                "type": "disambiguate_characters",
            }
            log_disambiguate_result(self._analysis_logger, messages, response, metadata)

            result = build_extended_result_from_response(response, candidates, context_sentences)
            return result
        except Exception as e:
            from loguru import logger

            logger.error("disambiguate_characters unexpected error: {}", str(e))
            raise

    async def disambiguate_anonymous(
        self,
        anonymous_names: list[str],
        anonymous_contexts: dict[str, str],
        existing_names: list[str] | None = None,
        existing_contexts: dict[str, str] | None = None,
    ) -> dict[str, str]:
        if not anonymous_names:
            return {}

        messages = build_anonymous_disambig_messages(
            anonymous_names, anonymous_contexts, existing_names, existing_contexts
        )
        is_cloud = self._is_cloud_api()

        log_disambiguate_start(
            "disambiguate_anonymous",
            len(anonymous_names),
            is_cloud,
            self._novel_id,
            self._task_type,
            self._config.model,
            self._config.thinking_enabled,
        )

        try:
            response = await call_disambiguate_api(
                client=self,
                config=self._config,
                messages=messages,
                log_type="disambiguate_anonymous",
            )
            log_disambiguate_response(
                "disambiguate_anonymous",
                len(response.canonical_decisions),
                is_cloud,
                self._novel_id,
            )

            metadata = {
                "model": self._config.model,
                "task_type": self._task_type,
                "anonymous_count": len(anonymous_names),
                "type": "disambiguate_anonymous",
            }
            log_disambiguate_result(self._analysis_logger, messages, response, metadata)

            result = build_result_from_response(response, anonymous_names)
            return result
        except Exception as e:
            from loguru import logger

            logger.error("disambiguate_anonymous unexpected error: {}", str(e))
            raise

    async def generate_summary(
        self,
        messages: list[dict[str, str]],
        max_tokens: int = 150,
    ) -> str:
        """
        生成摘要

        创建时间: 2026-04-08
        创建者: GLM-5
        任务: summary-full-chain-refactor
        说明: 调用 LLM 生成阶段性摘要

        Args:
            messages: 消息列表
            max_tokens: 最大 token 数

        Returns:
            生成的摘要文本
        """
        import time

        start_time = time.time()
        response = await self._client.chat.completions.create(
            model=self._config.model,
            messages=messages,
            temperature=0.3,
            max_tokens=max_tokens,
        )
        duration_ms = int((time.time() - start_time) * 1000)

        summary = response.choices[0].message.content.strip()

        self._record_token_usage(response, "stage_summary")

        from loguru import logger

        logger.debug(
            "Generated summary in {}ms: {} chars",
            duration_ms,
            len(summary),
        )

        return summary


__all__ = ["DisambiguationClient"]
