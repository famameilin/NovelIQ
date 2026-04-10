"""
创建时间: 2026-03-23
创建者: TraeAI
任务: unify-model-client-architecture
说明: 统一的诊断客户端，同时支持本地和云端

本模块包含诊断客户端，负责对小说进行整体诊断分析。
修改时间: 2026-03-23
修改者: TraeAI
任务: unify-model-client-architecture
修改内容: 创建统一的 DiagnosisClient，替代 cloud/diagnosis_client.py

修改时间: 2026-03-27
修改者: TraeAI
任务: 简化 diagnosis payload
修改内容: _build_messages 方法移除 common_character_names 相关逻辑，只使用 alias_map

修改时间: 2026-03-27
修改者: TraeAI
任务: 创建统一的模型交互记录接口
修改内容: 使用 record_model_interaction 替代内联保存逻辑
"""

from __future__ import annotations

import json
import time
from typing import Any, TypeVar

from loguru import logger
from pydantic import BaseModel

from src.config import TaskModelConfig
from src.config.analysis_logger import AnalysisLogger
from src.models.cloud.schema import CloudAnalysis
from src.models.interactions import record_model_interaction
from src.models.local.base import BaseModelClient, TokenUsageCallback

T = TypeVar("T", bound=BaseModel)


class DiagnosisClient(BaseModelClient):
    """
    统一诊断客户端

    负责对小说进行整体诊断分析，包括叙事类型、主题、价值观等。
    同时支持本地和云端模型，通过 base_url 自动检测。
    """

    MAX_RETRIES = 3
    RETRY_DELAY_SECONDS = 2

    def __init__(
        self,
        config: TaskModelConfig | None = None,
        client: Any | None = None,
        analysis_logger: AnalysisLogger | None = None,
        token_usage_callback: TokenUsageCallback | None = None,
        novel_id: str | None = None,
        session: Any | None = None,
    ) -> None:
        super().__init__(
            task_type="diagnosis",
            config=config,
            client=client,
            analysis_logger=analysis_logger,
            token_usage_callback=token_usage_callback,
            novel_id=novel_id,
            session=session,
        )

    async def diagnose(self, payload: dict) -> CloudAnalysis:
        if not self._config.model:
            raise ValueError("model is required for diagnosis")
        novel_id = payload.get("novel_id")
        messages = payload.get("messages")
        if not isinstance(messages, list):
            messages = self._build_messages(payload)

        is_cloud = self.is_cloud_api()
        if is_cloud:
            logger.info(
                "[云端模型] diagnose 开始: model={} base_url={} novel_id={} messages_count={}",
                self._config.model,
                self._config.base_url,
                novel_id,
                len(messages),
            )
        else:
            logger.debug(
                "diagnose 开始: model={} base_url={} novel_id={} messages_count={}",
                self._config.model,
                self._config.base_url,
                novel_id,
                len(messages),
            )

        from src.workflows.retry_utils import RetryableOperation

        operation = RetryableOperation(
            max_retries=self.MAX_RETRIES,
            retryable_exceptions=(ValueError,),
            operation_name="diagnosis",
        )

        return await operation.execute(
            self._diagnose_once,
            payload,
            messages,
            novel_id,
            run_id=payload.get("run_id"),
            pass_attempt_number=True,
        )

    def _build_json_schema(self, response_model: type[T]) -> dict[str, Any]:
        schema = response_model.model_json_schema()
        return {
            "type": "json_schema",
            "json_schema": {
                "name": response_model.__name__,
                "schema": schema,
                "strict": True,
            },
        }

    def _parse_structured_response(self, response: Any, response_model: type[T]) -> T:
        if not response.choices:
            raise ValueError("Empty response from API")

        content = response.choices[0].message.content
        if not content:
            raise ValueError("Empty content in response")

        try:
            json_data = json.loads(content)
        except json.JSONDecodeError:
            raise ValueError(f"Failed to parse JSON from response: {content[:200]}") from None

        return response_model.model_validate(json_data)

    async def _call_api(  # type: ignore[override]
        self,
        request_params: dict[str, Any],
        is_cloud: bool = False,
    ) -> Any:
        """
        非流式API调用（async 版本）

        创建时间: 2026-04-09
        创建者: TraeAI
        任务: 支持 AsyncOpenAI
        """
        logger.debug("Using non-streaming mode for diagnosis API call")

        if is_cloud:
            model_name = request_params.get("model", "unknown")
            print(f"[Non-Stream] Starting diagnosis API call with model={model_name}", flush=True)

        response = await self._client.chat.completions.create(**request_params)

        if is_cloud:
            print("\n[Non-Stream] Completed", flush=True)

        return response

    async def _diagnose_once(
        self,
        payload: dict,
        messages: list[dict[str, str]],
        novel_id: Any,
        run_id: str | None = None,
        attempt_number: int = 1,
    ) -> CloudAnalysis:
        start_time = time.time()
        request_params = self._build_request_params(messages)
        request_params["response_format"] = self._build_json_schema(CloudAnalysis)

        if self._client is None:
            raise ValueError("client is required")

        response = await self._call_api(request_params, is_cloud=self.is_cloud_api())
        result = self._parse_structured_response(response, CloudAnalysis)

        duration_ms = int((time.time() - start_time) * 1000)

        if run_id and response:
            message = response.choices[0].message
            content_clean, thinking_content = self._extract_response_content(message)

            record_model_interaction(
                run_id=run_id,
                chunk_id=None,
                interaction_type="diagnose",
                phase="diagnose",
                attempt_number=attempt_number,
                messages=messages,
                response_text=content_clean,
                thinking_content=thinking_content,
                duration_ms=duration_ms,
                model_name=self._config.model,
                model_provider="cloud" if self.is_cloud_api() else "local",
                session=self._session,
            )

        if self._analysis_logger and response:
            message = response.choices[0].message
            content_clean, thinking_content = self._extract_response_content(message)

            has_thinking = bool(thinking_content and thinking_content.strip())
            has_response = bool(content_clean and content_clean.strip())

            logger.info(
                "[模型] diagnose 响应: has_thinking={} thinking_chars={} has_response={} response_chars={}",
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
            self._record_token_usage(response, "diagnosis", chunk_id=None)

        if self._analysis_logger:
            self._analysis_logger.write_summary(
                {
                    "novel_id": novel_id,
                    "analysis_type": "diagnosis",
                    "result": final_result.to_dict(),
                }
            )
        return final_result

    def _finalize_result(self, result: CloudAnalysis, novel_id: Any) -> CloudAnalysis:
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
                narrative_arc_type=result.narrative_arc_type,
                protagonist=result.protagonist,
                main_characters=result.main_characters,
                core_cast=result.core_cast,
            )
        return result

    def _build_messages(self, payload: dict) -> list[dict[str, str]]:
        from src.config import settings

        prompt = json.dumps(payload, ensure_ascii=False)
        system_prompt = settings.prompts.diagnose
        alias_merges = payload.get("alias_merges") or {}
        known_characters = payload.get("known_characters") or []

        if alias_merges:
            naming_rules = [
                "Naming rules:",
                "When alias_merges provides an alias mapping, "
                "always rewrite the alias to its canonical character name "
                "before reasoning or output.",
                "Apply this consistently in arc_scores, topic_labels, "
                "diagnosis, value_logic_reason, power_stance_reason, "
                "dignity_reason, and cultural_depth_reason.",
                f"known_characters={json.dumps(known_characters, ensure_ascii=False)}",
                f"alias_merges={json.dumps(alias_merges, ensure_ascii=False)}",
            ]
            system_prompt = f"{system_prompt}\n\n" + "\n".join(naming_rules)

        return [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": prompt},
        ]


__all__ = ["DiagnosisClient"]
