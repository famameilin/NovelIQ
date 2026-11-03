"""annotations 的普通记录只读入口"""

from __future__ import annotations

from collections.abc import Iterable

from src.storage.input_boundary import plain_inputs
from src.storage.records.models import (
    AgentRecord,
    ChapterAnnotationRecord,
    DialogueRecordRecord,
)
from src.storage.records.values import NamedRecord
from src.storage.repositories.queries import annotations as _queries


@plain_inputs
class AnnotationsReads:
    "只返回脱离数据库资源的普通记录"

    def __init__(self, runner):
        self._runner = runner

    def list_saved_chapter_ids(self, run_id: str) -> list[NamedRecord]:
        "读取固定记录投影并在包内释放结果资源"
        return self._runner.run(lambda session: _queries.list_saved_chapter_ids(session, run_id), read_only=True)

    def find_consolidated_chapter(self, chapter_id: int, run_id: str) -> ChapterAnnotationRecord | None:
        "读取固定记录投影并在包内释放结果资源"
        return self._runner.run(
            lambda session: _queries.find_consolidated_chapter(session, chapter_id, run_id), read_only=True
        )

    def list_run_outputs(self, run_id: str) -> list[ChapterAnnotationRecord]:
        "读取固定记录投影并在包内释放结果资源"
        return self._runner.run(lambda session: _queries.list_run_outputs(session, run_id), read_only=True)

    def list_chapter_role_outputs(self, chapter_id: int, run_id: str) -> list[ChapterAnnotationRecord]:
        "读取固定记录投影并在包内释放结果资源"
        return self._runner.run(
            lambda session: _queries.list_chapter_role_outputs(session, chapter_id, run_id), read_only=True
        )

    def list_dialogues_for_executions(self, valid_executions: Iterable[str]) -> list[DialogueRecordRecord]:
        "读取固定记录投影并在包内释放结果资源"
        return self._runner.run(
            lambda session: _queries.list_dialogues_for_executions(session, valid_executions), read_only=True
        )

    def list_outputs_with_chapters(self, run_id: str) -> list[NamedRecord]:
        "读取固定记录投影并在包内释放结果资源"
        return self._runner.run(lambda session: _queries.list_outputs_with_chapters(session, run_id), read_only=True)

    def list_ordered_run_outputs(self, run_id: str) -> list[ChapterAnnotationRecord]:
        "读取固定记录投影并在包内释放结果资源"
        return self._runner.run(lambda session: _queries.list_ordered_run_outputs(session, run_id), read_only=True)

    def get_output(self, annotation_id: str) -> ChapterAnnotationRecord | None:
        "读取固定记录投影并在包内释放结果资源"
        return self._runner.run(lambda session: _queries.get_output(session, annotation_id), read_only=True)

    def get_saved_output(self, annotation_id: str) -> ChapterAnnotationRecord | None:
        "读取固定记录投影并在包内释放结果资源"
        return self._runner.run(lambda session: _queries.get_saved_output(session, annotation_id), read_only=True)

    def get_execution(self, agent_id: str) -> AgentRecord | None:
        "读取固定记录投影并在包内释放结果资源"
        return self._runner.run(lambda session: _queries.get_execution(session, agent_id), read_only=True)

    def list_output_paragraph_labels(self, record_ids: Iterable[str]) -> list[NamedRecord]:
        "读取固定记录投影并在包内释放结果资源"
        return self._runner.run(
            lambda session: _queries.list_output_paragraph_labels(session, record_ids), read_only=True
        )

    def list_ordered_dialogues(self, execution_ids: Iterable[str]) -> list[DialogueRecordRecord]:
        "读取固定记录投影并在包内释放结果资源"
        return self._runner.run(lambda session: _queries.list_ordered_dialogues(session, execution_ids), read_only=True)
