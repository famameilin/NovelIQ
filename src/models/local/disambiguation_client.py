"""
创建时间: 2026-03-12
创建者: TraeAI
任务: 项目文件结构整理与拆解 - 从 unified_client.py 拆分消歧专用客户端

修改时间: 2026-03-13
修改者: TraeAI
修改内容: 提取公共方法 _log_disambiguate_start, _call_disambiguate_api,
          _process_disambiguate_response, _log_disambiguate_result，
          重构 disambiguate_characters 和 disambiguate_anonymous 使用公共方法

本模块包含人名消歧相关的模型客户端，负责处理人物别名识别和匿名人物识别。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional, cast

import openai
from loguru import logger

from src.config import TaskModelConfig, TaskType
from src.config.analysis_logger import AnalysisLogger

from .base import BaseModelClient, TokenUsageCallback
from .parser import extract_thinking_unified, parse_alias_map
from .prompts import DISAMBIGUATE_SYSTEM_PROMPT, ANONYMOUS_DISAMBIG_SYSTEM_PROMPT


@dataclass
class DisambiguateResponse:
    """
    创建时间: 2026-03-13
    创建者: TraeAI
    任务: refactor-model-interaction-layer
    说明: 消歧响应数据结构，封装响应内容和thinking内容
    """

    content_clean: str
    thinking_content: Optional[str]
    extraction: Optional[Any]
    raw_response: Any


class DisambiguationClient(BaseModelClient):
    """
    消歧专用客户端

    负责处理人物别名识别和匿名人物识别。
    """

    def __init__(
        self,
        task_type: TaskType = "incremental_disambig",
        config: TaskModelConfig | None = None,
        client: Any | None = None,
        analysis_logger: AnalysisLogger | None = None,
        token_usage_callback: Optional[TokenUsageCallback] = None,
        novel_id: Optional[str] = None,
    ) -> None:
        super().__init__(
            task_type=task_type,
            config=config,
            client=client,
            analysis_logger=analysis_logger,
            token_usage_callback=token_usage_callback,
            novel_id=novel_id,
        )

    def _log_disambiguate_start(
        self,
        log_type: str,
        count: int,
        is_cloud: bool,
    ) -> None:
        """
        创建时间: 2026-03-13
        创建者: TraeAI
        任务: refactor-model-interaction-layer
        说明: 统一记录消歧开始日志，区分云端/本地
        """
        if is_cloud:
            logger.info(
                "[云端模型] {} 开始: task_type={} model={} count={}",
                log_type,
                self._task_type,
                self._config.model,
                count,
            )
        else:
            logger.debug(
                "{} start task_type={} model={} count={}",
                log_type,
                self._task_type,
                self._config.model,
                count,
            )

    def _call_disambiguate_api(
        self,
        messages: List[Dict[str, str]],
        log_type: str,
    ) -> Any:
        """
        创建时间: 2026-03-13
        创建者: TraeAI
        任务: refactor-model-interaction-layer
        说明: 统一调用消歧API，处理响应字符串/对象两种情况
        """
        if not self._config.model:
            raise ValueError("model is required")

        enable_thinking = self._config.thinking_enabled
        response = self._client.chat.completions.create(
            model=self._config.model,
            messages=cast(Any, messages),
            temperature=self._config.temperature,
            top_p=self._config.top_p,
            presence_penalty=self._config.presence_penalty,
            extra_body=self._build_extra_body(enable_thinking),
        )
        return response

    def _process_disambiguate_response(
        self,
        response: Any,
        is_cloud: bool,
        log_type: str,
    ) -> DisambiguateResponse:
        """
        创建时间: 2026-03-13
        创建者: TraeAI
        任务: refactor-model-interaction-layer
        说明: 统一处理消歧响应，提取thinking内容，记录响应日志
        """
        if isinstance(response, str):
            logger.warning("{} received string response from API", log_type)
            content_clean = response
            thinking_content = None
            extraction = None
        else:
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
                "[云端模型] {} 响应: has_thinking={} thinking_chars={} has_response={} response_chars={}",
                log_type,
                has_thinking,
                len(thinking_content) if thinking_content else 0,
                has_response,
                len(content_clean),
            )
        else:
            logger.info(
                "{} response: has_thinking={} thinking_chars={} has_response={} response_chars={}",
                log_type,
                has_thinking,
                len(thinking_content) if thinking_content else 0,
                has_response,
                len(content_clean),
            )
            logger.debug(
                "{} response received chars={} thinking_chars={}",
                log_type,
                len(content_clean),
                len(thinking_content) if thinking_content else 0,
            )

        return DisambiguateResponse(
            content_clean=content_clean,
            thinking_content=thinking_content,
            extraction=extraction,
            raw_response=response,
        )

    def _log_disambiguate_result(
        self,
        messages: List[Dict[str, str]],
        response_data: DisambiguateResponse,
        metadata: Dict[str, Any],
    ) -> None:
        """
        创建时间: 2026-03-13
        创建者: TraeAI
        任务: refactor-model-interaction-layer
        说明: 统一记录消歧结果日志到 analysis_logger
        """
        if not self._analysis_logger:
            return

        if response_data.thinking_content:
            metadata["thinking_content"] = response_data.thinking_content
            if not isinstance(response_data.raw_response, str) and response_data.extraction is not None:
                metadata["thinking_format"] = response_data.extraction.thinking_format
                if hasattr(response_data.extraction, "thinking_tokens"):
                    metadata["thinking_tokens"] = response_data.extraction.thinking_tokens

        self._analysis_logger.log_local_prompt(
            chunk_id=None,
            messages=messages,
            response=response_data.content_clean,
            metadata=metadata,
        )

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
        修改者: TraeAI
        修改内容: 支持 List[str] 和 List[Dict] 两种候选人名格式
                  Dict 格式: [{"name": "伯安", "count": 312}, ...]

        修改时间: 2026-03-13
        修改者: TraeAI
        修改内容: 重构使用公共方法 _log_disambiguate_start, _call_disambiguate_api,
                  _process_disambiguate_response, _log_disambiguate_result
        """
        if not candidates:
            return {}

        messages = self._build_disambiguate_messages(candidates, context_sentences, existing_names, rag_hint)
        is_cloud = self._is_cloud_api()

        self._log_disambiguate_start("disambiguate_characters", len(candidates), is_cloud)

        try:
            response = self._call_disambiguate_api(messages, "disambiguate_characters")
            response_data = self._process_disambiguate_response(response, is_cloud, "disambiguate_characters")

            metadata = {
                "model": self._config.model,
                "task_type": self._task_type,
                "candidates_count": len(candidates),
                "type": "disambiguate_characters",
            }
            self._log_disambiguate_result(messages, response_data, metadata)

            result = parse_alias_map(response_data.content_clean, candidates)

            if not isinstance(response, str):
                self._record_token_usage(response, "local")

            logger.debug("disambiguate_characters complete")
            return result
        except openai.APIConnectionError as e:
            self._handle_api_connection_error(e)
            raise
        except openai.APITimeoutError as e:
            self._handle_api_timeout(e)
            raise
        except openai.APIStatusError as e:
            self._handle_api_status_error(e)
            raise
        except Exception as e:
            logger.error("disambiguate_characters unexpected error: {}", str(e))
            raise

    def _build_disambiguate_messages(
        self,
        candidates: List[str] | List[Dict[str, int]],
        context_sentences: Dict[str, str] | None = None,
        existing_names: List[str] | None = None,
        rag_hint: str | None = None,
    ) -> List[Dict[str, str]]:
        """
        构建消歧消息

        修改时间: 2026-03-12
        修改者: TraeAI
        修改内容: 支持 List[str] 和 List[Dict] 两种候选人名格式，Dict 格式包含频次信息
        """
        lines = []

        if candidates and isinstance(candidates[0], dict):
            dict_candidates = cast(List[Dict[str, int]], candidates)
            for item in dict_candidates:
                name = str(item["name"])
                count = item.get("count", 0)
                ctx = context_sentences.get(name, "") if context_sentences else ""
                if ctx:
                    lines.append(f"- {name}（次数：{count}，参考：{ctx}）")
                else:
                    lines.append(f"- {name}（次数：{count}）")
        else:
            str_candidates = cast(List[str], candidates)
            for name in str_candidates:
                ctx = context_sentences.get(name, "") if context_sentences else ""
                if ctx:
                    lines.append(f"- {name}（参考：{ctx}）")
                else:
                    lines.append(f"- {name}")

        body = "\n".join(lines)

        system_prompt = DISAMBIGUATE_SYSTEM_PROMPT
        if existing_names:
            anchor_str = "、".join(existing_names)
            system_prompt += f"\n\n【已存在的角色】以下名字已在知识库中存在：[{anchor_str}]。如果你有充分证据认为候选人名与这些角色是同一人物，可以合并；如果证据不足，保持独立。"

        user_parts = [
            "以下候选人名可能是同一人物的不同称呼，也可能是不同人物。",
            "请根据例句中的上下文判断，若两人明显是不同人物请不要合并。",
        ]
        if rag_hint:
            user_parts.append(rag_hint)
        user_parts.append(f"\n候选人名列表：\n{body}")
        user_content = "\n".join(user_parts)

        return [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_content},
        ]

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
        修改内容: 重构使用公共方法 _log_disambiguate_start, _call_disambiguate_api,
                  _process_disambiguate_response, _log_disambiguate_result
        """
        if not anonymous_names:
            return {}
        messages = self._build_anonymous_disambig_messages(
            anonymous_names, anonymous_contexts, existing_names, existing_contexts
        )
        is_cloud = self._is_cloud_api()

        self._log_disambiguate_start("disambiguate_anonymous", len(anonymous_names), is_cloud)

        try:
            response = self._call_disambiguate_api(messages, "disambiguate_anonymous")
            response_data = self._process_disambiguate_response(response, is_cloud, "disambiguate_anonymous")

            metadata = {
                "model": self._config.model,
                "task_type": self._task_type,
                "anonymous_count": len(anonymous_names),
                "type": "disambiguate_anonymous",
            }
            self._log_disambiguate_result(messages, response_data, metadata)

            result = parse_alias_map(response_data.content_clean, anonymous_names)

            if not isinstance(response, str):
                self._record_token_usage(response, "local")

            logger.debug("disambiguate_anonymous complete")
            return result
        except openai.APIConnectionError as e:
            self._handle_api_connection_error(e)
            raise
        except openai.APITimeoutError as e:
            self._handle_api_timeout(e)
            raise
        except openai.APIStatusError as e:
            self._handle_api_status_error(e)
            raise
        except Exception as e:
            logger.error("disambiguate_anonymous unexpected error: {}", str(e))
            raise

    def _build_anonymous_disambig_messages(
        self,
        anonymous_names: List[str],
        anonymous_contexts: Dict[str, str],
        existing_names: List[str] | None = None,
        existing_contexts: Dict[str, str] | None = None,
    ) -> List[Dict[str, str]]:
        """构建匿名消歧消息"""
        info_parts = []
        for name in anonymous_names:
            ctx = anonymous_contexts.get(name, "无上下文")
            info_parts.append(f"【匿名人物】{name}\n上下文：\n{ctx}\n---")
        anonymous_info = "\n\n".join(info_parts)

        existing_lines = []
        if existing_names:
            for name in existing_names:
                ctx = existing_contexts.get(name, "") if existing_contexts else ""
                if ctx:
                    existing_lines.append(f"- {name}（参考：{ctx}）")
                else:
                    existing_lines.append(f"- {name}")
        existing_str = "\n".join(existing_lines) if existing_lines else "无"

        user_content = f"""以下匿名占位名需要识别真实身份。

【已知正式名】
{existing_str}

{anonymous_info}

请根据上下文判断每个匿名人物的真实身份。"""

        return [
            {"role": "system", "content": ANONYMOUS_DISAMBIG_SYSTEM_PROMPT},
            {"role": "user", "content": user_content},
        ]
