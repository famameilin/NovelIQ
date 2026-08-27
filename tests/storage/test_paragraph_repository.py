"""ParagraphRepository 存储测试（paragraphs 段落事实源表）"""

from __future__ import annotations

import hashlib
import uuid
from dataclasses import replace

import pytest
from sqlalchemy.exc import IntegrityError

from src.chunking.chunker import Chunk, split_chunk_paragraphs
from src.chunking.spans import ParagraphSpan
from src.storage.models import Paragraph
from src.storage.repositories import ChapterRepository, RunRepository
from src.storage.repositories.paragraph_repository import ParagraphRepository
from tests.support.analysis_factories import insert_test_novel as _insert_test_novel

CHUNK_TEXT = "第一段。\n第二段。\n第三段。\n"


def _create_run(db_session) -> str:
    novel_id = uuid.uuid4().hex[:8]
    _insert_test_novel(novel_id, session=db_session)
    return RunRepository(db_session).create_run(
        novel_id=novel_id,
        source_path="test",
        title="Paragraph Repository Test",
    )


def _insert_chapter_texts(db_session, run_id: str, chunks: list[Chunk]) -> None:
    ChapterRepository(db_session).insert_chapter_texts(run_id, chunks)


def _make_spans(chunks: list[Chunk], token_counts: list[int] | None = None) -> list[ParagraphSpan]:
    """用 chunker 切出段落并补齐 token_count"""
    spans = split_chunk_paragraphs(chunks)
    if token_counts is None:
        token_counts = [10] * len(spans)
    return [replace(span, token_count=tc) for span, tc in zip(spans, token_counts, strict=True)]


def _single_chunk(text: str = "第一段。\n", start: int = 0) -> list[Chunk]:
    return [Chunk(index=0, text=text, start=start, end=start + len(text), chapter_id=1)]


def _span(
    *,
    paragraph_id: int,
    paragraph_index: int | None = None,
    chapter_id: int = 1,
    local_start: int,
    local_end: int,
    global_start: int,
    global_end: int,
    token_count: int = 1,
    source_paragraph_index: int = 0,
    fragment_index: int = 0,
) -> ParagraphSpan:
    """构造完整合法的 ParagraphSpan（坐标可自由篡改以触发校验失败）"""
    return ParagraphSpan(
        paragraph_index=paragraph_index if paragraph_index is not None else paragraph_id,
        source_paragraph_index=source_paragraph_index,
        fragment_index=fragment_index,
        local_start_char=local_start,
        local_end_char=local_end,
        text="x" * (local_end - local_start),
        paragraph_id=paragraph_id,
        chapter_id=chapter_id,
        global_start_char=global_start,
        global_end_char=global_end,
        token_count=token_count,
    )


def test_insert_and_fetch_paragraphs(db_session) -> None:
    run_id = _create_run(db_session)
    chunks = _single_chunk(CHUNK_TEXT, start=0)
    _insert_chapter_texts(db_session, run_id, chunks)
    spans = _make_spans(chunks, token_counts=[3, 5, 7])

    repo = ParagraphRepository(db_session)
    assert repo.insert_paragraphs(run_id, spans) == 3
    assert repo.count_paragraphs(run_id) == 3
    assert repo.has_paragraphs(run_id)
    assert repo.count_paragraphs("no-such-run") == 0
    assert not repo.has_paragraphs("no-such-run")

    rows = repo.fetch_paragraph_rows(run_id)
    assert [row.paragraph_id for row in rows] == [0, 1, 2]
    for i, (row, span) in enumerate(zip(rows, spans, strict=True)):
        assert row.chapter_id == span.chapter_id == 1
        assert row.chapter_id == span.chapter_id == 1
        assert row.paragraph_index == span.paragraph_index == i
        assert row.source_paragraph_index == span.source_paragraph_index
        assert row.fragment_index == span.fragment_index
        assert row.local_start_char == span.local_start_char
        assert row.local_end_char == span.local_end_char
        assert row.global_start_char == span.global_start_char
        assert row.global_end_char == span.global_end_char
        assert row.char_count == span.char_count == len(span.text)
        assert row.token_count == span.token_count
        assert row.text == span.text
        assert row.content_hash == hashlib.sha256(span.text.encode("utf-8")).hexdigest()


