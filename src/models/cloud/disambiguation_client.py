"""
创建时间: 2026-03-12
创建者: TraeAI
任务: 项目文件结构整理与拆解 - 从 client.py 拆分云端消歧客户端

本模块包含云端人名消歧相关的模型客户端。
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from loguru import logger

from src.config import TaskModelConfig
from src.config.analysis_logger import AnalysisLogger

from .base import BaseCloudModelClient, TokenUsageCallback


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

        request_params = self._build_request_params(messages)
        response = self._client.chat.completions.create(**request_params)

        message = response.choices[0].message
        content_clean, thinking_content = self._extract_response_content(message)

        has_thinking = bool(thinking_content and thinking_content.strip())
        has_response = bool(content_clean and content_clean.strip())

        logger.info(
            "[云端模型] disambiguate 响应: has_thinking={} thinking_chars={} has_response={} response_chars={}",
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
                "type": "cloud_disambiguate_characters",
            }
            if thinking_content:
                metadata["thinking_content"] = thinking_content
                metadata["thinking_format"] = extraction.thinking_format
                metadata["thinking_tokens"] = extraction.thinking_tokens
            self._analysis_logger.log_cloud_prompt(
                messages=messages,
                response=content_clean,
                metadata=metadata,
            )

        from src.models.local.parser import parse_alias_map

        result = parse_alias_map(content_clean, candidates)

        self._record_token_usage(response, "unknown", "disambiguate")

        logger.info(
            "[云端模型] disambiguate 完成: result_count={}",
            len(result),
        )
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

        system_prompt = settings.prompts.local_disambiguate_system
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
