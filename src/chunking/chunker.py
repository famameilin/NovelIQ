"""
文本分块模块


本模块包含文本分块相关的功能，支持按章节、段落、语义等多种分块策略。
"""

from __future__ import annotations

import inspect
import re
from collections.abc import Awaitable, Callable, Iterable
from dataclasses import dataclass

from src.api.models.events import StreamEvent
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


def _reindex(chunks: list[Chunk]) -> list[Chunk]:
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


def _resolve_trimmed_span(text: str, start: int, end: int) -> tuple[int, int, str] | None:
    """
    解析切片在原文中的真实字符范围，并返回去首尾空白后的文本。

    chunk/paragraph 最终落库和对外暴露的 offset 必须对应“实际保留下来的文本”，
          不能继续沿用 strip() 之前的粗边界；否则全文 offset 会系统性偏移。
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
    按章节分割文本，并保留章节正文在全文中的字符范围。

    `split_by_chapters()` 旧接口只返回标题和正文，无法支撑全文 offset；
          这里新增内部 helper，把章节正文的全文起止位置一并保留下来。
    """
    chapters: list[tuple[str | None, str, int, int]] = []
    last_end = 0
    last_title: str | None = None

    for match in CHAPTER_PATTERN.finditer(text):
        if last_end < match.start():
            chapter_text = text[last_end : match.start()]
            if chapter_text.strip():
                chapters.append((last_title, chapter_text, last_end, match.start()))
        last_title = match.group(0).strip()
        last_end = match.end()

    if last_end < len(text):
        chapter_text = text[last_end:]
        if chapter_text.strip():
            chapters.append((last_title, chapter_text, last_end, len(text)))

    if chapters:
        return chapters
    return [(None, text, 0, len(text))]


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


def _detect_onomatopoeia(paragraphs: list[tuple[int, int, str]]) -> set[int]:
    """检测拟声词段落索引"""
    onomatopoeia_indices: set[int] = set()
    for i, (_, _, text) in enumerate(paragraphs):
        if _is_onomatopoeia(text):
            onomatopoeia_indices.add(i)
    return onomatopoeia_indices


# =============================================================================
# 章节分割
# =============================================================================


def split_by_chapters(text: str) -> list[tuple[str | None, str]]:
    """
    按章节分割文本。

    继续保留旧返回签名，内部改为复用带 offset 的 helper，避免外围调用点被迫同步改签名。
    """
    return [
        (chapter_title, chapter_text)
        for chapter_title, chapter_text, _, _ in _split_by_chapters_with_offsets(text)
    ]


