
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


def _parse_positive_int(
    value: Any,
    field_name: str,
    *,
    minimum: int = 1,
) -> int:
    """
    解析正整数配置值
    """
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{field_name} 必须是整数，当前值: {value!r}")
    if value < minimum:
        raise ValueError(f"{field_name} 必须大于等于 {minimum}，当前值: {value}")
    return value


@dataclass
class DisambiguationRuntimeSettings:
    """
    消歧运行时配置
    """

    max_retries: int = 3

    def validate(self) -> None:
        """验证消歧运行时配置"""
        self.max_retries = _parse_positive_int(self.max_retries, "runtime.disambiguation.max_retries")


@dataclass
class DiagnosisRuntimeSettings:
    """
    诊断运行时配置
    """

    max_retries: int = 3

    def validate(self) -> None:
        """验证诊断运行时配置"""
        self.max_retries = _parse_positive_int(self.max_retries, "runtime.diagnosis.max_retries")


@dataclass
class RuntimeSettings:
    """
    运行时行为配置集合
    """

    disambiguation: DisambiguationRuntimeSettings = field(default_factory=DisambiguationRuntimeSettings)
    diagnosis: DiagnosisRuntimeSettings = field(default_factory=DiagnosisRuntimeSettings)

    def validate(self) -> None:
        """验证整组运行时配置"""
        self.disambiguation.validate()
        self.diagnosis.validate()


def _parse_disambiguation_runtime_settings(data: dict[str, Any] | None) -> DisambiguationRuntimeSettings:
    """
    解析消歧运行时配置
    """
    json_data = data or {}
    settings = DisambiguationRuntimeSettings(
        max_retries=json_data.get("max_retries", 3),
    )
    settings.validate()
    return settings


def _parse_diagnosis_runtime_settings(data: dict[str, Any] | None) -> DiagnosisRuntimeSettings:
    """
    解析诊断运行时配置
    """
    json_data = data or {}
    settings = DiagnosisRuntimeSettings(
        max_retries=json_data.get("max_retries", 3),
    )
    settings.validate()
    return settings


def _parse_runtime_settings(data: dict[str, Any] | None) -> RuntimeSettings:
    """
    2026-08-03 用于解析当前运行时行为配置并拒绝已退役的标注阶段命名空间
    """
    json_data = data or {}
    if "annotation" in json_data:
        raise ValueError(
            "runtime.annotation 已退役，请使用 analysis.agents.annotation 配置当前标注 Agent"
        )
    settings = RuntimeSettings(
        disambiguation=_parse_disambiguation_runtime_settings(json_data.get("disambiguation")),
        diagnosis=_parse_diagnosis_runtime_settings(json_data.get("diagnosis")),
    )
    settings.validate()
    return settings
