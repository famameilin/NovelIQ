"""
创建时间: 2026-03-12
创建者: TraeAI
任务: 项目文件结构整理与拆解 - 从 unified_client.py 拆分消歧专用客户端

修改时间: 2026-03-13
修改者: TraeAI
修改内容: 提取公共方法 _log_disambiguate_start, _call_disambiguate_api,
          _process_disambiguate_response, _log_disambiguate_result，
          重构 disambiguate_characters 和 disambiguate_anonymous 使用公共方法

修改时间: 2026-03-16
修改者: TraeAI
任务: 重构本地消歧客户端集成 Instructor
修改内容: 集成 Instructor 实现结构化输出，简化 JSON 解析逻辑

修改时间: 2026-03-17
修改者: TraeAI
任务: 移除 Instructor 依赖
修改内容: 使用 LiteLLM 的 JSON Schema 模式替代 Instructor

修改时间: 2026-03-18
修改者: TraeAI
任务: code-quality-refactor - Task 9 拆分disambiguation_client.py
修改内容:
- 将消息构建逻辑移至 disambiguation/messages.py
- 将结果构建逻辑移至 disambiguation/result_builder.py
- 将日志逻辑移至 disambiguation/logging.py
- 将API调用逻辑移至 disambiguation/api_call.py
- 简化 disambiguation_client.py，委托给子模块

本模块包含人名消歧相关的模型客户端，负责处理人物别名识别和匿名人物识别。
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, TypeVar

from loguru import logger

from src.config import TaskModelConfig, TaskType
from src.config.analysis_logger import AnalysisLogger

from .base import BaseModelClient, TokenUsageCallback
from .disambiguation import (
    build_anonymous_disambig_messages,
    build_disambiguate_messages,
    build_result_from_response,
    call_disambiguate_api,
    log_disambiguate_response,
    log_disambiguate_result,
    log_disambiguate_start,
)
from .schema import DisambiguateResponseModel

T = TypeVar("T")


class DisambiguationClient(BaseModelClient):
    """
    消歧专用客户端

    负责处理人物别名识别和匿名人物识别。

    修改时间: 2026-03-16
    修改者: TraeAI
    任务: 支持依赖注入 instructor_client_factory，便于测试

    修改时间: 2026-03-18
    修改者: TraeAI
    任务: code-quality-refactor - Task 9 拆分disambiguation_client.py
    修改内容: 委托所有逻辑给子模块
    """

    def __init__(
        self,
        task_type: TaskType = "incremental_disambig",
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
        self._instructor_client_factory = instructor_client_factory

    def disambiguate_characters(
        self,
        candidates: List[str] | List[Dict[str, int]],
        context_sentences: Dict[str, str] | None = None,
        existing_names: List[str] | None = None,
        rag_hint: str | None = None,
    ) -> Dict[str, str]:
        """
        人名消歧

        修改时间: 2026-03-12
        创建者: TraeAI
        修改内容: 支持 List[str] 和 List[Dict] 两种候选人名格式
                  Dict 格式: [{"name": "伯安", "count": 312}, ...]

        修改时间: 2026-03-13
        修改者: TraeAI
        修改内容: 重构使用公共方法

        修改时间: 2026-03-18
        修改者: TraeAI
        任务: code-quality-refactor - Task 9 拆分disambiguation_client.py
        修改内容: 委托给子模块函数
        """
        if not candidates:
            return {}

        messages = build_disambiguate_messages(candidates, context_sentences, existing_names, rag_hint)
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

        try:
            response = call_disambiguate_api(
                client=self,
                config=self._config,
                messages=messages,
                log_type="disambiguate_characters",
                is_cloud=is_cloud,
            )
            log_disambiguate_response(
                "disambiguate_characters",
                len(response.alias_map),
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

            result = build_result_from_response(response, candidates)

            logger.debug("disambiguate_characters complete")
            return result
        except Exception as e:
            logger.error("disambiguate_characters unexpected error: {}", str(e))
            from litellm.exceptions import APIConnectionError as LiteLLMAPIConnectionError

            if isinstance(e, LiteLLMAPIConnectionError):
                raise ConnectionError(str(e)) from e
            raise

    def disambiguate_anonymous(
        self,
        anonymous_names: List[str],
        anonymous_contexts: Dict[str, str],
        existing_names: List[str] | None = None,
        existing_contexts: Dict[str, str] | None = None,
    ) -> Dict[str, str]:
        """
        消歧匿名占位名

        修改时间: 2026-03-13
        修改者: TraeAI
        修改内容: 重构使用公共方法

        修改时间: 2026-03-18
        修改者: TraeAI
        任务: code-quality-refactor - Task 9 拆分disambiguation_client.py
        修改内容: 委托给子模块函数
        """
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
            response = call_disambiguate_api(
                client=self,
                config=self._config,
                messages=messages,
                log_type="disambiguate_anonymous",
                is_cloud=is_cloud,
            )
            log_disambiguate_response(
                "disambiguate_anonymous",
                len(response.alias_map),
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

            logger.debug("disambiguate_anonymous complete")
            return result
        except Exception as e:
            logger.error("disambiguate_anonymous unexpected error: {}", str(e))
            raise
