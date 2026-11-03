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


def failed_view(op: dict[str, Any]) -> dict[str, Any]:
    """用于把逐 op 记录渲染成模型可见的失败清单（按 op 序号与源码行定位）"""
    body: dict[str, Any] = {"op": op["op_index"], "line": op["source_line"], "tool": op["tool_name"]}
    for key, source in (
        ("record", "record"),
        ("field", "field"),
        ("actual", "actual"),
        ("code", "error_code"),
        ("expected", "expected"),
        ("message", "message"),
    ):
        value = op.get(source)
        if value is not None:
            body[key] = value
    return body

