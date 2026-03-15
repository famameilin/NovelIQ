from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterable, List, Tuple

from loguru import logger

from src.config import CHAPTER_PATTERN, PARAGRAPH_SPLIT, settings
from src.models.local.embedding import EmbeddingClient


@dataclass(frozen=True)
class Chunk:
    index: int
    text: str
    start: int
    end: int
    chapter_title: str | None = None


# 创建时间: 2026-03-13
# 创建者: TraeAI
# 任务: refactor-core-data-layer-functions
# 说明: 拟声词正则匹配模式，用于识别小说中的拟声词段落
#
# 拟声词识别在语义分块中的作用：
# 1. 拟声词通常作为独立的段落出现，语义上与上下文关联较弱
# 2. 在计算段落相似度时，拟声词段落会导致相似度异常低（因为内容太短且特殊）
# 3. 为避免拟声词段落被错误地作为分块边界，需要特殊处理：
#    - 在 _build_chunk_boundaries 和 _detect_boundaries 中，跳过拟声词段落相邻的边界检测
#    - 拟声词段落会与相邻段落合并，保持语义完整性
#
# 正则表达式各分支说明：
# 分支1: r'^[轰唳砰咔嗖呼噗咚哗嗒啊哦嗯哼咦哇呀嘿唉喂噢咦]+[！!。…~～]*$'
#   - 匹配单字拟声词的连续组合，如"轰隆"、"砰砰"、"咔咔"等
#   - 后面可跟中文/英文感叹号、句号、省略号、波浪号等标点
#   - 示例: "轰！", "砰砰！", "咔嚓..."
#
# 分支2: r'^[轰砰咔哗呼噗咚嗒]{1,2}[！!。…~～]*$'
#   - 匹配1-2个常见爆炸/撞击类拟声词字符
#   - 这类拟声词在动作场景中频繁出现
#   - 示例: "轰！", "砰！", "咔！"
#
# 分支3: r'^[咔嚓哗啦轰隆砰砰轰轰]{1,2}[！!。…~～]*$'
#   - 匹配双字拟声词的1-2次重复
#   - 注意：这里的字符集包含完整的双字拟声词，如"咔嚓"、"哗啦"、"轰隆"
#   - 示例: "咔嚓！", "哗啦！", "轰隆隆..."
#
# 分支4: r'^.{1,4}[！!]$'
#   - 匹配1-4个任意字符后跟感叹号的短句
#   - 这类短句在小说中通常是感叹词或极短的拟声表达
#   - 示例: "啊！", "哇！", "天哪！"
ONOMATOPOEIA_PATTERN = re.compile(
    r"^[轰唳砰咔嗖呼噗咚哗嗒啊哦嗯哼咦哇呀嘿唉喂噢咦]+[！!。…~～]*$|"
    r"^[轰砰咔哗呼噗咚嗒]{1,2}[！!。…~～]*$|"
    r"^[咔嚓哗啦轰隆砰砰轰轰]{1,2}[！!。…~～]*$|"
    r"^.{1,4}[！!]$"
)

# 创建时间: 2026-03-13
# 创建者: TraeAI
# 任务: refactor-core-data-layer-functions
# 说明: 单字拟声词字符集合，用于快速判断字符是否为拟声词
#
# 用途：
# 1. 在 _is_onomatopoeia 方法中，用于快速判断短文本（<=2字符）是否为拟声词
# 2. 用于判断4字符以内的短段落是否包含拟声词字符（结合标点判断）
# 3. 作为 ONOMATOPOEIA_PATTERN 正则的补充，提高识别准确率
#
# 字符分类：
# - 爆炸/撞击类: 轰、砰、咔、咚
# - 风声/运动类: 唳、嗖、呼、哗、嗒
# - 其他声音: 噗
# - 感叹词类: 啊、哦、嗯、哼、咦、哇、呀、嘿、唉、喂、噢
SINGLE_ONOMATOPOEIA = set("轰唳砰咔嗖呼噗咚哗嗒啊哦嗯哼咦哇呀嘿唉喂噢")