def test_insert_paragraphs_with_nonzero_chunk_offset(db_session) -> None:
    """chunks.char_offset 非零时，global = char_offset + local 的偏移一致性校验通过"""
    run_id = _create_run(db_session)
    chunks = _single_chunk("甲段。\n乙段。\n", start=100)
    _insert_chapter_texts(db_session, run_id, chunks)
    spans = _make_spans(chunks)

    repo = ParagraphRepository(db_session)
    assert repo.insert_paragraphs(run_id, spans) == 2
    rows = repo.fetch_paragraph_rows(run_id)
    assert rows[0].global_start_char == 100 + rows[0].local_start_char
    assert rows[1].global_start_char == 100 + rows[1].local_start_char


def test_insert_paragraphs_is_idempotent(db_session) -> None:
    """同 run 重复插入先删后插，行数不翻倍"""
    run_id = _create_run(db_session)
    chunks = _single_chunk(CHUNK_TEXT)
    _insert_chapter_texts(db_session, run_id, chunks)
    spans = _make_spans(chunks)

    repo = ParagraphRepository(db_session)
    assert repo.insert_paragraphs(run_id, spans) == 3
    assert repo.insert_paragraphs(run_id, spans) == 3
    assert repo.count_paragraphs(run_id) == 3
    # 第二次只写前两段时，旧第三段被删除
    assert repo.insert_paragraphs(run_id, spans[:2]) == 2
    assert repo.count_paragraphs(run_id) == 2
    assert [row.paragraph_id for row in repo.fetch_paragraph_rows(run_id)] == [0, 1]


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("paragraph_id", None),
        ("chapter_id", None),
        ("global_start_char", None),
        ("global_end_char", None),
        ("token_count", None),
    ],
)
def test_insert_paragraphs_rejects_none_identity_fields(db_session, field: str, value) -> None:
    run_id = _create_run(db_session)
    span = replace(
        _span(paragraph_id=0, local_start=0, local_end=5, global_start=0, global_end=5),
        **{field: value},
    )
    with pytest.raises(ValueError, match="不得为 None"):
        ParagraphRepository(db_session).insert_paragraphs(run_id, [span])


def test_insert_paragraphs_rejects_negative_token_count(db_session) -> None:
    run_id = _create_run(db_session)
    span = replace(
        _span(paragraph_id=0, local_start=0, local_end=5, global_start=0, global_end=5),
        token_count=-1,
    )
    with pytest.raises(ValueError, match="不得为负数"):
        ParagraphRepository(db_session).insert_paragraphs(run_id, [span])


def test_insert_paragraphs_rejects_overlapping_local_coords(db_session) -> None:
    """同一 chunk 内 local 坐标重叠（倒序）必须被拒绝"""
    run_id = _create_run(db_session)
    spans = [
        _span(paragraph_id=0, local_start=0, local_end=5, global_start=0, global_end=5),
        _span(paragraph_id=1, local_start=3, local_end=8, global_start=5, global_end=10),
    ]
    with pytest.raises(ValueError, match="local 坐标"):
        ParagraphRepository(db_session).insert_paragraphs(run_id, spans)


def test_insert_paragraphs_rejects_reversed_local_coords(db_session) -> None:
    """同一 chunk 内段落顺序颠倒（后一段落起点落在前一段落之前）必须被拒绝"""
    run_id = _create_run(db_session)
    spans = [
        _span(paragraph_id=0, paragraph_index=1, local_start=5, local_end=10, global_start=0, global_end=5),
        _span(paragraph_id=1, paragraph_index=0, local_start=0, local_end=5, global_start=5, global_end=10),
    ]
    with pytest.raises(ValueError, match="local 坐标"):
        ParagraphRepository(db_session).insert_paragraphs(run_id, spans)


def test_insert_paragraphs_rejects_overlapping_global_coords(db_session) -> None:
    run_id = _create_run(db_session)
    spans = [
        _span(paragraph_id=0, local_start=0, local_end=5, global_start=0, global_end=5),
        _span(paragraph_id=1, local_start=5, local_end=10, global_start=3, global_end=8),
    ]
    with pytest.raises(ValueError, match="global 坐标"):
        ParagraphRepository(db_session).insert_paragraphs(run_id, spans)


