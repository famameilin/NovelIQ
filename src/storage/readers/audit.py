"""audit 的普通记录只读入口"""

from __future__ import annotations

from collections.abc import Iterable

from src.storage.input_boundary import plain_inputs
from src.storage.records.models import (
    AgentLoopRecord,
    ToolCallRecord,
)
from src.storage.records.values import NamedRecord
from src.storage.repositories.queries import audit as _queries


@plain_inputs
class AuditReads:
    "只返回脱离数据库资源的普通记录"

    def __init__(self, runner):
        self._runner = runner

    def find_turn_message(self, message_id: str) -> int | None:
        "读取固定记录投影并在包内释放结果资源"
        return self._runner.run(lambda session: _queries.find_turn_message(session, message_id), read_only=True)

    def find_tool_message(self, message_id: str) -> int | None:
        "读取固定记录投影并在包内释放结果资源"
        return self._runner.run(lambda session: _queries.find_tool_message(session, message_id), read_only=True)

    def list_accounting_sources(self, run_id: str) -> list[str]:
        "读取固定记录投影并在包内释放结果资源"
        return self._runner.run(lambda session: _queries.list_accounting_sources(session, run_id), read_only=True)

    def list_token_coverage_gaps(self, run_id: str) -> list[NamedRecord]:
        "读取固定记录投影并在包内释放结果资源"
        return self._runner.run(lambda session: _queries.list_token_coverage_gaps(session, run_id), read_only=True)

    def list_annotation_execution_ids(self, execution_ids: Iterable[str]) -> list[str]:
        "读取固定记录投影并在包内释放结果资源"
        return self._runner.run(
            lambda session: _queries.list_annotation_execution_ids(session, execution_ids), read_only=True
        )

    def list_run_turns(self, run_id: str) -> list[AgentLoopRecord]:
        "读取固定记录投影并在包内释放结果资源"
        return self._runner.run(lambda session: _queries.list_run_turns(session, run_id), read_only=True)

    def list_turn_tool_calls(self, call_ids: Iterable[str]) -> list[ToolCallRecord]:
        "读取固定记录投影并在包内释放结果资源"
        return self._runner.run(lambda session: _queries.list_turn_tool_calls(session, call_ids), read_only=True)

    def get_usage_summary(self, run_id: str) -> NamedRecord | None:
        "读取固定记录投影并在包内释放结果资源"
        return self._runner.run(lambda session: _queries.get_usage_summary(session, run_id), read_only=True)

    def list_usage_by_task(self, run_id: str) -> list[NamedRecord]:
        "读取固定记录投影并在包内释放结果资源"
        return self._runner.run(lambda session: _queries.list_usage_by_task(session, run_id), read_only=True)

    def list_usage_by_call_type(self, run_id: str) -> list[NamedRecord]:
        "读取固定记录投影并在包内释放结果资源"
        return self._runner.run(lambda session: _queries.list_usage_by_call_type(session, run_id), read_only=True)

    def list_usage_by_model(self, run_id: str) -> list[NamedRecord]:
        "读取固定记录投影并在包内释放结果资源"
        return self._runner.run(lambda session: _queries.list_usage_by_model(session, run_id), read_only=True)
