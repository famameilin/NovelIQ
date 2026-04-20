"""
创建时间: 2026-04-20
修改者: Codex
任务: runtime-behavior-settings
修改内容: 新增运行时行为配置 schema，统一承载 annotation/disambiguation/diagnosis 的流程参数
"""

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

    创建时间: 2026-04-20
    修改者: Codex
    任务: runtime-behavior-settings
    修改内容: 为 runtime 配置统一提供严格整数校验，避免无效值被静默吞掉
    """
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{field_name} 必须是整数，当前值: {value!r}")
    if value < minimum:
        raise ValueError(f"{field_name} 必须大于等于 {minimum}，当前值: {value}")
    return value


@dataclass
class AnnotationRuntimeSettings:
    """
    标注运行时配置

    创建时间: 2026-04-20
    修改者: Codex
    任务: runtime-behavior-settings
    修改内容: 统一承载标注阶段的重试与上下文窗口参数
    """

    phase_max_retries: int = 3
    phase3_max_retries: int = 3
    validation_max_retries: int = 3
    prev_chunks: int = 3
    lookback: int = 10

    def validate(self) -> None:
        """验证标注运行时配置。"""
        self.phase_max_retries = _parse_positive_int(self.phase_max_retries, "runtime.annotation.phase_max_retries")
        self.phase3_max_retries = _parse_positive_int(
            self.phase3_max_retries,
            "runtime.annotation.phase3_max_retries",
        )
        self.validation_max_retries = _parse_positive_int(
            self.validation_max_retries,
            "runtime.annotation.validation_max_retries",
        )
        self.prev_chunks = _parse_positive_int(self.prev_chunks, "runtime.annotation.prev_chunks")
        self.lookback = _parse_positive_int(self.lookback, "runtime.annotation.lookback")


@dataclass
class DisambiguationRuntimeSettings:
    """
    消歧运行时配置

    创建时间: 2026-04-20
    修改者: Codex
    任务: runtime-behavior-settings
    修改内容: 统一承载增量/全量消歧流程的重试参数
    """

    max_retries: int = 3

    def validate(self) -> None:
        """验证消歧运行时配置。"""
        self.max_retries = _parse_positive_int(self.max_retries, "runtime.disambiguation.max_retries")


@dataclass
class DiagnosisRuntimeSettings:
    """
    诊断运行时配置

    创建时间: 2026-04-20
    修改者: Codex
    任务: runtime-behavior-settings
    修改内容: 统一承载诊断流程的重试参数
    """

    max_retries: int = 3

    def validate(self) -> None:
        """验证诊断运行时配置。"""
        self.max_retries = _parse_positive_int(self.max_retries, "runtime.diagnosis.max_retries")


@dataclass
class RuntimeSettings:
    """
    运行时行为配置集合

    创建时间: 2026-04-20
    修改者: Codex
    任务: runtime-behavior-settings
    修改内容: 聚合 annotation/disambiguation/diagnosis 的流程行为配置
    """

    annotation: AnnotationRuntimeSettings = field(default_factory=AnnotationRuntimeSettings)
    disambiguation: DisambiguationRuntimeSettings = field(default_factory=DisambiguationRuntimeSettings)
    diagnosis: DiagnosisRuntimeSettings = field(default_factory=DiagnosisRuntimeSettings)

    def validate(self) -> None:
        """验证整组运行时配置。"""
        self.annotation.validate()
        self.disambiguation.validate()
        self.diagnosis.validate()


def _parse_annotation_runtime_settings(data: dict[str, Any] | None) -> AnnotationRuntimeSettings:
    """
    解析标注运行时配置

    创建时间: 2026-04-20
    修改者: Codex
    任务: runtime-behavior-settings
    修改内容: 从 settings.json 读取 annotation 行为参数并执行严格校验
    """
    json_data = data or {}
    settings = AnnotationRuntimeSettings(
        phase_max_retries=json_data.get("phase_max_retries", 3),
        phase3_max_retries=json_data.get("phase3_max_retries", 3),
        validation_max_retries=json_data.get("validation_max_retries", 3),
        prev_chunks=json_data.get("prev_chunks", 3),
        lookback=json_data.get("lookback", 10),
    )
    settings.validate()
    return settings


def _parse_disambiguation_runtime_settings(data: dict[str, Any] | None) -> DisambiguationRuntimeSettings:
    """
    解析消歧运行时配置

    创建时间: 2026-04-20
    修改者: Codex
    任务: runtime-behavior-settings
    修改内容: 从 settings.json 读取消歧重试参数并执行严格校验
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

    创建时间: 2026-04-20
    修改者: Codex
    任务: runtime-behavior-settings
    修改内容: 从 settings.json 读取诊断重试参数并执行严格校验
    """
    json_data = data or {}
    settings = DiagnosisRuntimeSettings(
        max_retries=json_data.get("max_retries", 3),
    )
    settings.validate()
    return settings


def _parse_runtime_settings(data: dict[str, Any] | None) -> RuntimeSettings:
    """
    解析运行时行为配置集合

    创建时间: 2026-04-20
    修改者: Codex
    任务: runtime-behavior-settings
    修改内容: 统一解析 annotation/disambiguation/diagnosis 的运行时配置
    """
    json_data = data or {}
    settings = RuntimeSettings(
        annotation=_parse_annotation_runtime_settings(json_data.get("annotation")),
        disambiguation=_parse_disambiguation_runtime_settings(json_data.get("disambiguation")),
        diagnosis=_parse_diagnosis_runtime_settings(json_data.get("diagnosis")),
    )
    settings.validate()
    return settings
