"""
本模块包含日志相关的配置数据类。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class LoggingModuleSettings:
    """日志模块配置"""

    file: str = ""
    level: str = "INFO"


@dataclass
class LoggingSettings:
    """日志配置"""

    console_level: str = "INFO"
    file_level: str = "DEBUG"
    log_dir: str = "logs"
    rotation: str = "10 MB"
    retention: str = "7 days"
    compression: str = "zip"
    modules: dict[str, LoggingModuleSettings] = field(default_factory=dict)
    third_party_level: str = "WARNING"
    json_parse_preview_chars: int = 200


def _parse_logging_settings(data: dict[str, Any] | None) -> LoggingSettings:
    """解析日志配置"""
    if not data:
        return LoggingSettings()

    modules_data = data.get("modules", {})
    modules = {
        k: LoggingModuleSettings(file=v.get("file", ""), level=v.get("level", "INFO")) for k, v in modules_data.items()
    }

    return LoggingSettings(
        console_level=data.get("console_level", "INFO"),
        file_level=data.get("file_level", "DEBUG"),
        log_dir=data.get("log_dir", "logs"),
        rotation=data.get("rotation", "10 MB"),
        retention=data.get("retention", "7 days"),
        compression=data.get("compression", "zip"),
        modules=modules,
        third_party_level=data.get("third_party_level", "WARNING"),
        json_parse_preview_chars=data.get("json_parse_preview_chars", 200),
    )
