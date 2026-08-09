"""
文本分块模块

本模块包含文本分块相关的功能，分章策略：
1. 优先按原始章节分割（CHAPTER_PATTERN 正则捕捉章节标题）
2. 无法捕捉原始章节时，回退到固定字数段落分割（_chunk_simple）

不再使用向量相似度（语义分块）作为分块依据。
"""

from __future__ import annotations

import re
from collections.abc import Awaitable, Callable, Iterable
from dataclasses import dataclass

from loguru import logger

from src.api.models.events import StreamEvent
from src.config import CHAPTER_PATTERN

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
    chapter_title: str | None = None
    chapter_index: int | None = None


def _reindex(chunks: list[Chunk]) -> list[Chunk]:
    """重新索引 chunks"""
    return [
        Chunk(
            index=idx,
            text=chunk.text,
            start=chunk.start,
            end=chunk.end,
            chapter_title=chunk.chapter_title,
            chapter_index=chunk.chapter_index,
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


def _split_by_chapters_with_offsets(text: str) -> list[tuple[str | None, str, int, int]]:
    """
    按章节分割文本，并保留章节正文在全文中的字符范围

    返回的章节标题来自原文匹配到的标题文本；未匹配到任何章节标题时，
    返回单条 `(None, text, 0, len(text))` 表示“无法捕捉原始章节”
    """
    chapters: list[tuple[str | None, str, int, int]] = []
    last_end = 0
    last_title: str | None = None

    for match in CHAPTER_PATTERN.finditer(text):
        if last_end < match.start():
            chapter_text = text[last_end : match.start()]
            if chapter_text.strip():
                chapters.append((last_title, chapter_text, last_end, match.start()))
            elif last_title is not None:
                logger.warning("章节「{}」无正文，已跳过该空章节", last_title)
        elif last_title is not None:
            logger.warning("章节「{}」无正文，已跳过该空章节", last_title)
        last_title = match.group(0).strip()
        last_end = match.end()

    if last_end < len(text):
        chapter_text = text[last_end:]
        if chapter_text.strip():
            chapters.append((last_title, chapter_text, last_end, len(text)))
        elif last_title is not None:
            logger.warning("章节「{}」无正文，已跳过该空章节", last_title)
    elif last_title is not None:
        logger.warning("章节「{}」无正文，已跳过该空章节", last_title)

    if chapters:
        return chapters
    return [(None, text, 0, len(text))]


def _chapters_detected(chapters: list[tuple[str | None, str, int, int]]) -> bool:
    """
    判断是否成功捕捉到原始章节

    只要存在一个非空章节标题，就视为捕捉到章节结构；
    否则说明整本都没有可识别的章节标题，需要回退固定字数分割
    """
    return any(title is not None and title.strip() for title, _, _, _ in chapters)


# =============================================================================
# 章节分割
# =============================================================================


def split_by_chapters(text: str) -> list[tuple[str | None, str]]:
    """
    按章节分割文本
    """
    return [
        (chapter_title, chapter_text)
        for chapter_title, chapter_text, _, _ in _split_by_chapters_with_offsets(text)
    ]


async def chunk_text(
    text: str,
    emitter: Callable[[StreamEvent], Awaitable[None]] | None = None,
) -> list[Chunk]:
    """
    将文本分割成块（async 版本）

    分章策略：
    - 优先按原始章节分割：每个章节为一个 chunk（保留 chapter_title/chapter_index，无论多长不再切）
    - 无法捕捉原始章节时，回退到固定字数段落分割（_chunk_simple）

    Args:
        text: 输入文本

    Returns:
        Chunk对象列表
    """
    if not text.strip():
        return []

    chapters = _split_by_chapters_with_offsets(text)
    if _chapters_detected(chapters):
        return _chunk_by_chapters(text, chapters)

    return _chunk_simple(text)


def _chunk_simple(text: str, max_chars: int = 2000) -> list[Chunk]:
    """
    固定字数段落分割（章节不可用时回退策略）

    文本不超过 max_chars 时整段一个 chunk；超过时在段落/句子边界按 max_chars 切分，无重叠。

    生成的 `Chunk.start/end` 为最终保留文本的真实全文范围
    """
    if len(text) <= max_chars:
        span = _resolve_trimmed_span(text, 0, len(text))
        if span is None:
            return []
        chunk_start, chunk_end, chunk_text_content = span
        return [
            Chunk(
                index=0,
                text=chunk_text_content,
                start=chunk_start,
                end=chunk_end,
                chapter_index=1,
            )
        ]

    chunks = []
    start = 0
    idx = 0

    while start < len(text):
        end = start + max_chars
        if end < len(text):
            # 尝试在段落边界分割
            paragraph_end = text.rfind("\n\n", start, end)
            if paragraph_end > start + max_chars * 0.5:
                end = paragraph_end
            else:
                # 尝试在句子边界分割
                sentence_end = text.rfind("。", start, end)
                if sentence_end > start + max_chars * 0.5:
                    end = sentence_end + 1

        span = _resolve_trimmed_span(text, start, end)
        if span is not None:
            chunk_start, chunk_end, chunk_text_content = span
            chunks.append(
                Chunk(
                    index=idx,
                    text=chunk_text_content,
                    start=chunk_start,
                    end=chunk_end,
                    chapter_index=idx + 1,
                )
            )
            idx += 1

        start = end

    return chunks


def _chunk_by_chapters(
    text: str,
    chapters: list[tuple[str | None, str, int, int]],
) -> list[Chunk]:
    """
    按章节分块

    每个章节为一个 chunk（保留 chapter_title），不再按字数切分章节。
    章节内局部切片写回 Chunk 时统一折算为整本全文的真实 offset
    """
    chunks: list[Chunk] = []

    for chapter_index, (chapter_title, chapter_text, chapter_start_offset, _) in enumerate(chapters, start=1):
        if not chapter_text.strip():
            continue

        span = _resolve_trimmed_span(chapter_text, 0, len(chapter_text))
        if span is None:
            continue
        local_start, local_end, chunk_text_content = span
        chunks.append(
            Chunk(
                index=len(chunks),
                text=chunk_text_content,
                start=chapter_start_offset + local_start,
                end=chapter_start_offset + local_end,
                chapter_title=chapter_title,
                chapter_index=chapter_index,
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
    """
    分块多个文档（async 版本）

    多文档场景下将每个文档的 chunk offset 折算为 run 级连续全文坐标；
    run-global offset 口径定义为“按输入顺序直接拼接的规范化文档文本”
    """
    all_chunks = []
    chunk_index_offset = 0
    chapter_index_offset = 0
    document_char_offset = 0

    for text in texts:
        chunks = await chunk_text(
            text,
            emitter=emitter,
        )
        chapter_indices = sorted(
            {
                chunk.chapter_index
                for chunk in chunks
                if chunk.chapter_index is not None
            }
        )
        for chunk in chunks:
            all_chunks.append(
                Chunk(
                    index=chunk.index + chunk_index_offset,
                    text=chunk.text,
                    start=chunk.start + document_char_offset,
                    end=chunk.end + document_char_offset,
                    chapter_title=chunk.chapter_title,
                    chapter_index=(
                        chunk.chapter_index + chapter_index_offset
                        if chunk.chapter_index is not None
                        else None
                    ),
                )
            )
        chunk_index_offset += len(chunks)
        if chapter_indices:
            chapter_index_offset += chapter_indices[-1]
        document_char_offset += len(text)

    return _reindex(all_chunks)


# =============================================================================
# 自然段分割（RAG 粒度）
# =============================================================================

PARAGRAPH_SPLIT_RE = re.compile(r"\n")
_SENTENCE_BOUNDARY_CHARS = ("。", "！", "？", "…", "；")


def _split_oversized_span(
    text: str,
    start: int,
    end: int,
    max_chars: int,
) -> list[tuple[int, int, str]]:
    """
    2026-08-08 用于把段落切分出的超大区间按句子边界再切到 max_chars 以内

    单段 token 数可能超过 embedding 服务的物理 batch 上限，
    必须在段落粒度内按句子边界再切（无句子边界时退化为固定字数硬切）
    """
    spans: list[tuple[int, int, str]] = []
    cursor = start
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
            spans.append(span)
        cursor = chunk_end
    return spans


def split_paragraphs(text: str, max_chars: int = 1500) -> list[tuple[int, int, str]]:
    """
    将文本按自然段分割，返回 (start, end, text) 三元组（strip 后真实坐标）

    RAG 检索粒度固定为一个自然段，本函数是段落级证据的统一分割入口。
    段落边界为任意换行（单换行也算段落边界，网文 txt 常以单换行分段），
    连续空行产生的空段自动跳过；超过 max_chars 的超长段落再按句子边界切分，
    保证单段 token 数不超过 embedding 服务物理 batch 上限
    """
    paragraphs: list[tuple[int, int, str]] = []
    start = 0

    for match in PARAGRAPH_SPLIT_RE.finditer(text):
        end = match.start()
        paragraphs.extend(_split_oversized_span(text, start, end, max_chars))
        start = match.end()

    if start < len(text):
        paragraphs.extend(_split_oversized_span(text, start, len(text), max_chars))

    if paragraphs:
        return paragraphs
    if text.strip():
        span = _resolve_trimmed_span(text, 0, len(text))
        return [span] if span is not None else []
    return []
