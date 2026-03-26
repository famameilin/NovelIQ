"""
创建时间: 2026-03-12
创建者: TraeAI
任务: 项目文件结构整理与拆解 - 从 client.py 拆分云端诊断客户端

本模块包含云端诊断相关的模型客户端，负责对小说进行整体诊断分析。

修改时间: 2026-03-12
修改者: TraeAI
修改内容: 添加重试机制，当JSON解析失败时自动重试

修改时间: 2026-03-16
修改者: TraeAI
修改内容: 集成 Instructor 实现结构化输出，简化 JSON 解析逻辑

修改时间: 2026-03-17
修改者: TraeAI
任务: 移除 Instructor 依赖
修改内容: 使用 LiteLLM 的 JSON Schema 模式替代 Instructor

修改时间: 2026-03-18
修改者: TraeAI
任务: code-quality-refactor - 统一重试机制
修改内容: 使用 RetryableOperation 替换自定义重试逻辑
"""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional, Type, TypeVar

from loguru import logger
from pydantic import BaseModel

from src.config import TaskModelConfig
from src.config.analysis_logger import AnalysisLogger

from .base import BaseCloudModelClient, TokenUsageCallback
from .schema import CloudAnalysis

T = TypeVar("T", bound=BaseModel)


class DiagnosisClient(BaseCloudModelClient):
    """
    云端诊断客户端

    负责对小说进行整体诊断分析，包括叙事类型、主题、价值观等。
    """

    MAX_RETRIES = 3
    RETRY_DELAY_SECONDS = 2

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

    def diagnose(self, payload: dict) -> CloudAnalysis:
        if not self._config.model:
            raise ValueError("cloud model is required")
        novel_id = payload.get("novel_id")
        messages = payload.get("messages")
        if not isinstance(messages, list):
            messages = self._build_messages(payload)

        logger.info(
            "[云端模型] diagnose 开始: model={} base_url={} novel_id={} messages_count={}",
            self._config.model,
            self._config.base_url,
            novel_id,
            len(messages),
        )

        # 使用 RetryableOperation 执行带重试的调用
        from src.workflows.retry_utils import RetryableOperation

        operation = RetryableOperation(
            max_retries=self.MAX_RETRIES,
            retryable_exceptions=(ValueError,),
            operation_name="cloud_diagnose",
        )

        return operation.execute(self._diagnose_once, payload, messages, novel_id, run_id=payload.get("run_id"), pass_attempt_number=True)

    def _build_json_schema(self, response_model: Type[T]) -> dict[str, Any]:
        """
        构建 JSON Schema 用于结构化输出

        创建时间: 2026-03-17
        创建者: TraeAI
        任务: 移除 Instructor 依赖
        说明: 使用 Pydantic 的 model_json_schema() 方法生成 JSON Schema
        """
        schema = response_model.model_json_schema()
        return {
            "type": "json_schema",
            "json_schema": {
                "name": response_model.__name__,
                "schema": schema,
                "strict": True,
            },
        }

    def _parse_structured_response(self, response: Any, response_model: Type[T]) -> T:
        """
        解析结构化响应

        创建时间: 2026-03-17
        创建者: TraeAI
        任务: 移除 Instructor 依赖
        说明: 从响应中提取 JSON 并解析为 Pydantic 模型
        """
        if not response.choices:
            raise ValueError("Empty response from API")

        content = response.choices[0].message.content
        if not content:
            raise ValueError("Empty content in response")

        try:
            json_data = json.loads(content)
        except json.JSONDecodeError:
            raise ValueError(f"Failed to parse JSON from response: {content[:200]}")

        return response_model.model_validate(json_data)

    def _call_api_stream(self, request_params: dict[str, Any], enable_console_output: bool = True) -> Any:
        """
        流式API调用

        创建时间: 2026-03-17
        创建者: TraeAI
        任务: API控制台流式输出
        说明: 使用流式模式调用API，实时输出到控制台
        """
        if self._client is None:
            raise ValueError("client is required")

        request_params["stream"] = True

        logger.debug("Using streaming mode for diagnosis API call")

        content_chunks: list[str] = []
        reasoning_chunks: list[str] = []
        chunk_count = 0

        # 输出到控制台
        print(f"[Stream] Starting diagnosis API call with model={request_params.get('model', 'unknown')}", flush=True)

        for chunk in self._client.chat.completions.create(**request_params):
            chunk_count += 1
            if chunk.choices:
                delta = chunk.choices[0].delta
                if delta.content:
                    content_chunks.append(delta.content)
                    # 实时输出到控制台
                    print(delta.content, end="", flush=True)
                if hasattr(delta, "reasoning_content") and delta.reasoning_content:
                    reasoning_chunks.append(delta.reasoning_content)
                    # 实时输出 reasoning 到控制台（使用不同颜色）
                    print(f"\033[90m{delta.reasoning_content}\033[0m", end="", flush=True)

        print(f"\n[Stream] Completed: received {chunk_count} chunks", flush=True)

        full_content = "".join(content_chunks)
        full_reasoning = "".join(reasoning_chunks) if reasoning_chunks else None

        # 构建模拟响应对象
        from types import SimpleNamespace

        message = SimpleNamespace(
            content=full_content,
            reasoning_content=full_reasoning,
            role="assistant",
        )
        choice = SimpleNamespace(
            message=message,
            finish_reason="stop",
            index=0,
        )
        response = SimpleNamespace(
            choices=[choice],
            model=request_params.get("model", "unknown"),
        )
        return response

    def _diagnose_once(self, payload: dict, messages: List[Dict[str, str]], novel_id: Any, run_id: str | None = None, attempt_number: int = 1) -> CloudAnalysis:
        """
        单次诊断尝试

        修改时间: 2026-03-16
        修改者: TraeAI
        修改内容: 集成 Instructor 实现结构化输出，简化 JSON 解析逻辑

        修改时间: 2026-03-17
        修改者: TraeAI
        任务: 移除 Instructor 依赖
        修改内容: 使用 LiteLLM 的 JSON Schema 模式替代 Instructor

        修改时间: 2026-03-19
        修改者: TraeAI
        任务: 添加模型交互记录保存
        修改内容: 添加 run_id 和 attempt_number 参数，保存交互记录
        """
        import time

        start_time = time.time()
        request_params = self._build_request_params(messages)
        request_params["response_format"] = self._build_json_schema(CloudAnalysis)

        if self._client is None:
            raise ValueError("client is required")

        # 使用流式模式并实时输出到控制台
        response = self._call_api_stream(request_params)
        result = self._parse_structured_response(response, CloudAnalysis)

        duration_ms = int((time.time() - start_time) * 1000)

        # 保存交互记录到数据库
        if run_id and response:
            try:
                from src.storage.db import get_session_factory
                from src.storage.repositories.model_interaction_repository import ModelInteractionRepository

                Session = get_session_factory()
                session = Session()
                try:
                    repo = ModelInteractionRepository(session)
                    message = response.choices[0].message
                    content_clean, thinking_content = self._extract_response_content(message)
                    prompt_text = "\n\n".join([f"{msg['role']}: {msg['content']}" for msg in messages])

                    repo.save_interaction(
                        run_id=run_id,
                        chunk_id=None,  # diagnose 阶段没有 chunk_id
                        interaction_type="diagnose",
                        phase="diagnose",
                        attempt_number=attempt_number,
                        model_name=self._config.model,
                        model_provider="cloud",
                        prompt=prompt_text,
                        response=content_clean,
                        thinking=thinking_content,
                        response_chars=len(content_clean),
                        thinking_chars=len(thinking_content) if thinking_content else 0,
                        has_thinking=bool(thinking_content and thinking_content.strip()),
                        status="success",
                        duration_ms=duration_ms,
                    )
                finally:
                    session.close()
            except Exception as e:
                logger.warning(f"Failed to save diagnose interaction: {e}")

        if self._analysis_logger and response:
            message = response.choices[0].message
            content_clean, thinking_content = self._extract_response_content(message)

            has_thinking = bool(thinking_content and thinking_content.strip())
            has_response = bool(content_clean and content_clean.strip())

            logger.info(
                "[云端模型] diagnose 响应: has_thinking={} thinking_chars={} has_response={} response_chars={}",
                has_thinking,
                len(thinking_content) if thinking_content else 0,
                has_response,
                len(content_clean),
            )

            from src.models.local.parser import extract_thinking_unified

            extraction = extract_thinking_unified(
                content=message.content or "",
                reasoning_content=getattr(message, "reasoning_content", None),
                support_reasoning_content=True,
                support_think_tags=True,
            )
            log_metadata = {
                "model": self._config.model,
                "novel_id": novel_id,
                "payload_keys": list(payload.keys()),
            }
            if thinking_content:
                log_metadata["thinking_content"] = thinking_content
                log_metadata["thinking_format"] = extraction.thinking_format
                log_metadata["thinking_tokens"] = extraction.thinking_tokens

            self._analysis_logger.log_prompt(
                messages=messages,
                response=content_clean,
                metadata=log_metadata,
            )

        final_result = self._finalize_result(result, novel_id)

        if response:
            novel_id_str = novel_id if isinstance(novel_id, str) else None
            self._record_token_usage(response, novel_id_str or "unknown", "diagnosis")

        if self._analysis_logger:
            self._analysis_logger.write_summary(
                {
                    "novel_id": novel_id,
                    "analysis_type": "cloud_diagnose",
                    "result": final_result.to_dict(),
                }
            )
        return final_result

    def _finalize_result(self, result: CloudAnalysis, novel_id: Any) -> CloudAnalysis:
        """最终化结果，确保 novel_id 正确设置"""
        if isinstance(novel_id, str) and result.novel_id != novel_id:
            return CloudAnalysis(
                novel_id=novel_id,
                foreshadow_rate=result.foreshadow_rate,
                arc_scores=result.arc_scores,
                narrative_type=result.narrative_type,
                topic_labels=result.topic_labels,
                diagnosis=result.diagnosis,
                value_logic_type=result.value_logic_type,
                value_logic_reason=result.value_logic_reason,
                power_stance_score=result.power_stance_score,
                power_stance_reason=result.power_stance_reason,
                common_people_dignity=result.common_people_dignity,
                dignity_reason=result.dignity_reason,
                cultural_depth_score=result.cultural_depth_score,
                cultural_depth_reason=result.cultural_depth_reason,
                emotion_curve_type=result.emotion_curve_type,
            )
        return result

    def _build_messages(self, payload: dict) -> List[Dict[str, str]]:
        from src.config import settings

        prompt = json.dumps(payload, ensure_ascii=False)
        system_prompt = settings.prompts.diagnose
        return [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": prompt},
        ]
