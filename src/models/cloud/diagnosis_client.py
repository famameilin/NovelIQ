"""
创建时间: 2026-03-12
创建者: TraeAI
任务: 项目文件结构整理与拆解 - 从 client.py 拆分云端诊断客户端

本模块包含云端诊断相关的模型客户端，负责对小说进行整体诊断分析。

修改时间: 2026-03-12
修改者: TraeAI
修改内容: 添加重试机制，当JSON解析失败时自动重试
"""

from __future__ import annotations

import json
import time
from typing import Any, Dict, List, Optional

from loguru import logger

from src.config import TaskModelConfig
from src.config.analysis_logger import AnalysisLogger

from .base import BaseCloudModelClient, TokenUsageCallback
from .schema import CloudAnalysis


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

        last_error: Exception | None = None
        for attempt in range(1, self.MAX_RETRIES + 1):
            try:
                result = self._diagnose_once(payload, messages, novel_id)
                if attempt > 1:
                    logger.info("[云端模型] diagnose 重试成功: attempt={}/{}", attempt, self.MAX_RETRIES)
                return result
            except ValueError as e:
                last_error = e
                logger.warning(
                    "[云端模型] diagnose 失败 (attempt {}/{}): {}",
                    attempt,
                    self.MAX_RETRIES,
                    str(e),
                )
                if attempt < self.MAX_RETRIES:
                    logger.info("[云端模型] diagnose 将在 {} 秒后重试...", self.RETRY_DELAY_SECONDS)
                    time.sleep(self.RETRY_DELAY_SECONDS)

        raise ValueError(f"云端诊断失败，已重试 {self.MAX_RETRIES} 次: {last_error}")

    def _diagnose_once(self, payload: dict, messages: List[Dict[str, str]], novel_id: Any) -> CloudAnalysis:
        """单次诊断尝试"""
        request_params = self._build_request_params(messages)
        response = self._client.chat.completions.create(**request_params)

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

        if self._analysis_logger:
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

            self._analysis_logger.log_cloud_prompt(
                messages=messages,
                response=content_clean,
                metadata=log_metadata,
            )

        parsed = self._parse_response(content_clean)
        if isinstance(parsed, dict):
            result = self._build_analysis(parsed, novel_id)

            novel_id_str = novel_id if isinstance(novel_id, str) else None
            self._record_token_usage(response, novel_id_str or "unknown", "diagnosis")

            if self._analysis_logger:
                self._analysis_logger.write_summary(
                    {
                        "novel_id": novel_id,
                        "analysis_type": "cloud_diagnose",
                        "result": result.to_dict(),
                    }
                )
            return result
        logger.error("cloud diagnose response not json, content: {}", content_clean[:500] if content_clean else "empty")
        raise ValueError("云端模型返回非JSON格式响应，诊断失败")

    def _build_messages(self, payload: dict) -> List[Dict[str, str]]:
        from src.config import settings

        prompt = json.dumps(payload, ensure_ascii=False)
        system_prompt = settings.prompts.cloud_diagnose_system
        return [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": prompt},
        ]

    def _build_analysis(self, parsed: dict, novel_id: Any) -> CloudAnalysis:
        value_logic_type = parsed.get("value_logic_type")
        if value_logic_type is not None:
            valid_types = ("善义有价值", "强者为王", "混合型")
            if value_logic_type not in valid_types:
                logger.warning("invalid value_logic_type: {}, setting to None", value_logic_type)
                value_logic_type = None
        power_stance_score = parsed.get("power_stance_score")
        if power_stance_score is not None:
            try:
                power_stance_score = int(power_stance_score)
            except (ValueError, TypeError):
                logger.warning("invalid power_stance_score: {}, setting to None", power_stance_score)
                power_stance_score = None
        common_people_dignity = parsed.get("common_people_dignity")
        if common_people_dignity is not None:
            try:
                common_people_dignity = int(common_people_dignity)
            except (ValueError, TypeError):
                logger.warning("invalid common_people_dignity: {}, setting to None", common_people_dignity)
                common_people_dignity = None
        cultural_depth_score = parsed.get("cultural_depth_score")
        if cultural_depth_score is not None:
            try:
                cultural_depth_score = int(cultural_depth_score)
            except (ValueError, TypeError):
                logger.warning("invalid cultural_depth_score: {}, setting to None", cultural_depth_score)
                cultural_depth_score = None

        arc_scores_raw = parsed.get("arc_scores", [])
        arc_scores: list[float] | dict[str, float]
        if isinstance(arc_scores_raw, dict):
            arc_scores = arc_scores_raw
        else:
            arc_scores = list(arc_scores_raw) if arc_scores_raw else []

        emotion_curve_type = parsed.get("emotion_curve_type")
        valid_emotion_types = ("白手起家", "伊卡洛斯", "落坑爬出", "持续下降", "灰姑娘", "俄狄浦斯")
        if emotion_curve_type is not None and emotion_curve_type not in valid_emotion_types:
            logger.warning("invalid emotion_curve_type: {}, setting to None", emotion_curve_type)
            emotion_curve_type = None

        return CloudAnalysis(
            novel_id=novel_id if isinstance(novel_id, str) else None,
            foreshadow_rate=parsed.get("foreshadow_rate"),
            arc_scores=arc_scores,
            narrative_type=parsed.get("narrative_type"),
            topic_labels=list(parsed.get("topic_labels", [])),
            diagnosis=parsed.get("diagnosis"),
            value_logic_type=value_logic_type,
            value_logic_reason=parsed.get("value_logic_reason"),
            power_stance_score=power_stance_score,
            power_stance_reason=parsed.get("power_stance_reason"),
            common_people_dignity=common_people_dignity,
            dignity_reason=parsed.get("dignity_reason"),
            cultural_depth_score=cultural_depth_score,
            cultural_depth_reason=parsed.get("cultural_depth_reason"),
            emotion_curve_type=emotion_curve_type,
        )
