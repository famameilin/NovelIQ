"""ChapterRepository 存储测试"""

from __future__ import annotations

from sqlalchemy import select

from src.storage import new_id
from src.storage.models import Chapter
from src.storage.repositories import ChapterRepository, RunRepository
from src.text_processing.chapters.models import ChapterData, ChapterLevel
from src.text_processing.models import Chunk
from tests.support.analysis_factories import insert_test_novel as _insert_test_novel
from tests.support.storage_fixtures import fixture_id


def _make_chapters() -> list[ChapterData]:
    return [
        ChapterData(
            chapter_id=1,
            sequence=1,
            level=ChapterLevel.CHAPTER,
            title="第一章 起点",
            display_title="起点",
            display_index_label="第1章",
            number=1,
            title_start_char=0,
            start_char=7,
            end_char=13,
        ),
        ChapterData(
            chapter_id=2,
            sequence=2,
            level=ChapterLevel.EXTRA,
            title="番外 前传",
            display_title="前传",
            display_index_label=None,
            number=None,
            title_start_char=13,
            start_char=20,
            end_char=26,
        ),
    ]


def _create_run(db_session) -> str:
    novel_id = new_id()
    _insert_test_novel(novel_id, session=db_session)
    return RunRepository(db_session).create_run(
        novel_id=novel_id,
        source_path="test",
        title="Chapter Repository Test",
    )


def test_insert_and_fetch_chapters(db_session) -> None:
    run_id = _create_run(db_session)
    repo = ChapterRepository(db_session)
    repo.insert_chapters(run_id, _make_chapters())

    rows = repo.fetch_chapters(run_id)
    assert len(rows) == 2
    first = rows[0]
    assert first.chapter_id == 1
    assert first.title == "第一章 起点"
    assert first.display_title == "起点"
    assert first.display_index_label == "第1章"
    assert first.level == "chapter"
    assert first.start_pos == 7
    assert first.end_pos == 13


def test_insert_chapters_replaces_old_data(db_session) -> None:
    run_id = _create_run(db_session)
    repo = ChapterRepository(db_session)
    repo.insert_chapters(run_id, _make_chapters())
    repo.insert_chapters(run_id, _make_chapters()[:1])

    rows = repo.fetch_chapters(run_id)
    assert len(rows) == 1
    assert rows[0].chapter_id == 1


def test_count_chapters(db_session) -> None:
    run_id = _create_run(db_session)
    repo = ChapterRepository(db_session)
    repo.insert_chapters(run_id, _make_chapters())
    # -2：count_chapters 只统计有正文的章节（结构行不算）
    repo.insert_chapter_texts(
        run_id,
        [
            Chunk(index=0, text="第一章正文。", start=0, end=6, chapter_id=1),
            Chunk(index=1, text="第二章正文。", start=6, end=12, chapter_id=2),
        ],
    )
    assert repo.count_chapters(run_id) == 2
    assert repo.count_chapters(fixture_id(__name__, "no-such-run")) == 0


def test_fetch_chapters_ordered_by_sequence(db_session) -> None:
    run_id = _create_run(db_session)
    repo = ChapterRepository(db_session)
    chapters = _make_chapters()
    chapters.reverse()
    repo.insert_chapters(run_id, chapters)

    rows = repo.fetch_chapters(run_id)
    assert [row.sequence for row in rows] == [1, 2]
    assert [row.chapter_id for row in rows] == [1, 2]


def test_insert_chapter_texts_writes_text_columns_on_chapters(db_session) -> None:
    """正文切片与全文起点与章节目录同键合并进 chapters（text/char_offset）"""
    run_id = _create_run(db_session)
    repo = ChapterRepository(db_session)
    repo.insert_chapters(run_id, _make_chapters())
    repo.insert_chapter_texts(
        run_id,
        [
            Chunk(index=0, text="第一章正文。", start=0, end=6, chapter_id=1),
            Chunk(index=1, text="番外正文。", start=6, end=11, chapter_id=2),
        ],
    )

    bodies = db_session.scalars(select(Chapter).where(Chapter.run_id == run_id).order_by(Chapter.chapter_id)).all()
    assert [(row.chapter_id, row.char_offset, row.text) for row in bodies] == [
        (1, 0, "第一章正文。"),
        (2, 6, "番外正文。"),
    ]

    assert repo.fetch_chapter_texts(run_id) == [(1, "第一章正文。"), (2, "番外正文。")]
    assert repo.fetch_all_chapter_texts(run_id) == ["第一章正文。", "番外正文。"]
    assert repo.fetch_chapter_counts(run_id) == (2, 11)

    # 正文终点 = char_offset + 字符长度（读取投影，原 chapters.char_end_offset）
    assert [
        (row.chapter_id, row.sequence, row.char_offset, row.char_end_offset, row.text)
        for row in repo.fetch_chapter_bodies(run_id)
    ] == [
        (1, 1, 0, 6, "第一章正文。"),
        (2, 2, 6, 11, "番外正文。"),
    ]


def test_chapter_without_text_has_no_body(db_session) -> None:
    """空正文章节只有结构行：count_chapters/has_chapters 只统计有正文的章节"""
    run_id = _create_run(db_session)
    repo = ChapterRepository(db_session)
    repo.insert_chapters(run_id, _make_chapters())
    repo.insert_chapter_texts(
        run_id,
        [Chunk(index=0, text="第一章正文。", start=0, end=6, chapter_id=1)],
    )

    assert len(repo.fetch_chapters(run_id)) == 2
    assert repo.fetch_chapter_texts(run_id) == [(1, "第一章正文。")]
    assert repo.count_chapters(run_id) == 1
    assert repo.has_chapters(run_id)


def test_insert_chapter_texts_updates_existing_body(db_session) -> None:
    """同章重复回填正文按最新切片覆盖，不产生重复正文行"""
    run_id = _create_run(db_session)
    repo = ChapterRepository(db_session)
    repo.insert_chapters(run_id, _make_chapters())
    repo.insert_chapter_texts(
        run_id,
        [Chunk(index=0, text="旧正文。", start=0, end=4, chapter_id=1)],
    )
    repo.insert_chapter_texts(
        run_id,
        [Chunk(index=0, text="新正文。", start=7, end=11, chapter_id=1)],
    )

    bodies = db_session.scalars(select(Chapter).where(Chapter.run_id == run_id, Chapter.text.is_not(None))).all()
    assert [(row.chapter_id, row.char_offset, row.text) for row in bodies] == [(1, 7, "新正文。")]
    assert repo.fetch_chapter_texts(run_id) == [(1, "新正文。")]
