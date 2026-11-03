"""linguistic 的普通记录只读入口"""

from __future__ import annotations

from src.storage.input_boundary import plain_inputs
from src.storage.records.values import NamedRecord
from src.storage.repositories.queries import linguistic as _queries


@plain_inputs
class LinguisticReads:
    "只返回脱离数据库资源的普通记录"

    def __init__(self, runner):
        self._runner = runner

    def get_completion_counts(self, run_id: str) -> NamedRecord:
        "读取固定记录投影并在包内释放结果资源"
        return self._runner.run(lambda session: _queries.get_completion_counts(session, run_id), read_only=True)

    def list_paragraph_labels(self, run_id: str) -> list[NamedRecord]:
        "读取固定记录投影并在包内释放结果资源"
        return self._runner.run(lambda session: _queries.list_paragraph_labels(session, run_id), read_only=True)
