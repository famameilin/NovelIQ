"""
本模块包含API和路径相关的配置数据类
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class PathSettings:
    """路径配置"""

    upload_dir: Path = field(default_factory=lambda: Path("data/uploads"))
    results_dir: Path = field(default_factory=lambda: Path("outputs"))
    log_dir: Path = field(default_factory=lambda: Path("logs"))
    lexicons_dir: Path = field(default_factory=lambda: Path("data/lexicons"))

    def __post_init__(self) -> None:
        self.upload_dir.mkdir(parents=True, exist_ok=True)
        self.results_dir.mkdir(parents=True, exist_ok=True)
        self.log_dir.mkdir(parents=True, exist_ok=True)


def _parse_path_settings(data: dict[str, Any] | None) -> PathSettings:
    """解析路径配置"""
    if not data:
        return PathSettings()
    return PathSettings(
        upload_dir=Path(data.get("upload_dir", "data/uploads")),
        results_dir=Path(data.get("results_dir", "outputs")),
        log_dir=Path(data.get("log_dir", "logs")),
        lexicons_dir=Path(data.get("lexicons_dir", "data/lexicons")),
    )
