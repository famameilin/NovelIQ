"""ChapterRepository 存储测试"""

from __future__ import annotations

import uuid

from src.chapters.models import ChapterData, ChapterLevel
from src.storage.repositories import ChapterRepository, RunRepository
from tests.storage.test_db_operations import _insert_test_novel


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
            start_char=20,
            end_char=26,
        ),
    ]


def _create_run(db_session) -> str:
    novel_id = uuid.uuid4().hex[:8]
    _insert_test_novel(db_session, novel_id)
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
    assert repo.count_chapters(run_id) == 2
    assert repo.count_chapters("no-such-run") == 0


def test_fetch_chapters_ordered_by_sequence(db_session) -> None:
    run_id = _create_run(db_session)
    repo = ChapterRepository(db_session)
    chapters = _make_chapters()
    chapters.reverse()
    repo.insert_chapters(run_id, chapters)

    rows = repo.fetch_chapters(run_id)
    assert [row.sequence for row in rows] == [1, 2]
    assert [row.chapter_id for row in rows] == [1, 2]
