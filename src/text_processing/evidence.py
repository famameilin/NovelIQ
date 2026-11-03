"""原文段落、引用坐标与证据摘要"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator

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


class StrictModel(BaseModel):
    "原文引用拒绝额外字段"

    model_config = ConfigDict(extra="forbid", use_enum_values=True)


class SourceReference(StrictModel):
    """跨章寻址只依赖已经存在的原文，不依赖其他 Agent 的产出"""

    chapter_id: int = Field(gt=0)
    paragraph_id: int = Field(ge=0)
    char_start: int = Field(ge=0)
    char_end: int = Field(gt=0)
    text_hash: str

    @model_validator(mode="after")
    def validate_span(self) -> SourceReference:
        if self.char_end <= self.char_start:
            raise ValueError("原文引用必须是非空区间")
        return self

