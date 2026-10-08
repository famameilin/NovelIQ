"""文本单元行形态（设计文档《章节粒度分析指标重设计》§3）

2026-10-06 自 src/chunking 收归：这两者是被存储层落库的行形态——
`Chunk` 是章级文本块，`ParagraphSpan` 是段落单元（分析的最小事实单元）。
切分算法在 `src.text_processing.paragraphs`。
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ParagraphSpan:
    """
    段落单元：身份、来源与字符坐标

    - local_* 坐标相对所属 chunk 的 strip 后文本
    - global_* 坐标相对 run 级规范化全文（= chunk 全文偏移 + local 偏移）
    """

    # chunk 内段落顺序号（0 起），同一 chunk 内唯一且连续
    paragraph_index: int
    # 来源自然段在 chunk 内的序号（0 起）；超长自然段拆出的片段共享该值
    source_paragraph_index: int
    # 超长自然段被拆分后的片段序号（0 起）；未拆分的自然段恒为 0
    fragment_index: int
    local_start_char: int
    local_end_char: int
    text: str
    # 以下字段由 split_chunk_paragraphs 填充；split_paragraphs 直接输出时为 None
    paragraph_id: int | None = None
    chapter_id: int | None = None
    global_start_char: int | None = None
    global_end_char: int | None = None
    # 分词后 token 数；chunker 不负责分词，由调用方（preprocess）填充
    token_count: int | None = None

    @property
    def char_count(self) -> int:
        """段落文本字符数，保证 char_count = length(text) 守恒"""
        return len(self.text)


@dataclass(frozen=True)
class Chunk:
    """文本块数据类"""

    index: int
    text: str
    start: int
    end: int
    chapter_id: int
