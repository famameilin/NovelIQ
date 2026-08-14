"""章节结构解析的数据类型"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class ChapterLevel(StrEnum):
    """章节层级（对应 chapters 表 level 列的取值）"""

    PART = "part"
    VOLUME = "volume"
    CHAPTER = "chapter"
    SECTION = "section"
    HUI = "hui"
    ESSAY = "essay"
    EXTRA = "extra"
    PREFACE = "preface"
    AUTO = "auto"


@dataclass
class ChapterCandidate:
    """阶段一/二产出的候选章节（confidence 随评分逐步调整）"""

    level: ChapterLevel
    title: str
    label: str
    display_title: str
    display_index_label: str | None
    number: int | None
    start_char: int
    body_start_char: int
    confidence: float = 1.0


@dataclass
class ChapterData:
    """解析产出的最终章节（chapter_id/sequence 在 finalize 阶段按出现顺序分配）"""

    chapter_id: int
    sequence: int
    level: ChapterLevel
    title: str
    display_title: str
    display_index_label: str | None
    number: int | None
    title_start_char: int
    start_char: int
    end_char: int
