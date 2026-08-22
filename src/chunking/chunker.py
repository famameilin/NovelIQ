"""
文本分块模块

分章策略：
1. 优先按章节结构解析（src.chapters）分割：每个章节为一个 chunk，
   保留 chapter_id，无论多长不再切
2. 无法捕捉原始章节时，章节解析器内部回退到固定字数段落分割（自动分章）

不再使用向量相似度（语义分块）作为分块依据。
"""

from __future__ import annotations

import re
from collections.abc import Awaitable, Callable, Iterable, Sequence
from dataclasses import dataclass, replace
from typing import TYPE_CHECKING

from src.chapters.models import ChapterData
from src.chapters.parser import parse_chapters
from src.chapters.preprocess import preprocess_text
from src.chunking.spans import ParagraphSpan

if TYPE_CHECKING:
    from src.api.models.events import StreamEvent

# =============================================================================
# 数据类型
# =============================================================================


@dataclass(frozen=True)
class Chunk:
    """文本块数据类"""

    index: int
    text: str
    start: int
    end: int
    chapter_id: int


def _reindex(chunks: list[Chunk]) -> list[Chunk]:
    """重新索引 chunks"""
    return [
        Chunk(
            index=idx,
            text=chunk.text,
            start=chunk.start,
            end=chunk.end,
            chapter_id=chunk.chapter_id,
        )
        for idx, chunk in enumerate(chunks)
    ]


def _resolve_trimmed_span(text: str, start: int, end: int) -> tuple[int, int, str] | None:
    """
    解析切片在原文中的真实字符范围，并返回去首尾空白后的文本

    chunk 最终落库和对外暴露的 offset 必须对应“实际保留下来的文本”，
    不能继续沿用 strip() 之前的粗边界；否则全文 offset 会系统性偏移
    """
    raw_text = text[start:end]
    stripped_text = raw_text.strip()
    if not stripped_text:
        return None

    leading_ws = len(raw_text) - len(raw_text.lstrip())
    trimmed_end = len(raw_text.rstrip())
    return start + leading_ws, start + trimmed_end, stripped_text


async def chunk_text(
    text: str,
    emitter: Callable[[StreamEvent], Awaitable[None]] | None = None,
) -> list[Chunk]:
    """将文本分割成块（async 版本），保留章节信息；无章节结构时自动分章兜底"""
    chunks, _ = await chunk_text_with_chapters(text, emitter=emitter)
    return chunks


async def chunk_text_with_chapters(
    text: str,
    emitter: Callable[[StreamEvent], Awaitable[None]] | None = None,
) -> tuple[list[Chunk], list[ChapterData]]:
    """
    将文本分割成块并返回章节目录（async 版本）

    返回的 chunk/chapter 偏移均相对 preprocess_text 的输出，两者共用同一坐标空间。
    """
    if not text.strip():
        return [], []

    normalized = preprocess_text(text)
    chapters = parse_chapters(normalized)
    return _chunk_by_chapters(normalized, chapters), chapters


def _chunk_by_chapters(
    text: str,
    chapters: list[ChapterData],
) -> list[Chunk]:
    """按章节分块：每个有正文的章节为一个 chunk，空章节跳过"""
    chunks: list[Chunk] = []

    for chapter in chapters:
        if not text[chapter.start_char : chapter.end_char].strip():
            continue

        span = _resolve_trimmed_span(text, chapter.start_char, chapter.end_char)
        if span is None:
            continue
        local_start, local_end, chunk_text_content = span
        chunks.append(
            Chunk(
                index=len(chunks),
                text=chunk_text_content,
                start=local_start,
                end=local_end,
                chapter_id=chapter.chapter_id,
            )
        )

    return _reindex(chunks)


# =============================================================================
# 便捷函数
# =============================================================================


async def chunk_documents(
    texts: Iterable[str],
    emitter: Callable[[StreamEvent], Awaitable[None]] | None = None,
) -> list[Chunk]:
    """分块多个文档（async 版本），仅返回 chunks"""
    chunks, _ = await chunk_documents_with_chapters(texts, emitter=emitter)
    return chunks


async def chunk_documents_with_chapters(
    texts: Iterable[str],
    emitter: Callable[[StreamEvent], Awaitable[None]] | None = None,
) -> tuple[list[Chunk], list[ChapterData]]:
    """
    分块多个文档并聚合章节目录（async 版本）

    多文档场景下将每个文档的 chunk/chapter offset 折算为 run 级连续全文坐标；
    run-global offset 口径定义为“按输入顺序直接拼接的 preprocess_text 输出”。
    """
    all_chunks: list[Chunk] = []
    all_chapters: list[ChapterData] = []
    chunk_index_offset = 0
    chapter_index_offset = 0
    document_char_offset = 0

    for text in texts:
        # chunk/chapter 偏移均相对 preprocess_text 输出，offset 累加必须用预处理后长度，
        # 否则多文档 run 中第 2 个文档起的坐标会系统性漂移
        normalized_len = len(preprocess_text(text))
        chunks, chapters = await chunk_text_with_chapters(text, emitter=emitter)
        for chunk in chunks:
            all_chunks.append(
                Chunk(
                    index=chunk.index + chunk_index_offset,
                    text=chunk.text,
                    start=chunk.start + document_char_offset,
                    end=chunk.end + document_char_offset,
                    chapter_id=chunk.chapter_id + chapter_index_offset,
                )
            )
        for chapter in chapters:
            all_chapters.append(
                ChapterData(
                    chapter_id=chapter.chapter_id + chapter_index_offset,
                    sequence=chapter.sequence + chapter_index_offset,
                    level=chapter.level,
                    title=chapter.title,
                    display_title=chapter.display_title,
                    display_index_label=chapter.display_index_label,
                    number=chapter.number,
                    title_start_char=chapter.title_start_char + document_char_offset,
                    start_char=chapter.start_char + document_char_offset,
                    end_char=chapter.end_char + document_char_offset,
                )
            )
        chunk_index_offset += len(chunks)
        if chapters:
            chapter_index_offset += len(chapters)
        document_char_offset += normalized_len

    return _reindex(all_chunks), all_chapters


