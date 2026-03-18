"""
创建时间: 2026-03-12
创建者: TraeAI
任务: 项目文件结构整理与拆解 - 从 unified_client.py 拆分 chunking 模块

本模块包含文本分块相关的功能，支持按章节、段落、语义等多种分块策略。

修改时间: 2026-03-13
修改者: TraeAI
任务: refactor-core-data-layer-functions
修改内容:
- 添加拟声词检测功能，优化语义分块边界检测
- 添加 ONOMATOPOEIA_PATTERN 和 SINGLE_ONOMATOPOEIA 常量
- 在 SemanticChunker 中集成拟声词检测逻辑

修改时间: 2026-03-18
创建者: TraeAI
任务: code-quality-refactor - Task 10 简化chunker.py
修改内容:
- 简化代码结构，移除复杂的子模块拆分
- 保留所有功能，优化代码组织
- 文件行数: 539行 → 319行 (-41%)
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterable, List, Set, Tuple

from src.config import CHAPTER_PATTERN, PARAGRAPH_SPLIT, settings
from src.models.local.embedding import EmbeddingClient


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


def _reindex(chunks: List[Chunk]) -> List[Chunk]:
    """重新索引 chunks"""
    return [
        Chunk(
            index=idx,
            text=chunk.text,
            start=chunk.start,
            end=chunk.end,
            chapter_title=chunk.chapter_title,
        )
        for idx, chunk in enumerate(chunks)
    ]


# =============================================================================
# 拟声词检测
# =============================================================================

ONOMATOPOEIA_PATTERN = re.compile(
    r"^[轰唳砰咔嗖呼噗咚哗嗒啊哦嗯哼咦哇呀嘿唉喂噢咦]+[！!。…~～]*$|"
    r"^[轰砰咔哗呼噗咚嗒]{1,2}[！!。…~～]*$|"
    r"^[咔嚓哗啦轰隆砰砰轰轰]{1,2}[！!。…~～]*$|"
    r"^.{1,4}[！!]$"
)

SINGLE_ONOMATOPOEIA = set("轰唳砰咔嗖呼噗咚哗嗒啊哦嗯哼咦哇呀嘿唉喂噢")


def _is_onomatopoeia(text: str) -> bool:
    """判断文本是否为拟声词"""
    text = text.strip()
    if not text:
        return False

    if ONOMATOPOEIA_PATTERN.match(text):
        return True

    if len(text) <= 2:
        return all(c in SINGLE_ONOMATOPOEIA for c in text)

    if len(text) <= 4:
        onomatopoeia_chars = sum(1 for c in text if c in SINGLE_ONOMATOPOEIA)
        punctuation_chars = sum(1 for c in text if c in "！!。…~～")
        if (onomatopoeia_chars + punctuation_chars) >= len(text) / 2:
            return True

    return False


def _detect_onomatopoeia(paragraphs: List[Tuple[int, int, str]]) -> Set[int]:
    """检测拟声词段落索引"""
    return {i for i, (_, _, text) in enumerate(paragraphs) if _is_onomatopoeia(text)}


# =============================================================================
# 章节检测
# =============================================================================

def detect_chapters(text: str) -> List[Tuple[int, int, str]]:
    """检测文本中的章节边界"""
    matches = list(CHAPTER_PATTERN.finditer(text))
    if not matches:
        return []
    ranges: List[Tuple[int, int, str]] = []
    for idx, match in enumerate(matches):
        start = match.start() + len(match.group(1))
        end = matches[idx + 1].start() if idx + 1 < len(matches) else len(text)
        ranges.append((start, end, match.group().strip()))
    return ranges


# =============================================================================
# 段落处理
# =============================================================================

def _iter_paragraphs(text: str, start: int = 0, end: int | None = None) -> List[Tuple[int, int, str]]:
    """迭代文本中的段落"""
    if end is None:
        end = len(text)
    paragraphs: List[Tuple[int, int, str]] = []
    cursor = start
    for match in PARAGRAPH_SPLIT.finditer(text, start, end):
        p_end = match.start()
        raw = text[cursor:p_end]
        if raw.strip():
            paragraphs.append((cursor, p_end, raw.strip()))
        cursor = match.end()
    if cursor <= end:
        raw = text[cursor:end]
        if raw.strip():
            paragraphs.append((cursor, end, raw.strip()))
    return paragraphs


def _chunk_by_paragraph(
    text: str,
    start: int,
    end: int,
    max_chars: int,
    title: str | None,
) -> List[Chunk]:
    """按段落分块"""
    chunks: List[Chunk] = []
    current: List[str] = []
    current_len = 0
    current_start = start
    idx = 0

    for p_start, p_end, paragraph in _iter_paragraphs(text, start, end):
        if not current:
            current_start = p_start
        current.append(paragraph)
        current_len += len(paragraph)
        if current_len >= max_chars:
            chunk_text = "\n\n".join(current).strip()
            if chunk_text:
                chunks.append(
                    Chunk(
                        index=idx,
                        text=chunk_text,
                        start=current_start,
                        end=p_end,
                        chapter_title=title,
                    )
                )
                idx += 1
            current = []
            current_len = 0

    if current:
        chunk_text = "\n\n".join(current).strip()
        if chunk_text:
            chunks.append(
                Chunk(
                    index=idx,
                    text=chunk_text,
                    start=current_start,
                    end=end,
                    chapter_title=title,
                )
            )

    return chunks


# =============================================================================
# 语义分块器
# =============================================================================

class SemanticChunker:
    """语义分块器 - 基于段落间的语义相似度进行分块"""

    def __init__(self, embedding_client: EmbeddingClient | None = None):
        self._embedding_client = embedding_client or EmbeddingClient()
        self._window_size = settings.chunking.semantic_window_size
        self._percentile = settings.chunking.semantic_percentile
        self._min_chars = settings.chunking.semantic_min_chars
        self._use_dynamic_threshold = settings.chunking.semantic_use_dynamic_threshold

    def chunk_text_semantic(
        self,
        text: str,
        chapter_title: str | None = None,
    ) -> List[Chunk]:
        """基于语义相似度对文本进行分块"""
        if not text:
            return []

        paragraphs = _iter_paragraphs(text, 0, len(text))
        if not paragraphs:
            return []

        if len(paragraphs) <= 2:
            return [
                Chunk(
                    index=0,
                    text=text,
                    start=paragraphs[0][0],
                    end=paragraphs[-1][1],
                    chapter_title=chapter_title,
                )
            ]

        onomatopoeia_indices = _detect_onomatopoeia(paragraphs)
        paragraph_embeddings = self._compute_paragraph_embeddings(paragraphs)

        if self._use_dynamic_threshold:
            boundaries = self._detect_boundaries(paragraphs, paragraph_embeddings, onomatopoeia_indices)
        else:
            boundaries = self._detect_boundaries_fixed(paragraphs, paragraph_embeddings, onomatopoeia_indices)

        chunks = self._create_chunks_from_boundaries(text, paragraphs, boundaries, chapter_title)
        chunks = self._apply_min_chars_constraint(chunks)
        return _reindex(chunks)

    def _compute_paragraph_embeddings(
        self, paragraphs: List[Tuple[int, int, str]]
    ) -> List[List[float]]:
        """计算段落的嵌入向量"""
        texts = [text for _, _, text in paragraphs]
        return self._embedding_client.embed_texts(texts)

    def _detect_boundaries(
        self,
        paragraphs: List[Tuple[int, int, str]],
        embeddings: List[List[float]],
        onomatopoeia_indices: Set[int],
    ) -> List[int]:
        """使用动态阈值检测分块边界"""
        from src.utils.similarity import cosine_similarity
        import statistics

        boundaries = []
        similarities = []

        for i in range(len(paragraphs) - 1):
            if i in onomatopoeia_indices or (i + 1) in onomatopoeia_indices:
                continue
            sim = cosine_similarity(embeddings[i], embeddings[i + 1])
            similarities.append((i, sim))

        if not similarities:
            return boundaries

        sim_values = [sim for _, sim in similarities]
        threshold = statistics.median(sim_values) * self._percentile

        for i, sim in similarities:
            if sim < threshold:
                boundaries.append(i)

        return boundaries

    def _detect_boundaries_fixed(
        self,
        paragraphs: List[Tuple[int, int, str]],
        embeddings: List[List[float]],
        onomatopoeia_indices: Set[int],
    ) -> List[int]:
        """使用固定阈值检测分块边界"""
        from src.utils.similarity import cosine_similarity

        boundaries = []
        threshold = settings.chunking.semantic_similarity_threshold

        for i in range(len(paragraphs) - 1):
            if i in onomatopoeia_indices or (i + 1) in onomatopoeia_indices:
                continue
            sim = cosine_similarity(embeddings[i], embeddings[i + 1])
            if sim < threshold:
                boundaries.append(i)

        return boundaries

    def _create_chunks_from_boundaries(
        self,
        text: str,
        paragraphs: List[Tuple[int, int, str]],
        boundaries: List[int],
        chapter_title: str | None,
    ) -> List[Chunk]:
        """根据边界创建 chunks"""
        chunks = []
        start_idx = 0

        for boundary in boundaries:
            chunk_paragraphs = paragraphs[start_idx : boundary + 1]
            if chunk_paragraphs:
                chunk_text = "\n\n".join(text for _, _, text in chunk_paragraphs)
                chunks.append(
                    Chunk(
                        index=len(chunks),
                        text=chunk_text,
                        start=chunk_paragraphs[0][0],
                        end=chunk_paragraphs[-1][1],
                        chapter_title=chapter_title,
                    )
                )
            start_idx = boundary + 1

        if start_idx < len(paragraphs):
            chunk_paragraphs = paragraphs[start_idx:]
            chunk_text = "\n\n".join(text for _, _, text in chunk_paragraphs)
            chunks.append(
                Chunk(
                    index=len(chunks),
                    text=chunk_text,
                    start=chunk_paragraphs[0][0],
                    end=chunk_paragraphs[-1][1],
                    chapter_title=chapter_title,
                )
            )

        return chunks

    def _apply_min_chars_constraint(self, chunks: List[Chunk]) -> List[Chunk]:
        """应用最小字符数约束，合并过小的 chunks"""
        if not chunks:
            return chunks

        result = []
        current_chunk = None

        for chunk in chunks:
            if current_chunk is None:
                current_chunk = chunk
            elif len(current_chunk.text) < self._min_chars:
                current_chunk = Chunk(
                    index=current_chunk.index,
                    text=current_chunk.text + "\n\n" + chunk.text,
                    start=current_chunk.start,
                    end=chunk.end,
                    chapter_title=current_chunk.chapter_title,
                )
            else:
                result.append(current_chunk)
                current_chunk = chunk

        if current_chunk:
            result.append(current_chunk)

        return result


# =============================================================================
# 主要分块函数
# =============================================================================

def chunk_text(
    text: str,
    max_chars: int | None = None,
    overlap: int | None = None,
    split_by_chapter: bool | None = None,
    use_semantic: bool | None = None,
) -> List[Chunk]:
    """对文本进行分块"""
    if use_semantic is None:
        use_semantic = settings.chunking.use_semantic_chunking

    if use_semantic:
        chunker = SemanticChunker()
        return chunker.chunk_text_semantic(text)

    if max_chars is None:
        max_chars = settings.chunking.max_chars
    if split_by_chapter is None:
        split_by_chapter = settings.chunking.split_by_chapter

    if not text:
        return []
    if max_chars <= 0:
        raise ValueError("max_chars must be positive")

    chunks: List[Chunk] = []

    if split_by_chapter:
        chapter_ranges = detect_chapters(text)
    else:
        chapter_ranges = []

    if chapter_ranges:
        for start, end, title in chapter_ranges:
            chunks.extend(_chunk_by_paragraph(text, start, end, max_chars, title))
        return _reindex(chunks)

    chunks = _chunk_by_paragraph(text, 0, len(text), max_chars, None)
    return _reindex(chunks)


def chunk_documents(
    texts: Iterable[str],
    max_chars: int | None = None,
    overlap: int | None = None,
    split_by_chapter: bool | None = None,
    use_semantic: bool | None = None,
) -> List[Chunk]:
    """对多个文档进行分块"""
    if max_chars is None:
        max_chars = settings.chunking.max_chars
    if split_by_chapter is None:
        split_by_chapter = settings.chunking.split_by_chapter
    if use_semantic is None:
        use_semantic = settings.chunking.use_semantic_chunking

    chunks: List[Chunk] = []
    for text in texts:
        chunks.extend(chunk_text(text, max_chars, overlap, split_by_chapter, use_semantic))

    return _reindex(chunks)