def test_insert_paragraphs_rejects_reversed_global_order(db_session) -> None:
    """span 列表（全文顺序）中 global 坐标回退必须被拒绝"""
    run_id = _create_run(db_session)
    spans = [
        _span(paragraph_id=0, local_start=0, local_end=5, global_start=5, global_end=10),
        _span(paragraph_id=1, local_start=5, local_end=10, global_start=0, global_end=5),
    ]
    with pytest.raises(ValueError, match="global 坐标"):
        ParagraphRepository(db_session).insert_paragraphs(run_id, spans)


def test_insert_paragraphs_rejects_inconsistent_global_offset(db_session) -> None:
    """global_start_char - char_offset != local_start_char 必须被拒绝"""
    run_id = _create_run(db_session)
    chunks = _single_chunk("甲段。\n乙段。\n", start=100)
    _insert_chapter_texts(db_session, run_id, chunks)
    spans = _make_spans(chunks)
    spans = [replace(spans[0], global_start_char=50, global_end_char=54)] + spans[1:]

    with pytest.raises(ValueError, match="偏移不一致"):
        ParagraphRepository(db_session).insert_paragraphs(run_id, spans)


def test_get_incomplete_paragraph_chapter_ids(db_session) -> None:
    """缺段落的章节被列出（空文本章节除外），补全后为空"""
    run_id = _create_run(db_session)
    text_a = "甲段。\n乙段。\n"
    text_b = "丙段。\n"
    chunks = [
        Chunk(index=0, text=text_a, start=0, end=len(text_a), chapter_id=1),
        Chunk(index=1, text=text_b, start=len(text_a), end=len(text_a) + len(text_b), chapter_id=2),
        Chunk(index=2, text="", start=len(text_a) + len(text_b), end=len(text_a) + len(text_b), chapter_id=3),
    ]
    _insert_chapter_texts(db_session, run_id, chunks)
    all_spans = _make_spans(chunks[:2])

    repo = ParagraphRepository(db_session)
    # 只插入章1 的段落 → 章2 缺失，章3 空文本被排除
    chapter1_spans = [s for s in all_spans if s.chapter_id == 1]
    repo.insert_paragraphs(run_id, chapter1_spans)
    assert repo.get_incomplete_paragraph_chapter_ids(run_id) == [2]

    # 补全后为空
    repo.insert_paragraphs(run_id, all_spans)
    assert repo.get_incomplete_paragraph_chapter_ids(run_id) == []


def test_get_incomplete_paragraph_chapter_ids_detects_gaps(db_session) -> None:
    """章内段落序号不连续（min != 0 或 count != max + 1）被列出"""
    run_id = _create_run(db_session)
    chunks = _single_chunk("一段。\n二段。\n")
    _insert_chapter_texts(db_session, run_id, chunks)
    # 手工构造缺 paragraph_index=1 的段落
    spans = [
        _span(paragraph_id=0, paragraph_index=0, local_start=0, local_end=3, global_start=0, global_end=3),
        _span(paragraph_id=1, paragraph_index=2, local_start=4, local_end=7, global_start=4, global_end=7),
    ]
    ParagraphRepository(db_session).insert_paragraphs(run_id, spans)
    assert ParagraphRepository(db_session).get_incomplete_paragraph_chapter_ids(run_id) == [1]


def test_db_constraint_rejects_invalid_local_order(db_session) -> None:
    """绕过 repository 校验直接插入违反 local_start_char < local_end_char 的行时触发 IntegrityError"""
    run_id = _create_run(db_session)
    chunks = _single_chunk("一段。")
    _insert_chapter_texts(db_session, run_id, chunks)
    db_session.add(
        Paragraph(
            run_id=run_id,
            paragraph_id=0,
            chapter_id=1,
            paragraph_index=0,
            source_paragraph_index=0,
            fragment_index=0,
            local_start_char=5,
            local_end_char=5,
            global_start_char=0,
            global_end_char=5,
            char_count=5,
            token_count=1,
            text="abcde",
            content_hash=hashlib.sha256(b"abcde").hexdigest(),
        )
    )
    with pytest.raises(IntegrityError):
        db_session.flush()
