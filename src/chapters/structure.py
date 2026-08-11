"""阶段三：结构决策

过滤低置信度候选 → 按相邻候选切分正文 → 空章节保留目录条目但不产出正文 →
开篇正文自动命名（楔子/序言）→ 无结构时自动分章兜底 → 边界安全钳制。
"""

from __future__ import annotations

from loguru import logger

from src.chapters.constants import (
    PRELIMINARY_TITLE_RE,
    ChapterConfig,
)
from src.chapters.models import ChapterCandidate, ChapterData, ChapterLevel


def decide_structure(
    text: str,
    candidates: list[ChapterCandidate],
    prologue_start: int,
    config: ChapterConfig | None = None,
) -> list[ChapterData]:
    """由候选产出最终章节列表；无可靠结构时返回空列表（交由自动分章兜底）"""
    config = config or ChapterConfig()
    qualifying = [c for c in candidates if c.confidence >= config.confidence_threshold]
    if len(qualifying) < config.min_candidate_count:
        return []

    chapters: list[ChapterData] = []
    for index, candidate in enumerate(qualifying):
        body_start = candidate.body_start_char
        body_end = qualifying[index + 1].start_char if index + 1 < len(qualifying) else len(text)
        if not text[body_start:body_end].strip():
            logger.warning(
                "章节「{}」无正文，已跳过该空章节（目录中仍保留）",
                candidate.title,
            )
        chapters.append(
            ChapterData(
                chapter_id=0,
                sequence=0,
                level=candidate.level,
                title=candidate.title,
                display_title=candidate.display_title,
                display_index_label=candidate.display_index_label,
                number=candidate.number,
                start_char=body_start,
                end_char=body_end,
            )
        )

    if not chapters:
        return []

    _drop_trailing_empty_chapters(text, chapters)
    _insert_prologue(text, chapters, prologue_start, config)
    if not any(text[ch.start_char:ch.end_char].strip() for ch in chapters):
        return []
    return chapters


def _drop_trailing_empty_chapters(text: str, chapters: list[ChapterData]) -> None:
    """移除文末零长度章节（下一章预告/断章残留），中间空章节保留目录条目"""
    while len(chapters) > 1 and not text[chapters[-1].start_char : chapters[-1].end_char].strip():
        dropped = chapters.pop()
        logger.warning(
            "文末章节「{}」无正文，判定为预告/断章残留，已从目录移除",
            dropped.title,
        )


def _insert_prologue(
    text: str,
    chapters: list[ChapterData],
    prologue_start: int,
    config: ChapterConfig,
) -> None:
    """开篇正文超过阈值时插入自动命名（楔子/序言）的前置章节"""
    first = chapters[0]
    if prologue_start >= first.start_char:
        return
    prologue_text = text[prologue_start:first.start_char]
    if len(prologue_text.strip()) <= config.prologue_min_chars:
        return
    title = guess_preliminary_title(prologue_text) or config.prologue_default_title
    chapters.insert(
        0,
        ChapterData(
            chapter_id=0,
            sequence=0,
            level=ChapterLevel.PREFACE,
            title=title,
            display_title=title,
            display_index_label=None,
            number=None,
            start_char=prologue_start,
            end_char=first.start_char,
        ),
    )


def guess_preliminary_title(text: str) -> str | None:
    """用开篇标题正则猜测前置章节名称"""
    for line in text.splitlines():
        match = PRELIMINARY_TITLE_RE.match(line.strip())
        if match:
            return match.group(1)
    return None


def auto_split(text: str, config: ChapterConfig | None = None) -> list[ChapterData]:
    """自动分章兜底：按固定字数在段落/句子边界切分（对齐原 _chunk_simple 策略）"""
    config = config or ChapterConfig()
    max_chars = config.fallback_chunk_size

    if len(text) <= max_chars:
        return [_make_auto_chapter(0, len(text), config)]

    chapters: list[ChapterData] = []
    start = 0
    while start < len(text):
        end = min(start + max_chars, len(text))
        if end < len(text):
            paragraph_end = text.rfind("\n\n", start, end)
            if paragraph_end > start + max_chars * 0.5:
                end = paragraph_end
            else:
                sentence_end = text.rfind("。", start, end)
                if sentence_end > start + max_chars * 0.5:
                    end = sentence_end + 1
        if text[start:end].strip():
            chapters.append(_make_auto_chapter(start, end, config))
        start = end
    return chapters


def _make_auto_chapter(
    start: int,
    end: int,
    config: ChapterConfig,
) -> ChapterData:
    """构造一条自动分章条目"""
    return ChapterData(
        chapter_id=0,
        sequence=0,
        level=ChapterLevel.AUTO,
        title=config.fallback_title,
        display_title=config.fallback_title,
        display_index_label=None,
        number=None,
        start_char=start,
        end_char=end,
    )


def finalize(text: str, chapters: list[ChapterData]) -> list[ChapterData]:
    """边界安全钳制 + 按出现顺序分配 chapter_id/sequence"""
    result: list[ChapterData] = []
    for index, chapter in enumerate(chapters, start=1):
        start = max(0, min(chapter.start_char, len(text)))
        end = max(start, min(chapter.end_char, len(text)))
        result.append(
            ChapterData(
                chapter_id=index,
                sequence=index,
                level=chapter.level,
                title=chapter.title,
                display_title=chapter.display_title,
                display_index_label=chapter.display_index_label,
                number=chapter.number,
                start_char=start,
                end_char=end,
            )
        )
    return result
