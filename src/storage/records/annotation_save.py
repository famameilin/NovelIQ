"标注完整保存操作的固定输入"

from dataclasses import dataclass

from src.storage.records.cases import CaseSave
from src.storage.records.events import EventSave
from src.storage.records.facts import FactSave


@dataclass(frozen=True, slots=True)
class AnnotationSave:
    record: dict
    facts: FactSave
    events: EventSave
    cases: CaseSave
    dialogues: tuple[dict, ...]
    labels: tuple[dict, ...]
