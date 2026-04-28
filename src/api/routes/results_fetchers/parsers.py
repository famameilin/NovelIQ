"""
字段解析工具

说明: 从 results_fetchers.py 拆分，包含字段解析相关函数
"""

from __future__ import annotations

import json
from typing import Any


def _parse_json_field(value: Any) -> Any:
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


def _parse_int_field(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (ValueError, TypeError):
        return None
