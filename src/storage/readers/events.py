"""events 的普通记录只读入口"""

from __future__ import annotations

from collections.abc import Iterable, Mapping

from src.storage.input_boundary import plain_inputs
from src.storage.records.models import (
    CompleteEventRecord,
    EventForeshadowingActionRecord,
    EventParticipantRecord,
    NarrativeGroupRecord,
    NarrativeLinkRecord,
    SourceEvidenceRecord,
)
from src.storage.records.values import NamedRecord
from src.storage.repositories.queries import events as _queries


@plain_inputs
class EventsReads:
    "只返回脱离数据库资源的普通记录"

    def __init__(self, runner):
        self._runner = runner

    def list_events_for_outputs(self, records_by_record: Mapping[str, object]) -> list[CompleteEventRecord]:
        "读取固定记录投影并在包内释放结果资源"
        return self._runner.run(
            lambda session: _queries.list_events_for_outputs(session, records_by_record), read_only=True
        )

    def list_event_evidence(self, source_event_ids: Iterable[str]) -> list[SourceEvidenceRecord]:
        "读取固定记录投影并在包内释放结果资源"
        return self._runner.run(lambda session: _queries.list_event_evidence(session, source_event_ids), read_only=True)

    def list_event_participants(self, source_event_ids: Iterable[str]) -> list[EventParticipantRecord]:
        "读取固定记录投影并在包内释放结果资源"
        return self._runner.run(
            lambda session: _queries.list_event_participants(session, source_event_ids), read_only=True
        )

    def list_related_foreshadowing_actions(
        self, annotation_events: Iterable[str]
    ) -> list[EventForeshadowingActionRecord]:
        "读取固定记录投影并在包内释放结果资源"
        return self._runner.run(
            lambda session: _queries.list_related_foreshadowing_actions(session, annotation_events), read_only=True
        )

    def list_ordered_foreshadowing_actions(
        self, annotation_events: Iterable[str]
    ) -> list[EventForeshadowingActionRecord]:
        "读取固定记录投影并在包内释放结果资源"
        return self._runner.run(
            lambda session: _queries.list_ordered_foreshadowing_actions(session, annotation_events), read_only=True
        )

    def list_queue_references(self, run_id: str) -> list[NarrativeLinkRecord]:
        "读取固定记录投影并在包内释放结果资源"
        return self._runner.run(lambda session: _queries.list_queue_references(session, run_id), read_only=True)

    def list_queue_links(self, run_id: str) -> list[NarrativeLinkRecord]:
        "读取正式队列成员与整队父子引用"
        return self._runner.run(lambda session: _queries.list_queue_links(session, run_id), read_only=True)

    def list_ordered_participants(self, source_event_ids: Iterable[str]) -> list[EventParticipantRecord]:
        "读取固定记录投影并在包内释放结果资源"
        return self._runner.run(
            lambda session: _queries.list_ordered_participants(session, source_event_ids), read_only=True
        )

    def list_foreshadowing_roots(self, annotation_events: Iterable[str]) -> list[CompleteEventRecord]:
        "读取固定记录投影并在包内释放结果资源"
        return self._runner.run(
            lambda session: _queries.list_foreshadowing_roots(session, annotation_events), read_only=True
        )

    def list_participants_by_ordinal(self, source_event_ids: Iterable[str]) -> list[EventParticipantRecord]:
        "读取固定记录投影并在包内释放结果资源"
        return self._runner.run(
            lambda session: _queries.list_participants_by_ordinal(session, source_event_ids), read_only=True
        )

    def list_execution_groups(self, producer_executions: Iterable[str]) -> list[NarrativeGroupRecord]:
        "读取固定记录投影并在包内释放结果资源"
        return self._runner.run(
            lambda session: _queries.list_execution_groups(session, producer_executions), read_only=True
        )

    def list_execution_trees(self, producer_executions: Iterable[str]) -> list[NarrativeGroupRecord]:
        "读取固定记录投影并在包内释放结果资源"
        return self._runner.run(
            lambda session: _queries.list_execution_trees(session, producer_executions), read_only=True
        )

    def list_execution_links(self, producer_executions: Iterable[str]) -> list[NarrativeLinkRecord]:
        "读取固定记录投影并在包内释放结果资源"
        return self._runner.run(
            lambda session: _queries.list_execution_links(session, producer_executions), read_only=True
        )

    def list_output_events(self, annotation_id: str) -> list[CompleteEventRecord]:
        "读取固定记录投影并在包内释放结果资源"
        return self._runner.run(lambda session: _queries.list_output_events(session, annotation_id), read_only=True)

    def list_saved_participants(self, source_event_ids: Iterable[str]) -> list[EventParticipantRecord]:
        "读取固定记录投影并在包内释放结果资源"
        return self._runner.run(
            lambda session: _queries.list_saved_participants(session, source_event_ids), read_only=True
        )

    def list_execution_actions(self, agent_id: str) -> list[EventForeshadowingActionRecord]:
        "读取固定记录投影并在包内释放结果资源"
        return self._runner.run(lambda session: _queries.list_execution_actions(session, agent_id), read_only=True)

    def list_producer_links(self, agent_id: str) -> list[NarrativeLinkRecord]:
        "读取固定记录投影并在包内释放结果资源"
        return self._runner.run(lambda session: _queries.list_producer_links(session, agent_id), read_only=True)

    def find_run_event_id(self, run_id: str) -> str | None:
        "读取固定记录投影并在包内释放结果资源"
        return self._runner.run(lambda session: _queries.find_run_event_id(session, run_id), read_only=True)

    def list_annotation_participants(self, annotation_events: Iterable[str]) -> list[EventParticipantRecord]:
        "读取固定记录投影并在包内释放结果资源"
        return self._runner.run(
            lambda session: _queries.list_annotation_participants(session, annotation_events), read_only=True
        )

    def list_ordered_output_events(self, record_ids: Iterable[str]) -> list[CompleteEventRecord]:
        "读取固定记录投影并在包内释放结果资源"
        return self._runner.run(
            lambda session: _queries.list_ordered_output_events(session, record_ids), read_only=True
        )

    def list_character_observations(self, record_by_annotation_event: Iterable[str]) -> list[EventParticipantRecord]:
        "读取固定记录投影并在包内释放结果资源"
        return self._runner.run(
            lambda session: _queries.list_character_observations(session, record_by_annotation_event), read_only=True
        )

    def list_output_event_ids(self, record_ids: Iterable[str]) -> list[NamedRecord]:
        "读取固定记录投影并在包内释放结果资源"
        return self._runner.run(lambda session: _queries.list_output_event_ids(session, record_ids), read_only=True)
