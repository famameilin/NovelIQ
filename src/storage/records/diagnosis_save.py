"正式诊断发布的普通输入记录"

from dataclasses import dataclass

from src.storage.records.cases import CaseSave
from src.storage.records.facts import FactSave


@dataclass(frozen=True, slots=True)
class DiagnosisPublish:
    run_id: str
    session_id: str
    report: dict
    assessments: tuple[dict, ...]
    organization_json: str
    declaration_ids: frozenset[str]
    facts: tuple[FactSave, ...]
    dialogue_updates: tuple[dict, ...]
    cases: tuple[CaseSave, ...]