def detect_chapters(text: str) -> List[Tuple[int, int, str]]:
    matches = list(CHAPTER_PATTERN.finditer(text))
    if not matches:
        return []
    ranges: List[Tuple[int, int, str]] = []
    for idx, match in enumerate(matches):
        start = match.start() + len(match.group(1))
        end = matches[idx + 1].start() if idx + 1 < len(matches) else len(text)
        ranges.append((start, end, match.group().strip()))
    return ranges


class SemanticChunker:
    def __init__(self, embedding_client: EmbeddingClient | None = None):
        self._embedding_client = embedding_client or EmbeddingClient()
        self._window_size = settings.chunking.semantic_window_size
        self._percentile = settings.chunking.semantic_percentile
        self._min_chars = settings.chunking.semantic_min_chars
        self._use_dynamic_threshold = settings.chunking.semantic_use_dynamic_threshold

    def chunk_text_semantic(
        self,
        text: str,
        threshold: float | None = None,
        max_chars: int | None = None,
    ) -> List[Chunk]:
        if threshold is None:
            threshold = settings.chunking.semantic_threshold
        if max_chars is None:
            max_chars = settings.chunking.semantic_max_chars
        if not text:
            return []
        if threshold <= 0 or threshold > 1:
            raise ValueError("threshold must be in (0, 1]")
        if max_chars <= 0:
            raise ValueError("max_chars must be positive")
        chapter_ranges = detect_chapters(text)
        if chapter_ranges:
            chunks: List[Chunk] = []
            for start, end, title in chapter_ranges:
                chunks.extend(self._chunk_section_semantic(text, start, end, title, threshold, max_chars))
            return self._reindex(chunks)
        return self._reindex(self._chunk_section_semantic(text, 0, len(text), None, threshold, max_chars))

    def _chunk_section_semantic(
        self,
        text: str,
        start: int,
        end: int,
        chapter_title: str | None,
        threshold: float,
        max_chars: int,
    ) -> List[Chunk]:
        paragraphs = _iter_paragraphs(text, start, end)
        if not paragraphs:
            return []
        if len(paragraphs) == 1:
            p_start, p_end, p_text = paragraphs[0]
            return [Chunk(index=0, text=p_text, start=p_start, end=p_end, chapter_title=chapter_title)]

        onomatopoeia_indices = self._detect_onomatopoeia(paragraphs)

        if self._use_dynamic_threshold:
            return self._chunk_with_dynamic_threshold(paragraphs, onomatopoeia_indices, chapter_title, max_chars)
        else:
            return self._chunk_with_fixed_threshold(
                paragraphs, onomatopoeia_indices, threshold, max_chars, chapter_title
            )

    def _chunk_with_dynamic_threshold(
        self,
        paragraphs: List[Tuple[int, int, str]],
        onomatopoeia_indices: set,
        chapter_title: str | None,
        max_chars: int,
    ) -> List[Chunk]:
        window_embeddings = self._compute_window_embeddings(paragraphs)
        if len(window_embeddings) < 2:
            return self._create_single_chunk(paragraphs, chapter_title)

        similarities = self._compute_window_similarities(window_embeddings)
        threshold = self._compute_dynamic_threshold(similarities)

        boundaries = self._detect_boundaries(similarities, threshold, onomatopoeia_indices)
        chunks = self._create_chunks_from_boundaries(paragraphs, boundaries, chapter_title, max_chars)
        chunks = self._apply_min_chars_constraint(chunks, max_chars)

        return chunks

    def _compute_paragraph_embeddings(
        self,
        paragraphs: List[Tuple[int, int, str]],
    ) -> Tuple[List[List[float]], List[Tuple[int, int, str]]]:
        """
        计算段落的嵌入向量。

        创建时间: 2026-03-13
        创建者: TraeAI
        任务: refactor-core-data-layer-functions
        功能: 遍历段落列表，为每个段落计算嵌入向量，过滤掉无效段落
        """
        embeddings: List[List[float]] = []
        valid_paragraphs: List[Tuple[int, int, str]] = []
        for p_start, p_end, p_text in paragraphs:
            emb = self._embedding_client.get_embedding(p_text)
            if emb:
                embeddings.append(emb)
                valid_paragraphs.append((p_start, p_end, p_text))
        return embeddings, valid_paragraphs

    def _build_chunk_boundaries(
        self,
        embeddings: List[List[float]],
        onomatopoeia_indices: set,
        threshold: float,
    ) -> List[int]:
        """
        根据嵌入向量相似度构建分块边界。

        创建时间: 2026-03-13
        创建者: TraeAI
        任务: refactor-core-data-layer-functions
        功能: 计算相邻段落间的相似度，当相似度低于阈值时创建边界
        """
        boundaries: List[int] = [0]
        for i in range(len(embeddings) - 1):
            if i in onomatopoeia_indices or i + 1 in onomatopoeia_indices:
                continue
            sim = EmbeddingClient.compute_similarity(embeddings[i], embeddings[i + 1])
            if sim < threshold:
                boundaries.append(i + 1)
        boundaries.append(len(embeddings))
        return boundaries

    def _chunk_with_fixed_threshold(
        self,
        paragraphs: List[Tuple[int, int, str]],
        onomatopoeia_indices: set,
        threshold: float,
        max_chars: int,
        chapter_title: str | None,
    ) -> List[Chunk]:
        embeddings, valid_paragraphs = self._compute_paragraph_embeddings(paragraphs)
        if not valid_paragraphs:
            return []
        if len(valid_paragraphs) == 1:
            p_start, p_end, p_text = valid_paragraphs[0]
            return [Chunk(index=0, text=p_text, start=p_start, end=p_end, chapter_title=chapter_title)]

        boundaries = self._build_chunk_boundaries(embeddings, onomatopoeia_indices, threshold)
        chunks = self._create_chunks_from_boundaries(valid_paragraphs, boundaries, chapter_title, max_chars)
        chunks = self._apply_min_chars_constraint(chunks, max_chars)
        return chunks

    def _detect_onomatopoeia(self, paragraphs: List[Tuple[int, int, str]]) -> set:
        onomatopoeia_indices = set()
        for idx, (_, _, p_text) in enumerate(paragraphs):
            if self._is_onomatopoeia(p_text):
                onomatopoeia_indices.add(idx)
        return onomatopoeia_indices

    def _is_onomatopoeia(self, text: str) -> bool:
        text = text.strip()
        if len(text) > 8:
            return False
        if len(text) <= 2 and all(c in SINGLE_ONOMATOPOEIA for c in text):
            return True
        if ONOMATOPOEIA_PATTERN.match(text):
            return True
        if len(text) <= 4:
            has_punct = any(c in "！!。…~～" for c in text)
            has_onomatopoeia = any(c in SINGLE_ONOMATOPOEIA for c in text)
            if has_punct and has_onomatopoeia:
                return True
        return False

    def _compute_window_embeddings(self, paragraphs: List[Tuple[int, int, str]]) -> List[List[float]]:
        window_embeddings: List[List[float]] = []
        half_window = self._window_size // 2
        for i in range(len(paragraphs)):
            start_idx = max(0, i - half_window)
            end_idx = min(len(paragraphs), i + half_window + 1)
            window_text = "\n".join(paragraphs[j][2] for j in range(start_idx, end_idx))
            emb = self._embedding_client.get_embedding(window_text)
            if emb:
                window_embeddings.append(emb)
            else:
                window_embeddings.append([])
        return window_embeddings

    def _compute_window_similarities(self, window_embeddings: List[List[float]]) -> List[float]:
        similarities: List[float] = []
        for i in range(len(window_embeddings) - 1):
            if window_embeddings[i] and window_embeddings[i + 1]:
                sim = EmbeddingClient.compute_similarity(window_embeddings[i], window_embeddings[i + 1])
                similarities.append(sim)
            else:
                similarities.append(0.5)
        return similarities

    def _compute_dynamic_threshold(self, similarities: List[float]) -> float:
        if not similarities:
            return 0.5
        sorted_sims = sorted(similarities)
        percentile_idx = max(0, int(len(sorted_sims) * self._percentile / 100))
        threshold = sorted_sims[percentile_idx]
        threshold = max(0.3, min(0.9, threshold))
        logger.debug(f"dynamic threshold computed: {threshold:.4f} (percentile={self._percentile}%)")
        return threshold

    def _detect_boundaries(
        self,
        similarities: List[float],
        threshold: float,
        onomatopoeia_indices: set,
    ) -> List[int]:
        boundaries: List[int] = [0]
        for i, sim in enumerate(similarities):
            if i in onomatopoeia_indices or i + 1 in onomatopoeia_indices:
                continue
            if sim < threshold:
                boundaries.append(i + 1)
        boundaries.append(len(similarities) + 1)
        return boundaries

    def _create_chunks_from_boundaries(
        self,
        paragraphs: List[Tuple[int, int, str]],
        boundaries: List[int],
        chapter_title: str | None,
        max_chars: int,
    ) -> List[Chunk]:
        chunks: List[Chunk] = []
        idx = 0
        for i in range(len(boundaries) - 1):
            start_idx = boundaries[i]
            end_idx = boundaries[i + 1]
            group = paragraphs[start_idx:end_idx]
            if not group:
                continue
            chunk_text_content = "\n\n".join(p[2] for p in group)
            chunk_start = group[0][0]
            chunk_end = group[-1][1]
            if len(chunk_text_content) > max_chars:
                sub_chunks = self._split_long_chunk(group, max_chars, chapter_title, idx)
                chunks.extend(sub_chunks)
                idx += len(sub_chunks)
            else:
                chunks.append(
                    Chunk(
                        index=idx,
                        text=chunk_text_content,
                        start=chunk_start,
                        end=chunk_end,
                        chapter_title=chapter_title,
                    )
                )
                idx += 1
        return chunks

    def _create_single_chunk(
        self,
        paragraphs: List[Tuple[int, int, str]],
        chapter_title: str | None,
    ) -> List[Chunk]:
        p_start, p_end, p_text = paragraphs[0]
        return [Chunk(index=0, text=p_text, start=p_start, end=p_end, chapter_title=chapter_title)]

    def _apply_min_chars_constraint(self, chunks: List[Chunk], max_chars: int) -> List[Chunk]:
        if not chunks or self._min_chars <= 0:
            return chunks
        merged: List[Chunk] = []
        i = 0
        while i < len(chunks):
            current = chunks[i]
            while i + 1 < len(chunks) and len(current.text) < self._min_chars:
                next_chunk = chunks[i + 1]
                merged_text = current.text + "\n\n" + next_chunk.text
                if len(merged_text) > max_chars:
                    break
                current = Chunk(
                    index=current.index,
                    text=merged_text,
                    start=current.start,
                    end=next_chunk.end,
                    chapter_title=current.chapter_title,
                )
                i += 1
            merged.append(current)
            i += 1
        if len(merged) >= 2 and len(merged[-1].text) < self._min_chars:
            last = merged[-1]
            prev = merged[-2]
            merged_text = prev.text + "\n\n" + last.text
            if len(merged_text) <= max_chars:
                merged[-2] = Chunk(
                    index=prev.index,
                    text=merged_text,
                    start=prev.start,
                    end=last.end,
                    chapter_title=prev.chapter_title,
                )
                merged.pop()
        return merged

    def _split_long_chunk(
        self,
        paragraphs: List[Tuple[int, int, str]],
        max_chars: int,
        chapter_title: str | None,
        start_idx: int,
    ) -> List[Chunk]:
        chunks: List[Chunk] = []
        current: List[Tuple[int, int, str]] = []
        current_len = 0
        idx = start_idx
        for p in paragraphs:
            p_len = len(p[2])
            if current and current_len + p_len > max_chars:
                chunk_text = "\n\n".join(item[2] for item in current)
                chunks.append(
                    Chunk(
                        index=idx,
                        text=chunk_text,
                        start=current[0][0],
                        end=current[-1][1],
                        chapter_title=chapter_title,
                    )
                )
                idx += 1
                current = [p]
                current_len = p_len
            else:
                current.append(p)
                current_len += p_len
        if current:
            chunk_text = "\n\n".join(item[2] for item in current)
            chunks.append(
                Chunk(
                    index=idx,
                    text=chunk_text,
                    start=current[0][0],
                    end=current[-1][1],
                    chapter_title=chapter_title,
                )
            )
        return chunks

    def _reindex(self, chunks: List[Chunk]) -> List[Chunk]:
        """
        重新索引 chunks 列表。

        创建时间: 2026-03-13
        创建者: TraeAI
        任务: fix-duplicate-reindex-function
        功能: 调用模块级 _reindex 函数，消除重复代码

        修改时间: 2026-03-13
        修改者: TraeAI
        任务: fix-duplicate-reindex-function
        修改原因: 原方法与模块级 _reindex 函数功能完全相同，改为调用模块级函数以消除重复
        """
        return _reindex(chunks)


