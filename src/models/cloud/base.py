"""
创建时间: 2026-03-12
创建者: TraeAI
任务: 项目文件结构整理与拆解 - 从 client.py 拆分云端模型基础客户端类

本模块包含云端模型客户端的基础类和公共接口。

修改时间: 2026-03-16
修改者: TraeAI
修改内容: 将 OpenAI SDK 替换为 LiteLLM

修改时间: 2026-03-21
修改者: TraeAI
任务: migrate-litellm-to-openai-sdk
修改内容:
1. 移除 LiteLLM 依赖，改用 OpenAI SDK
2. 移除 extra_body 参数，改用顶级参数
3. 添加 reasoning_effort 参数支持
4. 移除 API 密钥硬编码默认值
"""

from __future__ import annotations

import json
from typing import Any, Callable, Dict, List, Optional, cast

from loguru import logger
from openai import OpenAI

from src.config import TaskModelConfig, load_task_config
from src.config.analysis_logger import AnalysisLogger
from src.models.local.parser import extract_thinking_unified

from .schema import CloudAnalysis

TokenUsageCallback = Callable[[str, str, str, int, int, Optional[int], Optional[int]], None]


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

    修改时间: 2026-03-21
    修改者: TraeAI
    任务: migrate-litellm-to-openai-sdk
    修改内容: 使用 OpenAI SDK 替代 LiteLLM
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
            self._client = OpenAI(
                base_url=self._config.base_url,
                api_key=self._config.api_key,
                timeout=self._config.timeout_s,
            )
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

        修改时间: 2026-03-21
        修改者: TraeAI
        任务: migrate-litellm-to-openai-sdk
        修改内容: 使用 OpenAI SDK，移除 extra_body，添加 reasoning_effort 支持
        """
        request_params: dict[str, Any] = {
            "model": self._config.model,
            "messages": cast(Any, messages),
        }

        thinking_enabled = self._config.thinking_enabled
        if thinking_enabled:
            request_params["reasoning_effort"] = "medium"

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
