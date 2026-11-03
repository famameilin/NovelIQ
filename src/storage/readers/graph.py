"""graph 的普通记录只读入口"""

from __future__ import annotations

from collections.abc import Iterable, Mapping

from src.storage.input_boundary import plain_inputs
from src.storage.records.models import (
    EventParticipantRecord,
    FactEntityTagRecord,
    GraphEntityRecord,
    GraphFactRecord,
    GraphRelationRecord,
    SourceEvidenceRecord,
)
from src.storage.records.values import NamedRecord
from src.storage.repositories.queries import graph as _queries


@plain_inputs
class GraphReads:
    "只返回脱离数据库资源的普通记录"

    def __init__(self, runner):
        self._runner = runner

    def list_facts_with_source_chapters(self, valid_executions: Iterable[str]) -> list[NamedRecord]:
        "读取固定记录投影并在包内释放结果资源"
        return self._runner.run(
            lambda session: _queries.list_facts_with_source_chapters(session, valid_executions), read_only=True
        )

    def list_fact_evidence(self, fact_chapter: Mapping[str, object]) -> list[SourceEvidenceRecord]:
        "读取固定记录投影并在包内释放结果资源"
        return self._runner.run(lambda session: _queries.list_fact_evidence(session, fact_chapter), read_only=True)

    def list_entities_by_ids(self, lookup_ids: Iterable[str]) -> list[GraphEntityRecord]:
        "读取固定记录投影并在包内释放结果资源"
        return self._runner.run(lambda session: _queries.list_entities_by_ids(session, lookup_ids), read_only=True)

    def list_run_characters(self, run_id: str) -> list[GraphEntityRecord]:
        "读取固定记录投影并在包内释放结果资源"
        return self._runner.run(lambda session: _queries.list_run_characters(session, run_id), read_only=True)

    def list_participant_entities(self, participant_rows: Iterable[EventParticipantRecord]) -> list[GraphEntityRecord]:
        "读取固定记录投影并在包内释放结果资源"
        return self._runner.run(
            lambda session: _queries.list_participant_entities(session, participant_rows), read_only=True
        )

    def get_fact(self, fact_id: int | str) -> GraphFactRecord | None:
        "读取固定记录投影并在包内释放结果资源"
        return self._runner.run(lambda session: _queries.get_fact(session, fact_id), read_only=True)

    def list_referenced_entities(self, rows: Iterable[EventParticipantRecord]) -> list[GraphEntityRecord]:
        "读取固定记录投影并在包内释放结果资源"
        return self._runner.run(lambda session: _queries.list_referenced_entities(session, rows), read_only=True)

    def list_saved_participant_entities(
        self, participant_rows: Iterable[EventParticipantRecord]
    ) -> list[GraphEntityRecord]:
        "读取固定记录投影并在包内释放结果资源"
        return self._runner.run(
            lambda session: _queries.list_saved_participant_entities(session, participant_rows), read_only=True
        )

    def list_participating_entity_ids(self, run_id: str) -> list[str]:
        "读取固定记录投影并在包内释放结果资源"
        return self._runner.run(lambda session: _queries.list_participating_entity_ids(session, run_id), read_only=True)

    def list_execution_fact_tags(self, rows: Iterable[GraphFactRecord]) -> list[FactEntityTagRecord]:
        "读取固定记录投影并在包内释放结果资源"
        return self._runner.run(lambda session: _queries.list_execution_fact_tags(session, rows), read_only=True)

    def list_fact_tags_for_executions(self, agent_ids: Iterable[str]) -> list[FactEntityTagRecord]:
        "按执行一次读取事实标签，不逐条传事实记录"
        return self._runner.run(
            lambda session: _queries.list_fact_tags_for_executions(session, agent_ids), read_only=True
        )

    def list_execution_fact_evidence(self, rows: Iterable[GraphFactRecord]) -> list[SourceEvidenceRecord]:
        "读取固定记录投影并在包内释放结果资源"
        return self._runner.run(lambda session: _queries.list_execution_fact_evidence(session, rows), read_only=True)

    def list_producer_facts(self, agent_id: str) -> list[GraphFactRecord]:
        "读取固定记录投影并在包内释放结果资源"
        return self._runner.run(lambda session: _queries.list_producer_facts(session, agent_id), read_only=True)

    def list_execution_facts(self, agent_ids: Iterable[str]) -> list[GraphFactRecord]:
        "一次读取多个执行的事实行，按操作序稳定排列"
        return self._runner.run(lambda session: _queries.list_execution_facts(session, agent_ids), read_only=True)

    def list_run_entities(self, run_id: str) -> list[GraphEntityRecord]:
        "读取固定记录投影并在包内释放结果资源"
        return self._runner.run(lambda session: _queries.list_run_entities(session, run_id), read_only=True)

    def list_relations(self) -> list[GraphRelationRecord]:
        "读取固定记录投影并在包内释放结果资源"
        return self._runner.run(lambda session: _queries.list_relations(session), read_only=True)

    def list_registry_fact_tags(self, facts: Iterable[GraphFactRecord]) -> list[FactEntityTagRecord]:
        "读取固定记录投影并在包内释放结果资源"
        return self._runner.run(lambda session: _queries.list_registry_fact_tags(session, facts), read_only=True)

    def get_fact_relation(self, fact: GraphFactRecord) -> GraphRelationRecord | None:
        "读取固定记录投影并在包内释放结果资源"
        return self._runner.run(lambda session: _queries.get_fact_relation(session, fact), read_only=True)

    def list_registry_entities(self, run_id: str) -> list[GraphEntityRecord]:
        "读取固定记录投影并在包内释放结果资源"
        return self._runner.run(lambda session: _queries.list_registry_entities(session, run_id), read_only=True)

    def list_run_facts(self, run_id: str) -> list[str]:
        "读取固定记录投影并在包内释放结果资源"
        return self._runner.run(lambda session: _queries.list_run_facts(session, run_id), read_only=True)

    def list_participant_changes(self, chapter_ids: Iterable[str], run_id: str) -> list[NamedRecord]:
        "读取固定记录投影并在包内释放结果资源"
        return self._runner.run(
            lambda session: _queries.list_participant_changes(session, chapter_ids, run_id), read_only=True
        )

    def list_direct_changes(self, run_id: str, chapter_ids: Iterable[str]) -> list[NamedRecord]:
        "读取固定记录投影并在包内释放结果资源"
        return self._runner.run(
            lambda session: _queries.list_direct_changes(session, run_id, chapter_ids), read_only=True
        )

    def list_ordered_fact_tags(self, fact_ids: Iterable[int | str]) -> list[NamedRecord]:
        "读取固定记录投影并在包内释放结果资源"
        return self._runner.run(lambda session: _queries.list_ordered_fact_tags(session, fact_ids), read_only=True)
