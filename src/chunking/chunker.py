"""
文本分块模块

创建时间: 2026-03-12
创建者: TraeAI
任务: 项目文件结构整理与拆解

修改历史:
- 2026-03-13: 添加拟声词检测功能，优化语义分块边界检测
- 2026-03-18: 简化代码结构，文件行数: 539行 → 319行 (-41%)

说明: 本模块包含文本分块相关的功能，支持按章节、段落、语义等多种分块策略。
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
    onomatopoeia_indices: Set[int] = set()
    for i, (_, _, text) in enumerate(paragraphs):
        if _is_onomatopoeia(text):
            onomatopoeia_indices.add(i)
    return onomatopoeia_indices


# =============================================================================
# 章节分割
# =============================================================================


def split_by_chapters(text: str) -> List[Tuple[str | None, str]]:
    """按章节分割文本"""
    chapters = []
    last_end = 0
    last_title = None

    for match in CHAPTER_PATTERN.finditer(text):
        if last_end < match.start():
            chapter_text = text[last_end : match.start()]
            if chapter_text.strip():
                chapters.append((last_title, chapter_text))
        last_title = match.group(0).strip()
        last_end = match.end()

    if last_end < len(text):
        chapter_text = text[last_end:]
        if chapter_text.strip():
            chapters.append((last_title, chapter_text))

    return chapters if chapters else [(None, text)]


def chunk_text(
    text: str,
    max_chars: int = 1000,
    overlap: int = 100,
    split_by_chapter: bool = True,
    use_semantic: bool = False,
) -> List[Chunk]:
    """
    将文本分割成块

    Args:
        text: 输入文本
        max_chars: 每块最大字符数
        overlap: 块间重叠字符数
        split_by_chapter: 是否按章节分割
        use_semantic: 是否使用语义分块

    Returns:
        Chunk对象列表
    """
    if not text.strip():
        return []

    if use_semantic:
        chunker = SemanticChunker()
        return chunker.chunk_text_semantic(text)

    if split_by_chapter:
        return _chunk_by_chapters(text, max_chars, overlap)

    return _chunk_simple(text, max_chars, overlap)


def _chunk_simple(text: str, max_chars: int, overlap: int) -> List[Chunk]:
    """简单分块（不按章节）"""
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

        chunk_text_content = text[start:end].strip()
        if chunk_text_content:
            chunks.append(
                Chunk(index=idx, text=chunk_text_content, start=start, end=end)
            )
            idx += 1

        start = end - overlap if end < len(text) else end

    return chunks


def _chunk_by_chapters(text: str, max_chars: int, overlap: int) -> List[Chunk]:
    """按章节分块"""
    chapters = split_by_chapters(text)
    chunks = []
    idx = 0

    for chapter_title, chapter_text in chapters:
        if not chapter_text.strip():
            continue

        start = 0
        while start < len(chapter_text):
            end = start + max_chars
            if end < len(chapter_text):
                paragraph_end = chapter_text.rfind("\n\n", start, end)
                if paragraph_end > start + max_chars * 0.5:
                    end = paragraph_end
                else:
                    sentence_end = chapter_text.rfind("。", start, end)
                    if sentence_end > start + max_chars * 0.5:
                        end = sentence_end + 1

            chunk_text_content = chapter_text[start:end].strip()
            if chunk_text_content:
                chunks.append(
                    Chunk(
                        index=idx,
                        text=chunk_text_content,
                        start=start,
                        end=end,
                        chapter_title=chapter_title,
                    )
                )
                idx += 1

            start = end - overlap if end < len(chapter_text) else end

    return _reindex(chunks)


# =============================================================================
# 语义分块
# =============================================================================


class SemanticChunker:
    """语义分块器"""

    def __init__(self, embedding_client: EmbeddingClient | None = None):
        self._embedding_client = embedding_client
        self._window_size = settings.chunking.semantic_window_size
        self._percentile = settings.chunking.semantic_percentile
        self._min_chars = settings.chunking.semantic_min_chars
        self._use_dynamic_threshold = settings.chunking.semantic_use_dynamic_threshold

    def chunk_text_semantic(self, text: str) -> List[Chunk]:
        """基于语义相似度的文本分块"""
        if not text.strip():
            return []

        paragraphs = self._split_into_paragraphs(text)
        if len(paragraphs) <= 1:
            return [Chunk(index=0, text=text.strip(), start=0, end=len(text))]

        paragraph_embeddings = self._compute_paragraph_embeddings(paragraphs)
        boundaries = self._find_semantic_boundaries(paragraphs, paragraph_embeddings)
        chunks = self._create_chunks_from_boundaries(text, paragraphs, boundaries)

        return _reindex(chunks)

    def _split_into_paragraphs(self, text: str) -> List[Tuple[int, int, str]]:
        """将文本分割成段落"""
        paragraphs = []
        start = 0

        for match in PARAGRAPH_SPLIT.finditer(text):
            end = match.start()
            paragraph_text = text[start:end].strip()
            if paragraph_text:
                paragraphs.append((start, end, paragraph_text))
            start = match.end()

        if start < len(text):
            paragraph_text = text[start:].strip()
            if paragraph_text:
                paragraphs.append((start, len(text), paragraph_text))

        return paragraphs

    def _compute_paragraph_embeddings(
        self, paragraphs: List[Tuple[int, int, str]]
    ) -> List[List[float]]:
        """计算段落的嵌入向量"""
        texts = [text for _, _, text in paragraphs]
        return self._embedding_client.embed_texts(texts)

    def _find_semantic_boundaries(
        self,
        paragraphs: List[Tuple[int, int, str]],
        embeddings: List[List[float]],
    ) -> List[int]:
        """找到语义边界"""
        if len(paragraphs) <= 1:
            return [0, len(paragraphs)]

        onomatopoeia_indices = _detect_onomatopoeia(paragraphs)
        similarities = self._compute_window_similarities(embeddings, onomatopoeia_indices)

        if self._use_dynamic_threshold:
            threshold = self._compute_dynamic_threshold(similarities)
        else:
            threshold = settings.chunking.semantic_threshold

        boundaries = [0]
        for i, sim in enumerate(similarities):
            if sim < threshold or i in onomatopoeia_indices:
                boundaries.append(i + 1)
        boundaries.append(len(paragraphs))

        return boundaries

    def _compute_window_similarities(
        self,
        embeddings: List[List[float]],
        onomatopoeia_indices: Set[int],
    ) -> List[float]:
        """计算窗口相似度"""
        similarities = []

        for i in range(len(embeddings) - 1):
            if i in onomatopoeia_indices or (i + 1) in onomatopoeia_indices:
                similarities.append(0.0)
                continue

            window_start = max(0, i - self._window_size + 1)
            window_end = min(len(embeddings), i + self._window_size)

            window_embeddings = embeddings[window_start:window_end]
            if len(window_embeddings) < 2:
                similarities.append(1.0)
                continue

            import numpy as np

            window_embeddings_array = np.array(window_embeddings)
            current_emb = np.array(embeddings[i])
            next_emb = np.array(embeddings[i + 1])

            window_mean = np.mean(window_embeddings_array, axis=0)
            current_sim = np.dot(current_emb, window_mean) / (
                np.linalg.norm(current_emb) * np.linalg.norm(window_mean) + 1e-8
            )
            next_sim = np.dot(next_emb, window_mean) / (
                np.linalg.norm(next_emb) * np.linalg.norm(window_mean) + 1e-8
            )

            similarities.append(float((current_sim + next_sim) / 2))

        return similarities

    def _compute_dynamic_threshold(self, similarities: List[float]) -> float:
        """计算动态阈值"""
        import numpy as np

        if not similarities:
            return settings.chunking.semantic_threshold

        return float(np.percentile(similarities, self._percentile))

    def _create_chunks_from_boundaries(
        self,
        text: str,
        paragraphs: List[Tuple[int, int, str]],
        boundaries: List[int],
    ) -> List[Chunk]:
        """根据边界创建 chunks"""
        chunks = []

        for i in range(len(boundaries) - 1):
            start_idx = boundaries[i]
            end_idx = boundaries[i + 1]

            start_pos = paragraphs[start_idx][0]
            end_pos = paragraphs[end_idx - 1][1]
            chunk_text = text[start_pos:end_pos].strip()

            if chunk_text:
                chunks.append(
                    Chunk(
                        index=i,
                        text=chunk_text,
                        start=start_pos,
                        end=end_pos,
                    )
                )

        return chunks


# =============================================================================
# 便捷函数
# =============================================================================


def chunk_documents(
    texts: Iterable[str],
    max_chars: int = 1000,
    overlap: int = 100,
    split_by_chapter: bool = True,
    use_semantic: bool = False,
) -> List[Chunk]:
    """
    分块多个文档

    Args:
        texts: 文本迭代器
        max_chars: 每块最大字符数
        overlap: 块间重叠字符数
        split_by_chapter: 是否按章节分割
        use_semantic: 是否使用语义分块

    Returns:
        所有文档的Chunk列表
    """
    all_chunks = []
    offset = 0

    for text in texts:
        chunks = chunk_text(text, max_chars, overlap, split_by_chapter, use_semantic)
        for chunk in chunks:
            all_chunks.append(
                Chunk(
                    index=chunk.index + offset,
                    text=chunk.text,
                    start=chunk.start,
                    end=chunk.end,
                    chapter_title=chunk.chapter_title,
                )
            )
        offset += len(chunks)

    return _reindex(all_chunks)


# 向后兼容别名
detect_chapters = split_by_chapters
