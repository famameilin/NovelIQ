"段落写入与检索使用的普通记录"

from dataclasses import dataclass


@dataclass(frozen=True)
class KeywordMatchRow:
    "关键词检索段落 DTO，携带命中的关键词明细与全文定位"

    paragraph_id: int
    chapter_id: int
    paragraph_index: int
    paragraph_text: str
    local_start_char: int
    local_end_char: int
    global_start_char: int
    global_end_char: int
    matched_keywords: tuple[str, ...]
    match_count: int
