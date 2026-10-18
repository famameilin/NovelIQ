"""读回执的字段压缩，原文可截短，引用与坐标保持完整"""

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
_PROTECTED_FIELDS = REFERENCE_FIELDS | {
    "id",
    "record",
    "entity_id",
    "event_id",
    "declaration_id",
    "paragraph_ids",
    "capability",
    "node_id",
    "case_id",
    "producer_invocation_id",
}


def compact_read_result(value: Any, *, max_chars: int) -> tuple[str, int]:
    """按正文字符预算压缩，始终返回可解析 JSON 与实际省略的字符数"""
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except (TypeError, ValueError):
            pass

    def trim(item: Any, budget: list[int], key: str = "") -> Any:
        if key in _PROTECTED_FIELDS:
            return item
        if isinstance(item, dict):
            return {name: trim(child, budget, str(name)) for name, child in item.items()}
        if isinstance(item, (list, tuple)):
            return [trim(child, budget) for child in item]
        if isinstance(item, str):
            size = min(len(item), budget[0])
            budget[0] -= size
            return item[:size]
        return item

    original = json.dumps(value, ensure_ascii=False)
    if len(original) <= max_chars:
        return original, 0
    # 引用字段及 JSON 结构不参与截断，预算不足时也不能损坏 source_ref
    skeleton = json.dumps(trim(value, [0]), ensure_ascii=False)
    projected = json.dumps(trim(value, [max(0, max_chars - len(skeleton))]), ensure_ascii=False)
    return projected, max(0, len(original) - len(projected))


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
