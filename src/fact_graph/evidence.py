"""图与树共用的原文证据格式转换，不拥有状态或写入事务"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from src.utils.identity import text_digest


@dataclass(frozen=True, slots=True)
class EvidenceParagraph:
    """保存贡献携带的精确原文和坐标，不访问 work 或 agent 对象"""

    chapter_id: int
    paragraph_id: int
    text: str
    local_start_char: int
    local_end_char: int


def evidence_for(rows: Sequence[EvidenceParagraph], paragraph_id: int | None = None) -> list[dict[str, Any]]:
    """完整证据内嵌在各域记录中，不依赖全局证据字典"""
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
