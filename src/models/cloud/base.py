"""
创建时间: 2026-03-12
创建者: TraeAI
任务: 项目文件结构整理与拆解 - 从 client.py 拆分云端模型基础客户端类

本模块包含云端模型客户端的基础类和公共接口。

修改时间: 2026-03-16
修改者: TraeAI
修改内容: 将 OpenAI SDK 替换为 LiteLLM
"""

from __future__ import annotations

import json
from typing import Any, Callable, Dict, List, Optional, cast

import litellm
from loguru import logger

from src.config import TaskModelConfig, load_task_config
from src.config.analysis_logger import AnalysisLogger
from src.models.local.parser import extract_thinking_unified
from src.models.local.litellm_utils import get_model_with_provider

from .schema import CloudAnalysis

TokenUsageCallback = Callable[[str, str, str, int, int, Optional[int], Optional[int]], None]


class _LiteLLMCompletionsWrapper:
    """
    LiteLLM Completions 包装器
    兼容 OpenAI SDK 的 chat.completions.create() 接口
    """

    def __init__(self, config: "TaskModelConfig") -> None:
        self._config = config

    def create(self, **kwargs) -> Any:
        """
        调用 LiteLLM completion API

        LiteLLM 会根据 model 参数自动路由到正确的提供商
        """
        return litellm.completion(**kwargs)


class _LiteLLMChatWrapper:
    """LiteLLM Chat API 包装器"""

    def __init__(self, config: "TaskModelConfig") -> None:
        self._config = config
        self.completions = _LiteLLMCompletionsWrapper(config)


class _LiteLLMClientWrapper:
    """
    LiteLLM 客户端包装器
    兼容 OpenAI SDK 的 client.chat.completions.create() 接口
    """

    def __init__(self, config: "TaskModelConfig") -> None:
        self._config = config
        self.chat = _LiteLLMChatWrapper(config)


class CloudModelClient:
    """云端模型客户端基类"""

    def diagnose(self, payload: dict) -> CloudAnalysis:
        raise NotImplementedError

    def disambiguate_characters(
        self,
        candidates: List[str],
        context_sentences: Dict[str, str] | None = None,
        existing_names: List[str] | None = None,
    ) -> Dict[str, str]:
        raise NotImplementedError


class NullCloudModelClient(CloudModelClient):
    """空云端模型客户端，用于测试"""

    def diagnose(self, payload: dict) -> CloudAnalysis:
        return make_empty_analysis()

    def disambiguate_characters(
        self,
        candidates: List[str],
        context_sentences: Dict[str, str] | None = None,
        existing_names: List[str] | None = None,
    ) -> Dict[str, str]:
        return {name: name for name in candidates}


class BaseCloudModelClient(CloudModelClient):
    """
    云端模型客户端基类

    提供公共的配置管理、客户端初始化、API调用等功能。
    """

    def __init__(
        self,
        config: TaskModelConfig | None = None,
        client: Any | None = None,
        analysis_logger: AnalysisLogger | None = None,
        token_usage_callback: Optional[TokenUsageCallback] = None,
        novel_id: Optional[str] = None,
    ) -> None:
        loaded_config = config or load_task_config("diagnosis")
        loaded_config.validate()
        self._config = loaded_config
        if client is not None:
            self._client = client
        else:
            self._client = _LiteLLMClientWrapper(self._config)
            if self._config.api_key:
                litellm.api_key = self._config.api_key
            if self._config.base_url:
                litellm.api_base = self._config.base_url
        self._analysis_logger = analysis_logger
        self._token_usage_callback = token_usage_callback
        self._novel_id = novel_id
        logger.info(
            "[云端模型] 客户端初始化: model={} base_url={}",
            self._config.model,
            self._config.base_url,
        )

    def _build_request_params(self, messages: List[Dict[str, str]]) -> dict[str, Any]:
        """
        构建请求参数

        修改时间: 2026-03-16
        修改者: TraeAI
        任务: 修复thinking参数传递方式
        修改内容: 将thinking参数作为顶级参数传递，而非放在extra_body中

        修改时间: 2026-03-17
        修改者: TraeAI
        任务: 修复 LiteLLM 模型名称格式
        修改内容: 使用 get_model_with_provider 自动添加 provider 前缀
        """
        model_name = get_model_with_provider(self._config.model, self._config)
        request_params: dict[str, Any] = {
            "model": model_name,
            "messages": cast(Any, messages),
        }

        thinking_enabled = self._config.thinking_enabled
        if thinking_enabled:
            model_name = (self._config.model or "").lower()
            if "claude" in model_name or "anthropic" in model_name:
                budget = self._config.thinking_budget_tokens
                if budget:
                    request_params["thinking"] = {"type": "enabled", "budget_tokens": budget}
                else:
                    request_params["thinking"] = {"type": "enabled"}
            elif "deepseek" in model_name:
                request_params["thinking"] = {"type": "enabled"}
            # 其他模型（如 GLM-5）不支持 reasoning_effort，不添加该参数

        return request_params

    def _extract_response_content(self, message) -> tuple[str, str | None]:
        """提取响应内容"""
        content = message.content or ""
        extraction = extract_thinking_unified(
            content=content,
            reasoning_content=getattr(message, "reasoning_content", None),
            support_reasoning_content=True,
            support_think_tags=True,
        )
        return extraction.content_without_thinking, extraction.thinking_content

    def _parse_response(self, content: str) -> Dict[str, Any] | None:
        """解析JSON响应，支持处理markdown代码块包裹的JSON"""
        import re

        content_to_parse = content.strip()

        if not content_to_parse:
            return None

        try:
            data = json.loads(content_to_parse)
            if isinstance(data, dict):
                return data
        except json.JSONDecodeError:
            pass

        json_match = re.search(r"```(?:json)?\s*([\s\S]*?)```", content_to_parse)
        if json_match:
            extracted = json_match.group(1).strip()
            try:
                data = json.loads(extracted)
                if isinstance(data, dict):
                    logger.info("[云端模型] JSON从markdown代码块中提取成功")
                    return data
            except json.JSONDecodeError:
                pass

        json_match = re.search(r"\{[\s\S]*\}", content_to_parse)
        if json_match:
            extracted = json_match.group(0)
            try:
                data = json.loads(extracted)
                if isinstance(data, dict):
                    logger.info("[云端模型] JSON从混合内容中提取成功")
                    return data
            except json.JSONDecodeError:
                pass

        return None

    def _record_token_usage(self, response, novel_id: str, call_type: str) -> None:
        """记录token使用量"""
        if self._token_usage_callback and hasattr(response, "usage") and response.usage:
            self._token_usage_callback(
                self._novel_id or novel_id or "unknown",
                call_type,
                "cloud",
                response.usage.prompt_tokens,
                response.usage.total_tokens,
                response.usage.completion_tokens,
                None,
            )


def make_empty_analysis() -> CloudAnalysis:
    """创建空的分析结果"""
    analysis = CloudAnalysis(
        novel_id=None,
        foreshadow_rate=None,
        arc_scores=[],
        narrative_type=None,
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
    )
    return analysis
