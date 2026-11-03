"""text 的普通记录只读入口"""

from __future__ import annotations

from collections.abc import Iterable, Mapping

from src.storage.input_boundary import plain_inputs
from src.storage.records.models import (
    ChapterRecord,
    ParagraphRecord,
)
from src.storage.records.values import NamedRecord
from src.storage.repositories.queries import text as _queries


@plain_inputs
class TextReads:
    "只返回脱离数据库资源的普通记录"

    def __init__(self, runner):
        self._runner = runner

    def list_chapter_paragraphs(self, chapter_id: int, run_id: str) -> list[ParagraphRecord]:
        "读取固定记录投影并在包内释放结果资源"
        return self._runner.run(
            lambda session: _queries.list_chapter_paragraphs(session, chapter_id, run_id), read_only=True
        )

    def list_run_chapters(self, run_id: str) -> list[ChapterRecord]:
        "读取固定记录投影并在包内释放结果资源"
        return self._runner.run(lambda session: _queries.list_run_chapters(session, run_id), read_only=True)

    def get_chapter_sequence(self, current_chapter_id: int, run_id: str) -> int | None:
        "读取固定记录投影并在包内释放结果资源"
        return self._runner.run(
            lambda session: _queries.get_chapter_sequence(session, current_chapter_id, run_id), read_only=True
        )

    def list_ordered_chapter_ids(self, run_id: str) -> list[int]:
        "读取固定记录投影并在包内释放结果资源"
        return self._runner.run(lambda session: _queries.list_ordered_chapter_ids(session, run_id), read_only=True)

    def get_paragraph_with_chapter_sequence(self, paragraph_id: int, run_id: str) -> list[NamedRecord]:
        "读取固定记录投影并在包内释放结果资源"
        return self._runner.run(
            lambda session: _queries.get_paragraph_with_chapter_sequence(session, paragraph_id, run_id), read_only=True
        )

    def get_chapter(self, chapter_id: int, run_id: str) -> ChapterRecord | None:
        "读取固定记录投影并在包内释放结果资源"
        return self._runner.run(lambda session: _queries.get_chapter(session, chapter_id, run_id), read_only=True)

    def list_ordered_paragraphs(self, chapter_id: int, run_id: str) -> list[ParagraphRecord]:
        "读取固定记录投影并在包内释放结果资源"
        return self._runner.run(
            lambda session: _queries.list_ordered_paragraphs(session, chapter_id, run_id), read_only=True
        )

    def list_passages(self, paragraph_ids: Iterable[int], run_id: str) -> list[ParagraphRecord]:
        "读取固定记录投影并在包内释放结果资源"
        return self._runner.run(lambda session: _queries.list_passages(session, paragraph_ids, run_id), read_only=True)

    def list_run_paragraphs(self, run_id: str) -> list[ParagraphRecord]:
        "读取固定记录投影并在包内释放结果资源"
        return self._runner.run(lambda session: _queries.list_run_paragraphs(session, run_id), read_only=True)

    def list_readable_chapters(self, run_id: str) -> list[ChapterRecord]:
        "读取固定记录投影并在包内释放结果资源"
        return self._runner.run(lambda session: _queries.list_readable_chapters(session, run_id), read_only=True)

    def get_execution_chapter(self, execution_chapter_id: int, run_id: str) -> ChapterRecord | None:
        "读取固定记录投影并在包内释放结果资源"
        return self._runner.run(
            lambda session: _queries.get_execution_chapter(session, execution_chapter_id, run_id), read_only=True
        )

    def get_source_chapter(self, chapter_id: int, run_id: str) -> ChapterRecord | None:
        "读取固定记录投影并在包内释放结果资源"
        return self._runner.run(
            lambda session: _queries.get_source_chapter(session, chapter_id, run_id), read_only=True
        )

    def list_source_paragraphs(self, chapter_id: int, run_id: str) -> list[ParagraphRecord]:
        "读取固定记录投影并在包内释放结果资源"
        return self._runner.run(
            lambda session: _queries.list_source_paragraphs(session, chapter_id, run_id), read_only=True
        )

    def list_search_hit_positions(
        self,
        after_chapter_sequence: int | None,
        before_chapter_sequence: int | None,
        merged: Mapping[int, object],
        run_id: str,
    ) -> list[NamedRecord]:
        "读取固定记录投影并在包内释放结果资源"
        return self._runner.run(
            lambda session: _queries.list_search_hit_positions(
                session, after_chapter_sequence, before_chapter_sequence, merged, run_id
            ),
            read_only=True,
        )

    def count_chapters(self, run_id: str) -> int | None:
        "读取固定记录投影并在包内释放结果资源"
        return self._runner.run(lambda session: _queries.count_chapters(session, run_id), read_only=True)

    def get_book_end_offset(self, run_id: str) -> int | None:
        "读取固定记录投影并在包内释放结果资源"
        return self._runner.run(lambda session: _queries.get_book_end_offset(session, run_id), read_only=True)

    def list_chapter_offsets(self, run_id: str) -> list[NamedRecord]:
        "读取固定记录投影并在包内释放结果资源"
        return self._runner.run(lambda session: _queries.list_chapter_offsets(session, run_id), read_only=True)

    def get_last_chapter_offset(self, run_id: str) -> int | None:
        "读取固定记录投影并在包内释放结果资源"
        return self._runner.run(lambda session: _queries.get_last_chapter_offset(session, run_id), read_only=True)

    def list_readable_run_chapters(self, run_id: str) -> list[ChapterRecord]:
        "读取固定记录投影并在包内释放结果资源"
        return self._runner.run(lambda session: _queries.list_readable_run_chapters(session, run_id), read_only=True)

    def list_owned_evidence(self, owner_column: str, owner_ids: Iterable[str], run_id: str) -> list[NamedRecord]:
        "读取固定记录投影并在包内释放结果资源"
        return self._runner.run(
            lambda session: _queries.list_owned_evidence(session, owner_column, owner_ids, run_id), read_only=True
        )

    def list_owned_evidence_anchors(
        self, owner_column: str, owner_ids: Iterable[str], run_id: str
    ) -> list[NamedRecord]:
        "读取固定记录投影并在包内释放结果资源"
        return self._runner.run(
            lambda session: _queries.list_owned_evidence_anchors(session, owner_column, owner_ids, run_id),
            read_only=True,
        )

    def get_run_paragraph(self, run_id: str, paragraph_id: int) -> ParagraphRecord | None:
        "读取固定记录投影并在包内释放结果资源"
        return self._runner.run(
            lambda session: _queries.get_run_paragraph(session, run_id, paragraph_id), read_only=True
        )

    def list_ordered_run_chapters(self, run_id: str) -> list[ChapterRecord]:
        "读取固定记录投影并在包内释放结果资源"
        return self._runner.run(lambda session: _queries.list_ordered_run_chapters(session, run_id), read_only=True)

    def list_work_paragraphs(self, chapter: ChapterRecord, run_id: str) -> list[ParagraphRecord]:
        "读取固定记录投影并在包内释放结果资源"
        return self._runner.run(lambda session: _queries.list_work_paragraphs(session, chapter, run_id), read_only=True)
