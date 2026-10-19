"正式诊断保存的普通输入记录"

from dataclasses import dataclass

from src.storage.records.cases import CaseSave
from src.storage.records.facts import FactSave


@dataclass(frozen=True, slots=True)
class DiagnosisReportSave:
    run_id: str
    agent_id: str
    report: dict
    assessments: tuple[dict, ...]
    organization_json: str
    declaration_ids: frozenset[str]
    facts: tuple[FactSave, ...]
    dialogue_updates: tuple[dict, ...]
    cases: tuple[CaseSave, ...]


@dataclass(frozen=True, slots=True)
class DiagnosisSessionSave:
    run_id: str
    agent_id: str
    organization_json: str
    declaration_ids: frozenset[str]
    facts: tuple[FactSave, ...]
    dialogue_updates: tuple[dict, ...]
    cases: tuple[CaseSave, ...]
