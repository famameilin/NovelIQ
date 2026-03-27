"""
创建时间: 2025-03-11
创建者: TraeAI
任务: 云端模型客户端

修改时间: 2026-03-11
修改者: TraeAI
修改内容: 将所有云端模型相关日志提升为info等级，添加prompt和返回内容的控制台打印

修改时间: 2026-03-12
修改者: TraeAI
修改内容: 修复诊断失败时静默返回空结果导致任务状态错误标记为completed的问题
- 当云端模型返回非JSON响应时，抛出ValueError异常而非静默返回空CloudAnalysis
- 这样可以让上层正确捕获异常并将任务标记为failed

修改时间: 2026-03-12
修改者: TraeAI
修改内容: 项目文件结构整理与拆解 - 重构为兼容层
- 将诊断功能委托给 DiagnosisClient
- 保持原有接口不变，确保向后兼容

修改时间: 2026-03-23
修改者: TraeAI
任务: unify-model-client-architecture
修改内容: 
- 移除 CloudDisambiguationClient 依赖（已废弃，统一使用 DisambiguationClient）
- 使用统一的 DiagnosisClient（从 src.models.diagnosis 导入）
"""

from __future__ import annotations

from typing import Any

from src.config import TaskModelConfig
from src.config.analysis_logger import AnalysisLogger
from src.models.diagnosis import DiagnosisClient
from src.models.disambiguation import DisambiguationClient
from src.models.disambiguation_types import NameCountCandidate

from .base import CloudModelClient, NullCloudModelClient, TokenUsageCallback, make_empty_analysis
from .schema import CloudAnalysis


class ConfiguredCloudModelClient(CloudModelClient):
    """
    配置化的云端模型客户端

    这是一个兼容层，提供诊断功能。消歧功能已统一使用 DisambiguationClient。
    保持原有接口不变，确保向后兼容。
    """

    def __init__(
        self,
        config: TaskModelConfig | None = None,
        client: Any | None = None,
        analysis_logger: AnalysisLogger | None = None,
        token_usage_callback: TokenUsageCallback | None = None,
        novel_id: str | None = None,
    ) -> None:
        self._diagnosis_client = DiagnosisClient(
            config=config,
            client=client,
            analysis_logger=analysis_logger,
            token_usage_callback=token_usage_callback,
            novel_id=novel_id,
        )
        self._disambiguation_client = DisambiguationClient(
            task_type="incremental_disambig",
            config=config,
            client=client,
            analysis_logger=analysis_logger,
            token_usage_callback=token_usage_callback,
            novel_id=novel_id,
        )
        self._config = self._diagnosis_client._config
        self._analysis_logger = analysis_logger
        self._token_usage_callback = token_usage_callback
        self._novel_id = novel_id

    def diagnose(self, payload: dict) -> CloudAnalysis:
        return self._diagnosis_client.diagnose(payload)

    def disambiguate_characters(
        self,
        candidates: list[NameCountCandidate],
        context_sentences: dict[str, str] | None = None,
        existing_names: list[str] | None = None,
        rag_hint: str | None = None,
    ) -> dict[str, str]:
        result = self._disambiguation_client.disambiguate_characters(
            candidates=candidates,
            context_sentences=context_sentences,
            existing_names=existing_names,
            rag_hint=rag_hint,
        )
        return result.canonical_decisions


__all__ = [
    "CloudModelClient",
    "ConfiguredCloudModelClient",
    "NullCloudModelClient",
    "make_empty_analysis",
    "TokenUsageCallback",
]
