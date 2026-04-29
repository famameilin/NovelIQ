"""
本模块包含云端模型客户端的基础类和公共接口
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from loguru import logger

from src.config import TaskModelConfig, TaskType
from src.config.analysis_logger import AnalysisLogger
from src.models.disambiguation_types import NameCountCandidate
from src.models.local.base import BaseModelClient
from src.models.local.disambiguation import DisambiguationPromptContext

from .schema import CloudAnalysis

TokenUsageCallback = Callable[[str, str, str, str, int, int, int | None, int | None], None]


class CloudModelClient:
    """云端模型客户端基类"""

    async def diagnose(self, payload: dict) -> CloudAnalysis:
        raise NotImplementedError

    async def disambiguate_characters(
        self,
        candidates: list[NameCountCandidate],
        context_sentences: dict[str, str] | None = None,
        existing_names: list[str] | None = None,
        prompt_context: DisambiguationPromptContext | None = None,
    ) -> dict[str, str]:
        raise NotImplementedError


class NullCloudModelClient(CloudModelClient):
    """空云端模型客户端，用于测试"""

    async def diagnose(self, payload: dict) -> CloudAnalysis:
        return make_empty_analysis()

    async def disambiguate_characters(
        self,
        candidates: list[NameCountCandidate],
        context_sentences: dict[str, str] | None = None,
        existing_names: list[str] | None = None,
        prompt_context: DisambiguationPromptContext | None = None,
    ) -> dict[str, str]:
        return {candidate["name"]: candidate["name"] for candidate in candidates}


class BaseCloudModelClient(BaseModelClient):
    """
    云端模型客户端基类

    继承自 BaseModelClient，提供云端特定的配置和功能
    """

    def __init__(
        self,
        task_type: TaskType = "diagnosis",
        config: TaskModelConfig | None = None,
        client: Any | None = None,
        analysis_logger: AnalysisLogger | None = None,
        token_usage_callback: TokenUsageCallback | None = None,
        novel_id: str | None = None,
        session: Any | None = None,
    ) -> None:
        # 调用父类构造函数，传递 task_type 参数
        super().__init__(
            task_type=task_type,
            config=config,
            client=client,
            analysis_logger=analysis_logger,
            token_usage_callback=token_usage_callback,
            novel_id=novel_id,
            session=session,
        )
        logger.info(
            "[云端模型] 客户端初始化完成: model={} base_url={}",
            self._config.model,
            self._config.base_url,
        )

    def _build_request_params(self, messages: list[dict[Any, Any]], enable_thinking: bool = False) -> dict[str, Any]:
        """
        构建请求参数（云端版本）

        说明: 云端专用版本，使用 reasoning_effort 参数
        """
        request_params: dict[str, Any] = {
            "model": self._config.model,
            "messages": messages,
        }

        thinking_enabled = self._config.thinking_enabled
        if thinking_enabled:
            request_params["reasoning_effort"] = "medium"
            request_params["extra_body"] = {"think": True}

        return request_params


def make_empty_analysis() -> CloudAnalysis:
    analysis = CloudAnalysis(
        novel_id=None,
        foreshadow_expectation=None,
        arc_scores={},
        genre_labels=[],
        style_labels=[],
        topic_labels=[],
        diagnosis=None,
        value_logic_type=None,
        value_logic_reason=None,
        power_stance_score=None,
        power_stance_reason=None,
        common_people_dignity=None,
        dignity_reason=None,
        cultural_depth_score=None,
        cultural_depth_reason=None,
        focus_structure=None,
        focus_characters=[],
    )
    return analysis
