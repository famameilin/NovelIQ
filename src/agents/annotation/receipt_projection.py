"""读回执的原文授权句柄抽取；回显内容不压缩"""

from __future__ import annotations

import json
from typing import Any

REFERENCE_FIELDS = frozenset(
    {
        "source_ref",
        "chapter_id",
        "paragraph_id",
        "char_start",
        "char_end",
        "text_hash",
    }
)


def read_references(value: Any) -> list[dict[str, Any]]:
    """抽取原文授权句柄，脱离正文回显上限保留"""
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except (TypeError, ValueError):
            return []
    if isinstance(value, dict):
        if value.get("source_ref"):
            return [{key: item for key, item in value.items() if key in REFERENCE_FIELDS}]
        return [reference for item in value.values() for reference in read_references(item)]
    if isinstance(value, (list, tuple)):
        return [reference for item in value for reference in read_references(item)]
    return []
