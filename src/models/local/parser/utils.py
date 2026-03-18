"""
解析工具模块

创建时间: 2026-03-18
创建者: TraeAI
任务: code-quality-refactor - Task 9 拆分parser.py
说明: 提取通用解析工具函数
"""

from __future__ import annotations

from loguru import logger


def parse_active_entities(active_entities: str | None) -> list[str]:
    """
    解析活跃实体字符串

    创建时间: 2026-03-13
    创建者: TraeAI
    任务: refactor-model-interaction-layer
    迁移自: annotation_client.py::_parse_active_entities

    Args:
        active_entities: 活跃实体字符串，支持多种格式

    Returns:
        解析后的人名列表
    """
    if not active_entities:
        return []
    names: list[str] = []

    if "\n" in active_entities and "- " in active_entities:
        for line in active_entities.split("\n"):
            line = line.strip()
            if line.startswith("- "):
                name_part = line[2:]
                if "（" in name_part:
                    name = name_part.split("（")[0].strip()
                elif "：" in name_part:
                    name = name_part.split("：")[0].strip()
                elif ":" in name_part:
                    name = name_part.split(":")[0].strip()
                else:
                    name = name_part.strip()
                if name:
                    names.append(name)
    elif "\n" in active_entities:
        pass
    else:
        for part in active_entities.split(","):
            part = part.strip()
            if ":" in part:
                name = part.split(":")[0].strip()
            else:
                name = part
            if name:
                names.append(name)

    logger.debug(
        "Parsed active_entities: {} names extracted: {}",
        len(names),
        names,
    )
    return names
