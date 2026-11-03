"""diagnosis 的普通记录只读入口"""

from __future__ import annotations

from src.storage.input_boundary import plain_inputs
from src.storage.records.models import (
    AnalysisAssessmentRecord,
    DiagnosisReportRecord,
)
from src.storage.records.values import NamedRecord
from src.storage.repositories.queries import diagnosis as _queries


@plain_inputs
class DiagnosisReads:
    "只返回脱离数据库资源的普通记录"

    def __init__(self, runner):
        self._runner = runner

    def list_run_reports(self, run_id: str) -> list[DiagnosisReportRecord]:
        "读取固定记录投影并在包内释放结果资源"
        return self._runner.run(lambda session: _queries.list_run_reports(session, run_id), read_only=True)

    def find_latest_report(self, run_id: str) -> DiagnosisReportRecord | None:
        "读取固定记录投影并在包内释放结果资源"
        return self._runner.run(lambda session: _queries.find_latest_report(session, run_id), read_only=True)

    def find_cast_assessment(self, cast_role: str, report: DiagnosisReportRecord) -> int | None:
        "读取固定记录投影并在包内释放结果资源"
        return self._runner.run(
            lambda session: _queries.find_cast_assessment(session, cast_role, report), read_only=True
        )

    def find_labeled_assessment(self, column: str, report: DiagnosisReportRecord) -> int | None:
        "读取固定记录投影并在包内释放结果资源"
        return self._runner.run(
            lambda session: _queries.find_labeled_assessment(session, column, report), read_only=True
        )

    def get_latest_report(self, run_id: str) -> DiagnosisReportRecord | None:
        "读取固定记录投影并在包内释放结果资源"
        return self._runner.run(lambda session: _queries.get_latest_report(session, run_id), read_only=True)

    def list_topic_assessments(self, report_id: str) -> list[AnalysisAssessmentRecord]:
        "读取固定记录投影并在包内释放结果资源"
        return self._runner.run(lambda session: _queries.list_topic_assessments(session, report_id), read_only=True)

    def list_character_scores(self, report_id: str) -> list[NamedRecord]:
        "读取固定记录投影并在包内释放结果资源"
        return self._runner.run(lambda session: _queries.list_character_scores(session, report_id), read_only=True)

    def list_labels(self, column: str, report_id: str) -> list[NamedRecord]:
        "读取固定记录投影并在包内释放结果资源"
        return self._runner.run(lambda session: _queries.list_labels(session, column, report_id), read_only=True)

    def list_cast_names(self, cast_role: str, report_id: str) -> list[str]:
        "读取固定记录投影并在包内释放结果资源"
        return self._runner.run(lambda session: _queries.list_cast_names(session, cast_role, report_id), read_only=True)

    def find_latest_run_report(self, run_id: str) -> DiagnosisReportRecord | None:
        "读取固定记录投影并在包内释放结果资源"
        return self._runner.run(lambda session: _queries.find_latest_run_report(session, run_id), read_only=True)
