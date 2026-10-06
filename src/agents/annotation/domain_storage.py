"""图与树共用的原文证据格式转换，不拥有状态或写入事务"""

from __future__ import annotations

from typing import Any

from .identity import text_digest


def evidence_for(execution: Any, paragraph_id: int | None = None) -> list[dict[str, Any]]:
    """完整证据内嵌在各域记录中，不依赖全局证据字典"""
    rows = execution.receipt.payload["paragraphs"]
    return [
        {
            "chapter_id": row.chapter_id,
            "paragraph_id": row.paragraph_id,
            "char_start": 0,
            "char_end": len(row.text),
            "text_hash": text_digest(row.text),
        }
        for row in rows
        if paragraph_id is None or row.paragraph_id == paragraph_id
    ]
