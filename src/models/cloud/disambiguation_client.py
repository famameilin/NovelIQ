"""
创建时间: 2026-03-12
创建者: TraeAI
任务: 项目文件结构整理与拆解 - 从 client.py 拆分云端消歧客户端

本模块包含云端人名消歧相关的模型客户端。

修改时间: 2026-03-16
修改者: TraeAI
任务: 重构云端消歧客户端集成 Instructor
修改内容: 集成 Instructor 实现结构化输出，简化解析逻辑
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, cast

import instructor
from loguru import logger

from src.config import TaskModelConfig
from src.config.analysis_logger import AnalysisLogger

from .base import BaseCloudModelClient, TokenUsageCallback
from .schema import DisambiguationAliasMap


class CloudDisambiguationClient(BaseCloudModelClient):
    """
    云端消歧客户端

    负责使用云端模型进行人名消歧。
    """

    def __init__(
        self,
        config: TaskModelConfig | None = None,
        client: Any | None = None,
        analysis_logger: AnalysisLogger | None = None,
        token_usage_callback: Optional[TokenUsageCallback] = None,
        novel_id: Optional[str] = None,
    ) -> None:
        super().__init__(
            config=config,
            client=client,
            analysis_logger=analysis_logger,
            token_usage_callback=token_usage_callback,
            novel_id=novel_id,
        )

    def disambiguate_characters(
        self,
        candidates: List[str],
        context_sentences: Dict[str, str] | None = None,
        existing_names: List[str] | None = None,
    ) -> Dict[str, str]:
        """
        人名消歧

        修改时间: 2026-03-16
        修改者: TraeAI
        任务: 重构云端消歧客户端集成 Instructor
        修改内容: 使用 Instructor 实现结构化输出，简化解析逻辑
        """
        if not self._config.model:
            raise ValueError("cloud model is required")
        if not candidates:
            return {}
        messages = self._build_disambiguate_messages(candidates, context_sentences, existing_names)

        logger.info(
            "[云端模型] disambiguate 开始: model={} candidates_count={}",
            self._config.model,
            len(candidates),
        )

        try:
            result = self._call_with_instructor(messages, candidates)
        except Exception as e:
            logger.warning(
                "[云端模型] Instructor 调用失败，回退到传统解析: error={}",
                str(e),
            )
            result = self._call_with_fallback(messages, candidates)

        logger.info(
            "[云端模型] disambiguate 完成: result_count={}",
            len(result),
        )
        return result

    def _call_with_instructor(
        self,
        messages: List[Dict[str, str]],
        candidates: List[str],
    ) -> Dict[str, str]:
        """
        使用 Instructor 进行结构化输出

        创建时间: 2026-03-16
        创建者: TraeAI
        任务: 重构云端消歧客户端集成 Instructor
        """
        from litellm import completion

        model_name = self._config.model or ""
        provider_model = f"litellm/{model_name}"

        client = instructor.from_litellm(completion)
        request_params = self._build_instructor_request_params(messages)
        request_params["model"] = provider_model

        response = client.chat.completions.create(
            response_model=DisambiguationAliasMap,
            **request_params,
        )

        raw_completion = response._raw_response if hasattr(response, "_raw_response") else None
        if raw_completion:
            self._record_token_usage(raw_completion, "unknown", "disambiguate")

        if self._analysis_logger and raw_completion:
            self._log_instructor_response(messages, response, raw_completion, candidates)

        return self._build_result_from_response(response.alias_map, candidates)

    def _call_with_fallback(
        self,
        messages: List[Dict[str, str]],
        candidates: List[str],
    ) -> Dict[str, str]:
        """
        回退到传统解析方式

        创建时间: 2026-03-16
        创建者: TraeAI
        任务: 重构云端消歧客户端集成 Instructor
        """
        request_params = self._build_request_params(messages)
        response = self._client.chat.completions.create(**request_params)

        message = response.choices[0].message
        content_clean, thinking_content = self._extract_response_content(message)

        has_thinking = bool(thinking_content and thinking_content.strip())
        has_response = bool(content_clean and content_clean.strip())

        logger.info(
            "[云端模型] disambiguate 响应(fallback): has_thinking={} thinking_chars={} has_response={} response_chars={}",
            has_thinking,
            len(thinking_content) if thinking_content else 0,
            has_response,
            len(content_clean),
        )

        if self._analysis_logger:
            from src.models.local.parser import extract_thinking_unified

            extraction = extract_thinking_unified(
                content=message.content or "",
                reasoning_content=getattr(message, "reasoning_content", None),
                support_reasoning_content=True,
                support_think_tags=True,
            )
            metadata = {
                "model": self._config.model,
                "candidates_count": len(candidates),
                "type": "cloud_disambiguate_characters_fallback",
            }
            if thinking_content:
                metadata["thinking_content"] = thinking_content
                metadata["thinking_format"] = extraction.thinking_format
                metadata["thinking_tokens"] = extraction.thinking_tokens
            self._analysis_logger.log_prompt(
                messages=messages,
                response=content_clean,
                metadata=metadata,
            )

        from src.models.local.parser import parse_alias_map

        result = parse_alias_map(content_clean, candidates)

        self._record_token_usage(response, "unknown", "disambiguate")

        return result

    def _build_instructor_request_params(self, messages: List[Dict[str, str]]) -> Dict[str, Any]:
        """
        构建 Instructor 请求参数

        创建时间: 2026-03-16
        创建者: TraeAI
        任务: 重构云端消歧客户端集成 Instructor
        """
        params: Dict[str, Any] = {
            "messages": cast(Any, messages),
        }

        if self._config.api_key:
            params["api_key"] = self._config.api_key
        if self._config.base_url:
            params["base_url"] = self._config.base_url

        thinking_enabled = self._config.thinking_enabled
        if thinking_enabled:
            model_name = self._config.model or ""
            if "claude" in model_name.lower():
                budget = self._config.thinking_budget_tokens
                if budget:
                    params["thinking"] = {"type": "enabled", "budget_tokens": budget}
            params["extra_body"] = {"thinking": {"type": "enabled"}}

        return params

    def _log_instructor_response(
        self,
        messages: List[Dict[str, str]],
        response: DisambiguationAliasMap,
        raw_completion: Any,
        candidates: List[str],
    ) -> None:
        """
        记录 Instructor 响应日志

        创建时间: 2026-03-16
        创建者: TraeAI
        任务: 重构云端消歧客户端集成 Instructor
        """
        metadata = {
            "model": self._config.model,
            "candidates_count": len(candidates),
            "type": "cloud_disambiguate_characters_instructor",
            "alias_map": response.alias_map,
        }

        if hasattr(raw_completion, "choices") and raw_completion.choices:
            message = raw_completion.choices[0].message
            content = message.content or ""
            reasoning_content = getattr(message, "reasoning_content", None)

            if reasoning_content:
                metadata["thinking_content"] = reasoning_content
                metadata["thinking_format"] = "reasoning_content"
                metadata["thinking_tokens"] = len(reasoning_content) // 2

            if self._analysis_logger:
                self._analysis_logger.log_prompt(
                    messages=messages,
                    response=content,
                    metadata=metadata,
                )

    def _build_result_from_response(
        self,
        alias_map: Dict[str, str],
        candidates: List[str],
    ) -> Dict[str, str]:
        """
        从响应构建结果

        创建时间: 2026-03-16
        创建者: TraeAI
        任务: 重构云端消歧客户端集成 Instructor
        """
        result: Dict[str, str] = {}
        for name in candidates:
            if name in alias_map:
                result[name] = str(alias_map[name])
            else:
                result[name] = name
        return result

    def _build_disambiguate_messages(
        self,
        candidates: List[str],
        context_sentences: Dict[str, str] | None = None,
        existing_names: List[str] | None = None,
    ) -> List[Dict[str, str]]:
        from src.config import settings

        lines = []
        for name in candidates:
            ctx = context_sentences.get(name, "") if context_sentences else ""
            if ctx:
                lines.append(f"- {name}（参考：{ctx}）")
            else:
                lines.append(f"- {name}")
        body = "\n".join(lines)

        system_prompt = settings.prompts.disambiguate
        if existing_names:
            anchor_str = "、".join(existing_names)
            system_prompt += f"\n\n【已存在的角色】以下名字已在知识库中存在：[{anchor_str}]。如果你有充分证据认为候选人名与这些角色是同一人物，可以合并；如果证据不足，保持独立。"

        user_content = (
            "以下候选人名可能是同一人物的不同称呼，也可能是不同人物。\n"
            "请根据例句中的上下文判断，若两人明显是不同人物请不要合并。\n\n"
            f"候选人名列表：\n{body}"
        )

        return [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_content},
        ]
