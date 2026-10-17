"""ParagraphRepository 存储测试（paragraphs 段落事实源表）"""

from __future__ import annotations

import uuid
from dataclasses import replace

import pytest
from sqlalchemy import event
from sqlalchemy.exc import IntegrityError

from src.storage.models import Paragraph
from src.storage.repositories import ChapterRepository, RunRepository
from src.storage.repositories.paragraph_repository import ParagraphMetricRow, ParagraphRepository
from src.text_processing.models import Chunk, ParagraphSpan
from src.text_processing.paragraphs import split_chunk_paragraphs
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


def _metric_row(paragraph_id: int, *, token_count: int) -> ParagraphMetricRow:
    """最小合法指标行：token_count 是段落读取投影的口径来源"""
    return ParagraphMetricRow(
        paragraph_id=paragraph_id,
        token_count=token_count,
        sentence_count=0,
        sentence_char_sum=0.0,
        sentence_char_sum_sq=0.0,
        positive_weight_sum=0.0,
        negative_weight_sum=0.0,
        fight_weight_sum=0.0,
        exclaim_count=0,
        question_count=0,
        pause_count=0,
        dialogue_char_count=0,
        sensory_hit_count=0,
        imagery_hit_count=0,
        metaphor_sentence_count=0,
        body_reaction_hit_count=0,
    )


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


