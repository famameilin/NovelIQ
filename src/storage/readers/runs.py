"""runs 的普通记录只读入口"""

from __future__ import annotations

from src.storage.input_boundary import plain_inputs
from src.storage.records.models import (
    RunRecord,
)
from src.storage.repositories.queries import runs as _queries


@plain_inputs
class RunsReads:
    "只返回脱离数据库资源的普通记录"

    def __init__(self, runner):
        self._runner = runner

    def get_run(self, run_id: str) -> RunRecord | None:
        "读取固定记录投影并在包内释放结果资源"
        return self._runner.run(lambda session: _queries.get_run(session, run_id), read_only=True)

    def get_novel_id(self, run_id: str) -> str | None:
        "读取固定记录投影并在包内释放结果资源"
        return self._runner.run(lambda session: _queries.get_novel_id(session, run_id), read_only=True)

    def find_novel_id(self, run_id: str) -> str | None:
        "读取固定记录投影并在包内释放结果资源"
        return self._runner.run(lambda session: _queries.find_novel_id(session, run_id), read_only=True)
