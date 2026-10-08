"""诊断 HTTP 结果装配"""

from src.api.models.responses import DiagnosisResult
from src.diagnosis.read import query_diagnosis
from src.storage.repositories import StatsRepository


def _has_diagnosis_result(diagnosis: DiagnosisResult | None) -> bool:
    return diagnosis is not None


def _fetch_diagnosis(run_id: str, novel_id: str, stats_repo: StatsRepository) -> DiagnosisResult | None:
    result = query_diagnosis(run_id, novel_id, stats_repo)
    return DiagnosisResult.model_validate(result.model_dump()) if result is not None else None