def chunk_text(
    text: str,
    max_chars: int | None = None,
    overlap: int | None = None,
    split_by_chapter: bool | None = None,
    use_semantic: bool | None = None,
) -> List[Chunk]:
    if use_semantic is None:
        use_semantic = settings.chunking.use_semantic_chunking
    if use_semantic:
        chunker = SemanticChunker()
        return chunker.chunk_text_semantic(text)
    if max_chars is None:
        max_chars = settings.chunking.max_chars
    if overlap is None:
        overlap = settings.chunking.overlap
    if split_by_chapter is None:
        split_by_chapter = settings.chunking.split_by_chapter
    if not text:
        return []
    if max_chars <= 0:
        raise ValueError("max_chars must be positive")
    if overlap < 0:
        raise ValueError("overlap must be non-negative")
    chunks: List[Chunk] = []
    if split_by_chapter:
        chapter_ranges = detect_chapters(text)
    else:
        chapter_ranges = []
    if chapter_ranges:
        for start, end, title in chapter_ranges:
            chunks.extend(_chunk_by_paragraph(text, start, end, max_chars, title))
        return chunks
    return _chunk_by_paragraph(text, 0, len(text), max_chars, None)


def chunk_documents(
    texts: Iterable[str],
    max_chars: int | None = None,
    overlap: int | None = None,
    split_by_chapter: bool | None = None,
    use_semantic: bool | None = None,
) -> List[Chunk]:
    if max_chars is None:
        max_chars = settings.chunking.max_chars
    if overlap is None:
        overlap = settings.chunking.overlap
    if split_by_chapter is None:
        split_by_chapter = settings.chunking.split_by_chapter
    if use_semantic is None:
        use_semantic = settings.chunking.use_semantic_chunking
    chunks: List[Chunk] = []
    for text in texts:
        chunks.extend(chunk_text(text, max_chars, overlap, split_by_chapter, use_semantic))
    return _reindex(chunks)


def _chunk_range(
    text: str,
    start: int,
    end: int,
    max_chars: int,
    overlap: int,
    title: str | None,
) -> List[Chunk]:
    chunks: List[Chunk] = []
    idx = 0
    cursor = start
    while cursor < end:
        chunk_end = min(cursor + max_chars, end)
        chunk_text = text[cursor:chunk_end].strip()
        if chunk_text:
            chunks.append(
                Chunk(
                    index=idx,
                    text=chunk_text,
                    start=cursor,
                    end=chunk_end,
                    chapter_title=title,
                )
            )
            idx += 1
        if chunk_end >= end:
            break
        cursor = max(cursor + max_chars - overlap, cursor + 1)
    return chunks


def _chunk_by_paragraph(
    text: str,
    start: int,
    end: int,
    max_chars: int,
    title: str | None,
) -> List[Chunk]:
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


def _iter_paragraphs(
    text: str,
    start: int,
    end: int,
) -> List[Tuple[int, int, str]]:
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


def _reindex(chunks: List[Chunk]) -> List[Chunk]:
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
