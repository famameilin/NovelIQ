"""
解析工具模块

创建时间: 2026-03-18
创建者: TraeAI
任务: code-quality-refactor - Task 9 拆分parser.py
说明: 提取通用解析工具函数
"""

from __future__ import annotations

import re

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

    def _extract_name(line: str) -> str:
        if "：" in line:
            line = line.split("：")[0].strip()
        elif ":" in line:
            line = line.split(":")[0].strip()
        for sep in ["（", "(", "）", ")"]:
            if sep in line:
                return line.split(sep)[0].strip()
        return line.strip()

    if active_entities.strip() in {"[]", "[ ]"}:
        return []

    if "\n" in active_entities:
        for line in active_entities.split("\n"):
            line = line.strip()
            if not line:
                continue
            if line.startswith("【") and line.endswith("】"):
                continue
            if line.startswith("- "):
                name = _extract_name(line[2:].strip())
            else:
                name = _extract_name(line)
            if name and name not in {"[]", "[ ]"}:
                names.append(name)
    else:
        for part in re.split(r"[，,]", active_entities):
            part = part.strip()
            if not part or part in {"[]", "[ ]"}:
                continue
            name = _extract_name(part)
            if name:
                names.append(name)

    logger.debug(
        "Parsed active_entities: {} names extracted: {}",
        len(names),
        names,
    )
    return names
