from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from pathlib import Path

from loguru import logger


@dataclass(frozen=True)
class LoggingConfig:
    level: str = "DEBUG"
    log_file: Path | None = None
    max_bytes: int = 5_000_000
    backup_count: int = 3
    console: bool = True
    console_log_file: Path | None = None

    @classmethod
    def from_file(cls, path: Path | None = None) -> LoggingConfig:
        config_path = path or Path("config/logging_config.json")
        data = json.loads(config_path.read_text(encoding="utf-8"))
        log_file = data.get("log_file")
        console_log_file = data.get("console_log_file")
        return cls(
            level=str(data.get("level", "DEBUG")).upper(),
            log_file=Path(log_file) if log_file else None,
            max_bytes=int(data.get("max_bytes", 5_000_000)),
            backup_count=int(data.get("backup_count", 3)),
            console=bool(data.get("console", True)),
            console_log_file=Path(console_log_file) if console_log_file else None,
        )

    def validate(self) -> None:
        if self.max_bytes <= 0:
            raise ValueError("max_bytes must be positive")
        if self.backup_count < 0:
            raise ValueError("backup_count must be non-negative")


def setup_logging(config: LoggingConfig | None = None, verbose: bool = False, debug: bool = False) -> tuple[int, int]:
    """
    设置日志系统

    创建时间: 2025-03-11
    创建者: TraeAI
    任务: 小说量化分析 API 服务

    修改时间: 2026-03-12
    修改者: TraeAI
    修改内容: 添加终端日志文件支持，将终端显示的日志单独保存到文件

    返回: (file_handler_id, console_file_handler_id) 文件日志处理器ID和终端日志文件处理器ID
    """
    cfg = config or LoggingConfig.from_file()
    cfg.validate()
    logger.remove()
    if debug:
        level = "DEBUG"
    elif verbose:
        level = "INFO"
    else:
        level = "WARNING"

    console_format = "<green>{time:YYYY-MM-DD HH:mm:ss}</green> | <level>{level: <8}</level> | <cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> - <level>{message}</level>"
    file_format = "{time:YYYY-MM-DD HH:mm:ss} | {level: <8} | {name}:{function}:{line} - {message}"

    console_file_handler_id = -1
    if cfg.console:
        logger.add(
            sys.stderr,
            level=level,
            format=console_format,
        )
        if cfg.console_log_file is not None:
            cfg.console_log_file.parent.mkdir(parents=True, exist_ok=True)
            rotation_mb = cfg.max_bytes / 1_000_000
            console_file_handler_id = logger.add(
                str(cfg.console_log_file),
                level=level,
                rotation=f"{rotation_mb} MB",
                retention=cfg.backup_count,
                encoding="utf-8",
                format=console_format,
            )

    file_handler_id = -1
    if cfg.log_file is not None:
        cfg.log_file.parent.mkdir(parents=True, exist_ok=True)
        rotation_mb = cfg.max_bytes / 1_000_000
        file_handler_id = logger.add(
            str(cfg.log_file),
            level=cfg.level,
            rotation=f"{rotation_mb} MB",
            retention=cfg.backup_count,
            encoding="utf-8",
            format=file_format,
        )
    return file_handler_id, console_file_handler_id
