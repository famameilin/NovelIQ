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

本模块包含人名消歧相关的模型客户端，负责处理人物别名识别和匿名人物识别。
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, TypeVar, cast

from loguru import logger

from src.config import TaskModelConfig, TaskType
from src.config.analysis_logger import AnalysisLogger
from src.utils.token_counter import count_messages_tokens, count_tokens

from .base import BaseModelClient, TokenUsageCallback
from .litellm_utils import get_model_with_provider
from .prompts import DISAMBIGUATE_SYSTEM_PROMPT, ANONYMOUS_DISAMBIG_SYSTEM_PROMPT
from .schema import DisambiguateResponseModel

T = TypeVar("T")


class DisambiguationClient(BaseModelClient):
    """
    消歧专用客户端

    负责处理人物别名识别和匿名人物识别。

    修改时间: 2026-03-16
    修改者: TraeAI
    任务: 支持依赖注入 instructor_client_factory，便于测试
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

        修改时间: 2026-03-17
        修改者: TraeAI
        任务: 优化云端模型日志，显示更多调用信息
        修改内容: 添加 novel_id、thinking_enabled 参数到日志
        """
        if is_cloud:
            logger.info(
                "[云端模型] {} 开始: novel_id={} task_type={} model={} count={} thinking_enabled={}",
                log_type,
                self._novel_id,
                self._task_type,
                self._config.model,
                count,
                self._config.thinking_enabled,
            )
        else:
            logger.debug(
                "{} start: novel_id={} task_type={} model={} count={} thinking_enabled={}",
                log_type,
                self._novel_id,
                self._task_type,
                self._config.model,
                count,
                self._config.thinking_enabled,
            )

    # _build_json_schema 方法已移至 BaseModelClient 基类
    # 创建时间: 2026-03-17
    # 修改者: TraeAI
    # 任务: code-quality-refactor - 提取API调用基类

    def _call_disambiguate_api(
        self,
        messages: List[Dict[str, str]],
        log_type: str,
    ) -> DisambiguateResponseModel:
        """
        创建时间: 2026-03-13
        创建者: TraeAI
        任务: refactor-model-interaction-layer
        说明: 统一调用消歧API，处理响应字符串/对象两种情况

        修改时间: 2026-03-16
        修改者: TraeAI
        任务: 重构本地消歧客户端集成 Instructor
        修改内容: 使用 Instructor 实现结构化输出，直接返回 DisambiguateResponseModel

        修改时间: 2026-03-17
        修改者: TraeAI
        任务: 移除 Instructor 依赖
        修改内容: 使用 LiteLLM 的 JSON Schema 模式替代 Instructor
        """
        if not self._config.model:
            raise ValueError("model is required")

        if self._client is None:
            raise ValueError("client is required")

        model_name = get_model_with_provider(self._config.model, self._config)

        request_params: dict[str, Any] = {
            "model": model_name,
            "messages": cast(Any, messages),
            "temperature": self._config.temperature,
            "top_p": self._config.top_p,
            "presence_penalty": self._config.presence_penalty,
            "response_format": self._build_json_schema(DisambiguateResponseModel),
        }

        # 使用tiktoken估算prompt token数量
        model_for_token_count = self._config.model or "gpt-4"
        prompt_tokens = count_messages_tokens(messages, model_for_token_count)

        # 使用流式模式并实时输出到控制台（仅云端API）
        is_cloud = self._is_cloud_api()
        response = self._call_api_stream(request_params, is_cloud=is_cloud)

        # 提取 thinking_content（如果存在）
        thinking_content = None
        if hasattr(response, "choices") and response.choices:
            message = response.choices[0].message
            thinking_content = getattr(message, "reasoning_content", None)
            if thinking_content:
                logger.debug(f"Extracted thinking_content: {len(thinking_content)} chars")

        parsed_response = self._parse_structured_response(response, DisambiguateResponseModel)

        # 将 thinking_content 附加到响应对象以便日志记录
        if thinking_content:
            parsed_response._thinking_content = thinking_content

        # 估算completion token并记录token使用
        response_content = (
            response.choices[0].message.content if hasattr(response, "choices") and response.choices else ""
        )
        completion_tokens = count_tokens(response_content, model_for_token_count)
        total_tokens = prompt_tokens + completion_tokens

        self._record_token_usage_estimated(
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=total_tokens,
            call_type=log_type,
        )

        return parsed_response

    def _call_api_stream(self, request_params: dict[str, Any], is_cloud: bool = False) -> Any:
        """
        流式API调用

        创建时间: 2026-03-17
        创建者: TraeAI
        任务: API控制台流式输出
        说明: 使用流式模式调用API，实时输出到控制台（仅云端API）

        修改时间: 2026-03-17
        修改者: TraeAI
        任务: code-quality-refactor - 使用基类 _call_api_stream 方法
        """
        return self._call_api_stream(request_params, is_cloud)

    # _parse_structured_response 方法已移至 BaseModelClient 基类
    # 创建时间: 2026-03-17
    # 修改者: TraeAI
    # 任务: code-quality-refactor - 提取API调用基类

    def _process_disambiguate_response(
        self,
        response: DisambiguateResponseModel,
        is_cloud: bool,
        log_type: str,
    ) -> DisambiguateResponseModel:
        """
        创建时间: 2026-03-13
        创建者: TraeAI
        任务: refactor-model-interaction-layer
        说明: 统一处理消歧响应，提取thinking内容，记录响应日志

        修改时间: 2026-03-16
        修改者: TraeAI
        任务: 重构本地消歧客户端集成 Instructor
        修改内容: 简化方法，Instructor 已返回结构化模型，无需手动解析

        修改时间: 2026-03-17
        修改者: TraeAI
        任务: 优化云端模型日志，显示更多调用信息
        修改内容: 添加 novel_id 参数到日志
        """
        alias_count = len(response.alias_map)

        if is_cloud:
            logger.info(
                "[云端模型] {} 响应: novel_id={} alias_count={}",
                log_type,
                self._novel_id,
                alias_count,
            )
        else:
            logger.info(
                "{} response: novel_id={} alias_count={}",
                log_type,
                self._novel_id,
                alias_count,
            )

        return response

    def _log_disambiguate_result(
        self,
        messages: List[Dict[str, str]],
        response_data: DisambiguateResponseModel,
        metadata: Dict[str, Any],
    ) -> None:
        """
        创建时间: 2026-03-13
        创建者: TraeAI
        任务: refactor-model-interaction-layer
        说明: 统一记录消歧结果日志到 analysis_logger

        修改时间: 2026-03-16
        修改者: TraeAI
        任务: 重构本地消歧客户端集成 Instructor
        修改内容: 适配 DisambiguateResponseModel，简化日志记录

        修改时间: 2026-03-17
        修改者: TraeAI
        任务: 添加 thinking_content 记录
        修改内容: 从响应对象提取并记录 thinking_content
        """
        if not self._analysis_logger:
            return

        # 将 Python dict 转换为标准 JSON 格式（双引号）
        import json

        response_content = json.dumps(response_data.alias_map, ensure_ascii=False)

        # 添加 thinking_content 到 metadata（如果存在）
        thinking_content = getattr(response_data, "_thinking_content", None)
        if thinking_content:
            metadata["thinking_content"] = thinking_content
            metadata["thinking_format"] = "reasoning_content"
            metadata["thinking_tokens"] = len(thinking_content) // 2

        self._analysis_logger.log_prompt(
            messages=messages,
            response=response_content,
            metadata=metadata,
            chunk_id=None,
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

        修改时间: 2026-03-16
        修改者: TraeAI
        任务: 重构本地消歧客户端集成 Instructor
        修改内容: 使用 Instructor 结构化输出，简化结果处理
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

            result = self._build_result_from_response(response_data, candidates)

            logger.debug("disambiguate_characters complete")
            return result
        except Exception as e:
            logger.error("disambiguate_characters unexpected error: {}", str(e))
            from litellm.exceptions import APIConnectionError as LiteLLMAPIConnectionError

            if isinstance(e, LiteLLMAPIConnectionError):
                raise ConnectionError(str(e)) from e
            raise

    def _build_result_from_response(
        self,
        response_data: DisambiguateResponseModel,
        candidates: List[str] | List[Dict[str, int]],
    ) -> Dict[str, str]:
        """
        创建时间: 2026-03-16
        创建者: TraeAI
        任务: 重构本地消歧客户端集成 Instructor
        说明: 从 DisambiguateResponseModel 构建结果字典，确保所有候选名都有映射
        """
        name_list: list[str] = []
        if candidates and isinstance(candidates[0], dict):
            dict_candidates = cast(list[dict[str, int]], candidates)
            name_list = [str(c["name"]) for c in dict_candidates]
        else:
            str_candidates = cast(list[str], candidates)
            name_list = list(str_candidates)

        result: dict[str, str] = {}
        for name in name_list:
            if name in response_data.alias_map:
                result[name] = str(response_data.alias_map[name])
            else:
                result[name] = name
        return result

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

        修改时间: 2026-03-16
        修改者: TraeAI
        任务: 重构本地消歧客户端集成 Instructor
        修改内容: 使用 Instructor 结构化输出，简化结果处理
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

            result = self._build_result_from_response(response_data, anonymous_names)

            logger.debug("disambiguate_anonymous complete")
            return result
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
