"""
loguru 日志系统初始化（基于 settings.logging 统一配置）
"""

from __future__ import annotations

import sys

from loguru import logger

from .schemas.logging import LoggingSettings
from .settings import settings


def _record_belongs_to_third_party(record) -> bool:
    """2026-08-08 用于识别非本仓库命名空间的第三方日志"""
    return not _record_belongs_to_project(record)


def _record_belongs_to_project(record) -> bool:
    """2026-08-08 用于识别本仓库命名空间的日志（src.*）"""
    name = str(record["name"])
    return name == "src" or name.startswith("src.")


def _module_filter(module_name: str):
    """2026-08-08 用于按模块前缀过滤 loguru 记录"""

    def filter(record) -> bool:
        name = str(record["name"])
        return name == module_name or name.startswith(f"{module_name}.")

    return filter


def setup_logging(config: LoggingSettings | None = None) -> None:
    """
    2026-08-08 用于按 settings.logging 初始化 loguru：
    控制台按 console_level，模块按 modules 各自写文件，统一轮转与压缩
    注意：本函数会先调用 logger.remove() 清除全部现有 handler，
    仅应在进程启动期调用一次，避免误删其他模块已注册的日志 sink
    """
    cfg = config or settings.logging
    logger.remove()

    console_format = (
        "<green>{time:YYYY-MM-DD HH:mm:ss}</green> | "
        "<level>{level: <8}</level> | "
        "<cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> - "
        "<level>{message}</level>"
    )
    file_format = "{time:YYYY-MM-DD HH:mm:ss} | {level: <8} | {name}:{function}:{line} - {message}"

    logger.add(
        sys.stderr,
        level=cfg.console_level.upper(),
        format=console_format,
        filter=_record_belongs_to_project,
    )
    logger.add(
        sys.stderr,
        level=cfg.third_party_level.upper(),
        format=console_format,
        filter=_record_belongs_to_third_party,
    )

    for module_name, module_cfg in cfg.modules.items():
        log_path = f"{cfg.log_dir}/{module_cfg.file}"
        logger.add(
            log_path,
            level=module_cfg.level.upper(),
            rotation=cfg.rotation,
            retention=cfg.retention,
            compression=cfg.compression,
            encoding="utf-8",
            format=file_format,
            filter=_module_filter(module_name),
        )
