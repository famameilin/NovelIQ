"""metrics 的普通记录只读入口"""

from __future__ import annotations

from collections.abc import Iterable

from src.storage.input_boundary import plain_inputs
from src.storage.records.values import NamedRecord
from src.storage.repositories.queries import metrics as _queries


@plain_inputs
class MetricsReads:
    "只返回脱离数据库资源的普通记录"

    def __init__(self, runner):
        self._runner = runner

    def list_output_label_counts(self, record_ids: Iterable[str]) -> list[NamedRecord]:
        "读取固定记录投影并在包内释放结果资源"
        return self._runner.run(lambda session: _queries.list_output_label_counts(session, record_ids), read_only=True)

    def find_global_stats(self, run_id: str) -> str | None:
        "读取固定记录投影并在包内释放结果资源"
        return self._runner.run(lambda session: _queries.find_global_stats(session, run_id), read_only=True)
