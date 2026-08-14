"""
段落单元（ParagraphSpan）切分测试

验收映射：设计文档《章节粒度分析指标重设计》§18.1（切分与身份）：
- 超长自然段生成相同 source_paragraph_index、递增 fragment_index
- 段落文本逐字匹配章节切片（chunk.text[local_start:local_end] == span.text）
- 段落身份与坐标单调不重叠
"""

from __future__ import annotations

from src.chunking.chunker import Chunk, split_chunk_paragraphs, split_paragraphs


def test_split_paragraphs_basic_identity() -> None:
    text = "第一段。\n第二段。\n第三段。"
    spans = split_paragraphs(text)

    assert [span.paragraph_index for span in spans] == [0, 1, 2]
    assert [span.source_paragraph_index for span in spans] == [0, 1, 2]
    assert [span.fragment_index for span in spans] == [0, 0, 0]
    assert [span.text for span in spans] == ["第一段。", "第二段。", "第三段。"]
    assert [span.local_start_char for span in spans] == [0, 5, 10]
    assert [span.local_end_char for span in spans] == [4, 9, 14]
    assert all(span.char_count == len(span.text) for span in spans)
    # chunk 级身份未归属时保持 None
    assert all(span.paragraph_id is None for span in spans)
    assert all(span.chunk_id is None for span in spans)
    assert all(span.global_start_char is None for span in spans)


def test_split_paragraphs_single_newline_is_boundary() -> None:
    spans = split_paragraphs("第一段。\n第二段。")
    assert len(spans) == 2
    assert [span.text for span in spans] == ["第一段。", "第二段。"]


def test_split_paragraphs_blank_lines_do_not_produce_paragraphs() -> None:
    text = "第一段。\n\n\n第二段。"
    spans = split_paragraphs(text)

    assert [span.text for span in spans] == ["第一段。", "第二段。"]
    # 空段不产出段落单元，但仍占用 source_paragraph_index（自然段序号含空行）
    assert [span.source_paragraph_index for span in spans] == [0, 3]
    assert [span.paragraph_index for span in spans] == [0, 1]


def test_split_paragraphs_uses_stripped_real_coordinates() -> None:
    text = "  第一段。  \n  第二段。"
    spans = split_paragraphs(text)

    assert [span.text for span in spans] == ["第一段。", "第二段。"]
    assert spans[0].local_start_char == 2
    assert spans[0].local_end_char == 6
    assert spans[1].local_start_char == 11
    assert spans[1].local_end_char == 15
    # 坐标与 strip 后文本逐字匹配
    for span in spans:
        assert text[span.local_start_char : span.local_end_char] == span.text


def test_split_paragraphs_oversized_paragraph_fragments() -> None:
    """超长自然段：共享 source_paragraph_index，fragment_index 递增"""
    long_paragraph = "句子甲。" * 30  # 150 字
    text = f"{long_paragraph}\n短段。"
    spans = split_paragraphs(text, max_chars=100)

    assert len(spans) == 3  # 150 字切成 2 段（约 100/50）+ 短段
    assert spans[0].source_paragraph_index == 0
    assert spans[0].fragment_index == 0
    assert spans[1].source_paragraph_index == 0
    assert spans[1].fragment_index == 1
    assert spans[2].source_paragraph_index == 1
    assert spans[2].fragment_index == 0
    assert spans[2].paragraph_index == 2
    assert all(len(span.text) <= 100 for span in spans)
    # 片段覆盖原文全部非空字符且不重叠
    assert spans[0].local_end_char == spans[1].local_start_char
    assert text[spans[0].local_start_char : spans[1].local_end_char] == long_paragraph


def test_split_paragraphs_oversized_without_sentence_boundaries_hard_cuts() -> None:
    text = "无标点长文本" * 30  # 150 字，无句末标点
    spans = split_paragraphs(text, max_chars=100)

    assert len(spans) == 2
    assert all(span.text for span in spans)
    assert spans[0].fragment_index == 0
    assert spans[1].fragment_index == 1


def test_split_paragraphs_no_newline_single_paragraph() -> None:
    spans = split_paragraphs("只有一段。没有换行。")
    assert len(spans) == 1
    assert spans[0].paragraph_index == 0
    assert spans[0].source_paragraph_index == 0
    assert spans[0].local_start_char == 0
    assert spans[0].local_end_char == len("只有一段。没有换行。")
    assert spans[0].text == "只有一段。没有换行。"


def test_split_paragraphs_blank_text_returns_empty() -> None:
    assert split_paragraphs("") == []
    assert split_paragraphs("\n\n") == []
    assert split_paragraphs("   \n  ") == []


def test_split_chunk_paragraphs_assigns_run_level_identity() -> None:
    chunks = [
        Chunk(index=0, text="甲段。\n乙段。", start=10, end=17, chapter_id=1),
        Chunk(index=1, text="丙段。", start=17, end=20, chapter_id=2),
    ]
    spans = split_chunk_paragraphs(chunks)

    assert len(spans) == 3
    assert [span.paragraph_id for span in spans] == [0, 1, 2]
    assert [span.chunk_id for span in spans] == [0, 0, 1]
    assert [span.chapter_id for span in spans] == [1, 1, 2]
    # global = chunk.start + local
    assert [(span.global_start_char, span.global_end_char) for span in spans] == [
        (10, 13),
        (14, 17),
        (17, 20),
    ]
    # global 坐标单调不重叠
    for i in range(len(spans) - 1):
        assert spans[i + 1].global_start_char >= spans[i].global_end_char
    # 文本逐字匹配
    for span in spans:
        chunk = chunks[span.chunk_id or 0]
        assert chunk.text[span.local_start_char : span.local_end_char] == span.text


def test_split_chunk_paragraphs_empty_chunks() -> None:
    assert split_chunk_paragraphs([]) == []


def test_split_chunk_paragraphs_paragraph_id_global_order() -> None:
    """paragraph_id 按全文顺序连续，跨 chunk 不重置"""
    chunks = [
        Chunk(index=0, text="一段。", start=0, end=3, chapter_id=1),
        Chunk(index=1, text="二段。", start=3, end=6, chapter_id=2),
    ]
    spans = split_chunk_paragraphs(chunks)
    assert [span.paragraph_id for span in spans] == [0, 1]