# =============================================================================
# 自然段分割（最小事实单元）
# =============================================================================

PARAGRAPH_SPLIT_RE = re.compile(r"\n")
_SENTENCE_BOUNDARY_CHARS = ("。", "！", "？", "…", "；")


def _split_oversized_span(
    text: str,
    start: int,
    end: int,
    max_chars: int,
    source_paragraph_index: int,
) -> list[ParagraphSpan]:
    """
    把段落切分出的超大区间按句子边界再切到 max_chars 以内

    单段 token 数可能超过 embedding 服务的物理 batch 上限，
    必须在段落粒度内按句子边界再切（无句子边界时退化为固定字数硬切）

    拆分出的片段共享 source_paragraph_index，fragment_index 从 0 递增
    """
    spans: list[ParagraphSpan] = []
    cursor = start
    fragment_index = 0
    while cursor < end:
        chunk_end = min(cursor + max_chars, end)
        if chunk_end < end:
            sentence_end = max(
                (text.rfind(boundary, cursor, chunk_end) for boundary in _SENTENCE_BOUNDARY_CHARS),
                default=-1,
            )
            if sentence_end > cursor + max_chars * 0.5:
                chunk_end = sentence_end + 1
        span = _resolve_trimmed_span(text, cursor, chunk_end)
        if span is not None:
            local_start, local_end, paragraph_text = span
            spans.append(
                ParagraphSpan(
                    paragraph_index=-1,  # 由 split_paragraphs 统一分配
                    source_paragraph_index=source_paragraph_index,
                    fragment_index=fragment_index,
                    local_start_char=local_start,
                    local_end_char=local_end,
                    text=paragraph_text,
                )
            )
        cursor = chunk_end
        fragment_index += 1
    return spans


def split_paragraphs(text: str, max_chars: int = 1500) -> list[ParagraphSpan]:
    """
    将文本按自然段分割为段落单元（ParagraphSpan，strip 后真实局部坐标）

    段落单元是文本分析的最小事实单元（设计文档《章节粒度分析指标重设计》§3）。
    段落边界为任意换行（单换行也算段落边界，网文 txt 常以单换行分段），
    连续空行产生的空段自动跳过；超过 max_chars 的超长段落再按句子边界切分，
    保证单段 token 数不超过 embedding 服务物理 batch 上限。

    返回的 ParagraphSpan 只含 chunk 局部身份（paragraph_index、
    source_paragraph_index、fragment_index 与 local 坐标），chunk 级身份
    （chapter_id/chapter_id/paragraph_id/global 坐标）由 split_chunk_paragraphs
    或调用方在归属到 chunk 后填充。
    """
    paragraphs: list[ParagraphSpan] = []
    source_paragraph_index = 0
    start = 0

    for match in PARAGRAPH_SPLIT_RE.finditer(text):
        end = match.start()
        paragraphs.extend(_split_oversized_span(text, start, end, max_chars, source_paragraph_index))
        source_paragraph_index += 1
        start = match.end()

    if start < len(text):
        paragraphs.extend(_split_oversized_span(text, start, len(text), max_chars, source_paragraph_index))

    if paragraphs:
        return [
            ParagraphSpan(
                paragraph_index=idx,
                source_paragraph_index=span.source_paragraph_index,
                fragment_index=span.fragment_index,
                local_start_char=span.local_start_char,
                local_end_char=span.local_end_char,
                text=span.text,
            )
            for idx, span in enumerate(paragraphs)
        ]
    if text.strip():
        span = _resolve_trimmed_span(text, 0, len(text))
        if span is not None:
            local_start, local_end, paragraph_text = span
            return [
                ParagraphSpan(
                    paragraph_index=0,
                    source_paragraph_index=0,
                    fragment_index=0,
                    local_start_char=local_start,
                    local_end_char=local_end,
                    text=paragraph_text,
                )
            ]
    return []


def split_chunk_paragraphs(
    chunks: Sequence[Chunk],
    max_chars: int = 1500,
) -> list[ParagraphSpan]:
    """
    将多个 chunk（章）的文本切分为带 run 级身份的段落单元

    段落身份不变量（设计文档 §3/§4）：
    - paragraph_id 在 run 内按全文顺序连续（0, 1, 2, ...），不随数据库自增推断
    - global 坐标 = chunk 全文偏移 + local 坐标，与规范化全文坐标一致
    - chapter_id 直接取自 Chunk 上下文（M9a-2：chunks 表合并后段落身份 = chapter_id）
    """
    spans: list[ParagraphSpan] = []
    paragraph_id = 0
    for chunk in chunks:
        for span in split_paragraphs(chunk.text, max_chars=max_chars):
            spans.append(
                replace(
                    span,
                    paragraph_id=paragraph_id,
                    chapter_id=chunk.chapter_id,
                    global_start_char=chunk.start + span.local_start_char,
                    global_end_char=chunk.start + span.local_end_char,
                )
            )
            paragraph_id += 1
    return spans
