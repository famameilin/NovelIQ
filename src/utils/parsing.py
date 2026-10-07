"""所属领域的字段契约与结果处理"""

from __future__ import annotations

import json
from typing import Any


def parse_json_field(value: Any) -> Any:
    """解析 JSON 字段，处理可能的异常"""
    if value is None:
        return None
    if isinstance(value, dict | list):
        return value
    if isinstance(value, str):
        try:
            return json.loads(value)
        except (json.JSONDecodeError, TypeError):
            return None
    return None


def parse_int_field(value: Any) -> int | None:
    """解析整数字段，处理可能的异常"""
    if value is None:
        return None
    try:
        return int(value)
    except (ValueError, TypeError):
        return None