async def chunk_text(
    text: str,
    max_chars: int = 1000,
    overlap: int = 100,
    split_by_chapter: bool = True,
    use_semantic: bool = False,
    emitter: Callable[[StreamEvent], Awaitable[None]] | None = None,
) -> list[Chunk]:
    """
    将文本分割成块（async 版本）

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
        from src.models.local.embedding import EmbeddingClient

        embedding_client = EmbeddingClient()
        chunker = SemanticChunker(embedding_client=embedding_client, emitter=emitter)
        return await chunker.chunk_text_semantic(text)

    if split_by_chapter:
        return _chunk_by_chapters(text, max_chars, overlap)

    return _chunk_simple(text, max_chars, overlap)


def _chunk_simple(text: str, max_chars: int, overlap: int) -> list[Chunk]:
    """
    简单分块（不按章节）。

    生成的 `Chunk.start/end` 改为最终保留文本的真实全文范围，
              不再沿用 strip() 之前的粗切片边界。
    """
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
            chunks.append(Chunk(index=idx, text=chunk_text_content, start=chunk_start, end=chunk_end))
            idx += 1

        start = end - overlap if end < len(text) else end

    return chunks


def _chunk_by_chapters(text: str, max_chars: int, overlap: int) -> list[Chunk]:
    """
    按章节分块。

    章节内局部切片仍按正文处理，但写回 Chunk 时统一折算为整本文本的真实全文 offset。
    """
    chapters = _split_by_chapters_with_offsets(text)
    chunks = []
    idx = 0

    for chapter_title, chapter_text, chapter_start_offset, _ in chapters:
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

            span = _resolve_trimmed_span(chapter_text, start, end)
            if span is not None:
                local_start, local_end, chunk_text_content = span
                chunks.append(
                    Chunk(
                        index=idx,
                        text=chunk_text_content,
                        start=chapter_start_offset + local_start,
                        end=chapter_start_offset + local_end,
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
    """语义分块器

    """

    def __init__(
        self,
        embedding_client: EmbeddingClient | None = None,
        emitter: Callable[[StreamEvent], Awaitable[None]] | None = None,
    ):
        self._embedding_client = embedding_client
        self._emitter = emitter
        self._window_size = settings.chunking.semantic_window_size
        self._percentile = settings.chunking.semantic_percentile
        self._min_chars = settings.chunking.semantic_min_chars
        self._max_chars = settings.chunking.semantic_max_chars
        self._use_dynamic_threshold = settings.chunking.semantic_use_dynamic_threshold

    async def chunk_text_semantic(self, text: str) -> list[Chunk]:
        """基于语义相似度的文本分块（async 版本）"""
        if not text.strip():
            return []

        paragraphs = self._split_into_paragraphs(text)
        if len(paragraphs) <= 1:
            return [Chunk(index=0, text=text.strip(), start=0, end=len(text))]

        paragraph_embeddings = await self._compute_paragraph_embeddings(paragraphs)
        boundaries = self._find_semantic_boundaries(paragraphs, paragraph_embeddings)
        chunks = self._create_chunks_from_boundaries(text, paragraphs, boundaries)

        return _reindex(chunks)

    async def _compute_paragraph_embeddings(self, paragraphs: list[tuple[int, int, str]]) -> list[list[float]]:
        """计算段落的嵌入向量（async 版本）"""
        if self._embedding_client is None:
            return []
        texts = [text for _, _, text in paragraphs]
        embed_texts = self._embedding_client.embed_texts
        try:
            signature = inspect.signature(embed_texts)
        except (TypeError, ValueError):
            signature = None

        if signature is not None and "progress_callback" in signature.parameters:
            return await embed_texts(
                texts,
                progress_callback=self._emit_embedding_progress,
            )
        return await embed_texts(texts)

    async def _emit_embedding_progress(self, completed_batches: int, total_batches: int, total_items: int) -> None:
        """
        发射语义分块 paragraph embedding 的批次进度。

        语义分块阶段本身没有 chunk 级循环，必须把 embed_texts 的批量完成信号翻译成 SSE，
                  前端才能在长文本 paragraph 向量化时看到持续进度。
        """
        if self._emitter is None or total_batches <= 0:
            return

        sub_percent = (completed_batches / total_batches) * 100
        # 这里复用 preprocess/stage_progress 协议，不新增前端事件类型；
        # current/total 表示“已完成批次/总批次”，message 单独说明这是 paragraph embedding。
        await self._emitter(
            StreamEvent(
                action="progress",
                stage="preprocess",
                sub_stage="semantic_chunking_embedding",
                current=completed_batches,
                total=total_batches,
                sub_percent=sub_percent,
                message=(
                    f"语义分块段落向量计算 {completed_batches}/{total_batches}"
                    f" 批（共 {total_items} 段）"
                ),
            )
        )

    def _split_into_paragraphs(self, text: str) -> list[tuple[int, int, str]]:
        """
        将文本分割成段落。

        段落的 start/end 改为 strip 后正文在全文中的真实坐标，
                  后续 semantic chunk 和 paragraph global offset 都直接复用这组坐标。
        """
        paragraphs = []
        start = 0

        for match in PARAGRAPH_SPLIT.finditer(text):
            end = match.start()
            span = _resolve_trimmed_span(text, start, end)
            if span is not None:
                paragraphs.append(span)
            start = match.end()

        if start < len(text):
            span = _resolve_trimmed_span(text, start, len(text))
            if span is not None:
                paragraphs.append(span)

        return paragraphs

    def _find_semantic_boundaries(
        self,
        paragraphs: list[tuple[int, int, str]],
        embeddings: list[list[float]],
    ) -> list[int]:
        """找到语义边界


        - 优先使用语义边界（模型判断）
        - 当累计长度超过 max_chars 时强制分割（工程约束）
        - 在段落边界分割，保持段落完整性
        """
        if len(paragraphs) <= 1:
            return [0, len(paragraphs)]

        onomatopoeia_indices = _detect_onomatopoeia(paragraphs)
        similarities = self._compute_window_similarities(embeddings, onomatopoeia_indices)

        if self._use_dynamic_threshold:
            threshold = self._compute_dynamic_threshold(similarities)
        else:
            threshold = settings.chunking.semantic_threshold

        paragraph_lengths = [len(text) for _, _, text in paragraphs]

        boundaries = [0]
        current_len = 0

        for i, sim in enumerate(similarities):
            current_len += paragraph_lengths[i]

            # 语义边界 OR 拟声词边界 OR 长度超限
            if sim < threshold or i in onomatopoeia_indices or current_len > self._max_chars:
                boundaries.append(i + 1)
                current_len = 0

        boundaries.append(len(paragraphs))

        return boundaries

    def _compute_window_similarities(
        self,
        embeddings: list[list[float]],
        onomatopoeia_indices: set[int],
    ) -> list[float]:
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
            next_sim = np.dot(next_emb, window_mean) / (np.linalg.norm(next_emb) * np.linalg.norm(window_mean) + 1e-8)

            similarities.append(float((current_sim + next_sim) / 2))

        return similarities

    def _compute_dynamic_threshold(self, similarities: list[float]) -> float:
        """计算动态阈值"""
        import numpy as np

        if not similarities:
            return settings.chunking.semantic_threshold

        return float(np.percentile(similarities, self._percentile))

    def _create_chunks_from_boundaries(
        self,
        text: str,
        paragraphs: list[tuple[int, int, str]],
        boundaries: list[int],
    ) -> list[Chunk]:
        """根据边界创建 chunks


        依赖 paragraph 的真实全文坐标，确保 semantic chunk 最终也落成真实全文 offset。
        """
        chunks: list[Chunk] = []

        for i in range(len(boundaries) - 1):
            start_idx = boundaries[i]
            end_idx = boundaries[i + 1]

            start_pos = paragraphs[start_idx][0]
            end_pos = paragraphs[end_idx - 1][1]
            chunk_text = text[start_pos:end_pos]

            if not chunk_text:
                continue

            chunk_len = len(chunk_text)

            # 如果块超长，按句子边界拆分
            if chunk_len > self._max_chars:
                sub_chunks = self._split_long_chunk(chunk_text, start_pos)
                chunks.extend(sub_chunks)
            # 如果块太小，尝试合并到前一个块
            elif chunk_len < self._min_chars and chunks:
                prev_chunk = chunks[-1]
                merged_text = text[prev_chunk.start:end_pos]
                # 检查合并后是否超长
                if len(merged_text) > self._max_chars:
                    # 不合并，保持原样
                    chunks.append(
                        Chunk(
                            index=len(chunks),
                            text=chunk_text,
                            start=start_pos,
                            end=end_pos,
                        )
                    )
                else:
                    chunks[-1] = Chunk(
                        index=prev_chunk.index,
                        text=merged_text,
                        start=prev_chunk.start,
                        end=end_pos,
                    )
            else:
                chunks.append(
                    Chunk(
                        index=len(chunks),
                        text=chunk_text,
                        start=start_pos,
                        end=end_pos,
                    )
                )

        return chunks

    def _split_long_chunk(self, text: str, start_pos: int) -> list[Chunk]:
        """拆分超长块


        - 优先在句子边界（句号）分割
        - 保证每个子块不超过 max_chars
        - 如果无法找到合适的句子边界，则强制按字符分割

        子块同样使用真实全文坐标，不再沿用 strip 前的粗边界。
        """
        chunks: list[Chunk] = []
        offset = 0

        while offset < len(text):
            end = min(offset + self._max_chars, len(text))

            if end < len(text):
                last_period = text.rfind("。", offset, end)
                if last_period > offset + self._max_chars * 0.5:
                    end = last_period + 1
                else:
                    last_exclamation = text.rfind("！", offset, end)
                    if last_exclamation > offset + self._max_chars * 0.5:
                        end = last_exclamation + 1
                    else:
                        last_question = text.rfind("？", offset, end)
                        if last_question > offset + self._max_chars * 0.5:
                            end = last_question + 1

            span = _resolve_trimmed_span(text, offset, end)
            if span is not None:
                local_start, local_end, chunk_text = span
                chunks.append(
                    Chunk(
                        index=len(chunks),
                        text=chunk_text,
                        start=start_pos + local_start,
                        end=start_pos + local_end,
                    )
                )
            offset = end

        return chunks


# =============================================================================
# 便捷函数
# =============================================================================


async def chunk_documents(
    texts: Iterable[str],
    max_chars: int = 1000,
    overlap: int = 100,
    split_by_chapter: bool = True,
    use_semantic: bool = False,
    emitter: Callable[[StreamEvent], Awaitable[None]] | None = None,
) -> list[Chunk]:
    """
    分块多个文档（async 版本）

    Args:
        texts: 文本迭代器
        max_chars: 每块最大字符数
        overlap: 块间重叠字符数
        split_by_chapter: 是否按章节分割
        use_semantic: 是否使用语义分块

    Returns:
        所有文档的Chunk列表

    多文档场景下将每个文档的 chunk offset 折算为 run 级连续全文坐标；
              这里不额外注入分隔符，run-global offset 口径定义为“按输入顺序直接拼接的规范化文档文本”。
    """
    all_chunks = []
    chunk_index_offset = 0
    document_char_offset = 0

    for text in texts:
        chunks = await chunk_text(
            text,
            max_chars,
            overlap,
            split_by_chapter,
            use_semantic,
            emitter=emitter,
        )
        for chunk in chunks:
            all_chunks.append(
                Chunk(
                    index=chunk.index + chunk_index_offset,
                    text=chunk.text,
                    start=chunk.start + document_char_offset,
                    end=chunk.end + document_char_offset,
                    chapter_title=chunk.chapter_title,
                )
            )
        chunk_index_offset += len(chunks)
        document_char_offset += len(text)

    return _reindex(all_chunks)