def _paragraph_model(
    run_id: str,
    *,
    paragraph_id: int,
    local_start_char: int,
    text: str,
    chapter_id: int = 1,
) -> Paragraph:
    """直接构造段落 ORM 行（绕过 repository 校验，用于数据库约束反例）"""
    return Paragraph(
        run_id=run_id,
        paragraph_id=paragraph_id,
        chapter_id=chapter_id,
        paragraph_index=paragraph_id,
        source_paragraph_index=0,
        fragment_index=0,
        local_start_char=local_start_char,
        text=text,
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
        assert row.paragraph_index == span.paragraph_index == i
        assert row.source_paragraph_index == span.source_paragraph_index
        assert row.fragment_index == span.fragment_index
        assert row.local_start_char == span.local_start_char
        # 2026-10-16 3NF：local_end_char/global/char_count 是读取投影
        assert row.local_end_char == span.local_end_char
        assert row.global_start_char == span.global_start_char
        assert row.global_end_char == span.global_end_char
        assert row.char_count == span.char_count == len(span.text)
        assert row.text == span.text
        # token_count 读取投影来自 paragraph_metrics（本用例未写指标行）
        assert row.token_count is None


def test_paragraph_token_count_projection_comes_from_metrics(db_session) -> None:
    """2026-10-16 3NF：token_count 从 paragraph_metrics 读取投影（预处理与指标同批 token）"""
    run_id = _create_run(db_session)
    chunks = _single_chunk(CHUNK_TEXT, start=0)
    _insert_chapter_texts(db_session, run_id, chunks)
    spans = _make_spans(chunks, token_counts=[3, 5, 7])

    repo = ParagraphRepository(db_session)
    repo.insert_paragraphs(run_id, spans)
    assert [row.token_count for row in repo.fetch_paragraph_rows(run_id)] == [None, None, None]

    repo.insert_paragraph_metrics(
        run_id,
        [_metric_row(span.paragraph_id, token_count=span.token_count) for span in spans],
    )
    assert [row.token_count for row in repo.fetch_paragraph_rows(run_id)] == [3, 5, 7]


def test_chapter_paragraph_batch_filters_in_database(db_session) -> None:
    """章节段落查询必须在 SQL 层按章过滤，不能回退到全书扫描"""
    run_id = _create_run(db_session)
    first = "甲段。\n乙段。\n"
    second = "丙段。\n"
    chunks = [
        Chunk(index=0, text=first, start=0, end=len(first), chapter_id=1),
        Chunk(index=1, text=second, start=len(first), end=len(first) + len(second), chapter_id=2),
    ]
    _insert_chapter_texts(db_session, run_id, chunks)
    ParagraphRepository(db_session).insert_paragraphs(run_id, _make_spans(chunks))

    statements: list[str] = []

    def capture_sql(_conn, _cursor, statement, _parameters, _context, _executemany) -> None:
        statements.append(statement)

    bind = db_session.get_bind()
    event.listen(bind, "before_cursor_execute", capture_sql)
    try:
        rows = ParagraphRepository(db_session).fetch_paragraph_rows_batch(run_id, chapter_id=2, limit=None)
    finally:
        event.remove(bind, "before_cursor_execute", capture_sql)

    assert len(rows) == 1
    assert rows[0].chapter_id == 2
    assert any("paragraphs.chapter_id =" in sql for sql in statements if "FROM paragraphs" in sql)


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
    with pytest.raises(ValueError):
        ParagraphRepository(db_session).insert_paragraphs(run_id, [span])


def test_insert_paragraphs_rejects_negative_token_count(db_session) -> None:
    run_id = _create_run(db_session)
    span = replace(
        _span(paragraph_id=0, local_start=0, local_end=5, global_start=0, global_end=5),
        token_count=-1,
    )
    with pytest.raises(ValueError):
        ParagraphRepository(db_session).insert_paragraphs(run_id, [span])


def test_insert_paragraphs_rejects_overlapping_local_coords(db_session) -> None:
    """同一 chunk 内 local 坐标重叠（倒序）必须被拒绝"""
    run_id = _create_run(db_session)
    spans = [
        _span(paragraph_id=0, local_start=0, local_end=5, global_start=0, global_end=5),
        _span(paragraph_id=1, local_start=3, local_end=8, global_start=5, global_end=10),
    ]
    with pytest.raises(ValueError):
        ParagraphRepository(db_session).insert_paragraphs(run_id, spans)


def test_insert_paragraphs_rejects_reversed_local_coords(db_session) -> None:
    """同一 chunk 内段落顺序颠倒（后一段落起点落在前一段落之前）必须被拒绝"""
    run_id = _create_run(db_session)
    spans = [
        _span(paragraph_id=0, paragraph_index=1, local_start=5, local_end=10, global_start=0, global_end=5),
        _span(paragraph_id=1, paragraph_index=0, local_start=0, local_end=5, global_start=5, global_end=10),
    ]
    with pytest.raises(ValueError):
        ParagraphRepository(db_session).insert_paragraphs(run_id, spans)


def test_insert_paragraphs_rejects_overlapping_global_coords(db_session) -> None:
    run_id = _create_run(db_session)
    spans = [
        _span(paragraph_id=0, local_start=0, local_end=5, global_start=0, global_end=5),
        _span(paragraph_id=1, local_start=5, local_end=10, global_start=3, global_end=8),
    ]
    with pytest.raises(ValueError):
        ParagraphRepository(db_session).insert_paragraphs(run_id, spans)


def test_insert_paragraphs_rejects_reversed_global_order(db_session) -> None:
    """span 列表（全文顺序）中 global 坐标回退必须被拒绝"""
    run_id = _create_run(db_session)
    spans = [
        _span(paragraph_id=0, local_start=0, local_end=5, global_start=5, global_end=10),
        _span(paragraph_id=1, local_start=5, local_end=10, global_start=0, global_end=5),
    ]
    with pytest.raises(ValueError):
        ParagraphRepository(db_session).insert_paragraphs(run_id, spans)


def test_insert_paragraphs_rejects_inconsistent_global_offset(db_session) -> None:
    """global_start_char - char_offset != local_start_char 必须被拒绝"""
    run_id = _create_run(db_session)
    chunks = _single_chunk("甲段。\n乙段。\n", start=100)
    _insert_chapter_texts(db_session, run_id, chunks)
    spans = _make_spans(chunks)
    spans = [replace(spans[0], global_start_char=50, global_end_char=54)] + spans[1:]

    with pytest.raises(ValueError):
        ParagraphRepository(db_session).insert_paragraphs(run_id, spans)


def test_db_constraint_rejects_duplicate_local_start_in_chapter(db_session) -> None:
    """绕过 repository 校验直接插入同章重复 local_start_char 时触发 IntegrityError

    2026-10-16 3NF：local_end_char 不再落列，DDL 层不再有 local_start < local_end 检查，
    同章定位唯一性（uq_paragraphs_run_chapter_local_start）仍是数据库约束。
    """
    run_id = _create_run(db_session)
    chunks = _single_chunk("一段。")
    _insert_chapter_texts(db_session, run_id, chunks)
    db_session.add(_paragraph_model(run_id, paragraph_id=0, local_start_char=0, text="abcde"))
    db_session.add(_paragraph_model(run_id, paragraph_id=1, local_start_char=0, text="fghij"))
    with pytest.raises(IntegrityError):
        db_session.flush()


def test_db_constraint_rejects_paragraph_of_missing_chapter(db_session) -> None:
    """段落所属章节不存在时由外键拒绝（段落身份必须挂在真实章节上）"""
    run_id = _create_run(db_session)
    db_session.add(_paragraph_model(run_id, paragraph_id=0, local_start_char=0, text="abcde", chapter_id=99))
    with pytest.raises(IntegrityError):
        db_session.flush()


def test_fetch_paragraph_rows_batch_cursor_paging(db_session) -> None:
    """keyset 游标分页：limit 截断批次、after_id 排除上一批最后一条"""
    run_id = _create_run(db_session)
    chunks = _single_chunk(CHUNK_TEXT)
    _insert_chapter_texts(db_session, run_id, chunks)
    spans = _make_spans(chunks)
    ParagraphRepository(db_session).insert_paragraphs(run_id, spans)

    repo = ParagraphRepository(db_session)
    first_batch = repo.fetch_paragraph_rows_batch(run_id, limit=2)
    assert [row.paragraph_id for row in first_batch] == [0, 1]
    second_batch = repo.fetch_paragraph_rows_batch(run_id, after_id=1, limit=2)
    assert [row.paragraph_id for row in second_batch] == [2]


def test_insert_paragraphs_rejects_local_span_text_length_mismatch(db_session) -> None:
    """local 坐标跨度与原文长度不一致时必须拒绝（投影坐标会与文本不符）"""
    run_id = _create_run(db_session)
    span = replace(
        _span(paragraph_id=0, local_start=0, local_end=5, global_start=0, global_end=5),
        text="abc",
    )
    with pytest.raises(ValueError):
        ParagraphRepository(db_session).insert_paragraphs(run_id, [span])
