"案例完整保存入口，不接收外部事务或领域运行时对象"

from __future__ import annotations

from typing import Any

from src.storage.input_boundary import plain_inputs
from src.storage.records.cases import CaseSave
from src.storage.repositories.case_writes import CaseWritesRepository


@plain_inputs
class CaseAccess:
    def __init__(self, runner):
        self._runner = runner

    def ids(self, run_id: str) -> set[str]:
        "读取本运行正式案例的实际身份集合"
        return self._runner.run(lambda session: CaseWritesRepository(run_id)._case_ids(session), read_only=True)

    def rows(self, run_id: str):
        "读取本运行的案例行"
        return self._runner.run(lambda session: CaseWritesRepository(run_id).rows(session), read_only=True)

    def save(self, contribution: CaseSave, *, adopted_output_id: str | None = None) -> list[dict[str, Any]]:
        "一次操作完成案例保存，允许的局部冲突作为具名告警返回"
        return self._runner.run(
            lambda session: CaseWritesRepository(contribution.run_id).save_work(
                session, contribution, adopted_output_id=adopted_output_id
            )
        )
