"""
JSON解析工具模块

说明: 提取JSON解析相关逻辑
"""

from __future__ import annotations

import json
import re
from typing import Any

from loguru import logger


def try_parse_json(content: str) -> dict[str, Any] | None:
    """
    尝试解析 JSON，支持不完整的 JSON 和带尾随逗号的 JSON
    """
    # 首先尝试标准 json 解析
    try:
        data = json.loads(content)
        if isinstance(data, dict):
            return data
    except json.JSONDecodeError:
        pass

    # 尝试使用 json5 解析（支持尾随逗号、注释等）
    try:
        import json5

        data = json5.loads(content)
        if isinstance(data, dict):
            logger.debug("json parsed by json5 (trailing comma supported)")
            return data
    except Exception:
        pass

    # 尝试使用 streamingjson 修复不完整的 JSON
    try:
        import streamingjson

        lexer = streamingjson.Lexer()
        lexer.append_string(content)
        fixed = lexer.complete_json()
        data = json.loads(fixed)
        if isinstance(data, dict):
            logger.debug("json repaired by streamingjson")
            return data
    except Exception:
        pass

    # 尝试使用 fix_json 作为后备
    fixed = fix_json(content)
    if fixed is not None:
        try:
            data = json.loads(fixed)
            if isinstance(data, dict):
                logger.debug("json repaired successfully")
                return data
        except json.JSONDecodeError:
            pass
    logger.warning("json parse failed, content preview: {}", content[:200])
    return None


def fix_json(content: str) -> str | None:
    """
    修复不完整的或格式错误的 JSON
    """
    # 移除 think 块，避免提取到思考内容中的 JSON
    content = re.sub(r"<think>[\s\S]*?</think>\s*", "", content)

    json_match = re.search(r"\{[\s\S]*\}", content)
    if json_match:
        extracted = json_match.group(0)
        try:
            json.loads(extracted)
            logger.debug("json extracted from mixed content")
            return extracted
        except json.JSONDecodeError:
            pass
    fixed = content.strip()
    if fixed.startswith("```json"):
        fixed = fixed[7:]
    elif fixed.startswith("```"):
        fixed = fixed[3:]
    if fixed.endswith("```"):
        fixed = fixed[:-3]
    fixed = fixed.strip()
    if not fixed.startswith("{"):
        start = fixed.find("{")
        if start != -1:
            fixed = fixed[start:]
    if not fixed.endswith("}"):
        end = fixed.rfind("}")
        if end != -1:
            fixed = fixed[: end + 1]
    # 移除尾随逗号（json5 已经处理，这里保留作为后备）
    fixed = re.sub(r",\s*}", "}", fixed)
    fixed = re.sub(r",\s*]", "]", fixed)
    # 注意：移除了有问题的引号转义正则表达式
    # 原代码：fixed = re.sub(r'(?<!\\)"(?![\s:,\}\]])', '\\"', fixed)
    # 这个正则表达式会错误地转义所有 JSON 引号
    if fixed and fixed.startswith("{") and fixed.endswith("}"):
        logger.debug("json fix applied: removed markdown/code blocks, trailing commas")
        return fixed
    return None
