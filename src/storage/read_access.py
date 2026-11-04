"固定数据投影的公开读取接口"

from __future__ import annotations

from src.storage.readers.annotations import AnnotationsReads
from src.storage.readers.audit import AuditReads
from src.storage.readers.diagnosis import DiagnosisReads
from src.storage.readers.events import EventsReads
from src.storage.readers.graph import GraphReads
from src.storage.readers.linguistic import LinguisticReads
from src.storage.readers.metrics import MetricsReads
from src.storage.readers.runs import RunsReads
from src.storage.readers.system import SystemReads
from src.storage.readers.text import TextReads
from src.storage.readers.topics import TopicsReads


class ReadAccess:
    "按数据语义提供独立读取能力"

    def __init__(self, runner):
        self.annotations = AnnotationsReads(runner)
        self.audit = AuditReads(runner)
        self.diagnosis = DiagnosisReads(runner)
        self.events = EventsReads(runner)
        self.graph = GraphReads(runner)
        self.linguistic = LinguisticReads(runner)
        self.metrics = MetricsReads(runner)
        self.runs = RunsReads(runner)
        self.system = SystemReads(runner)
        self.text = TextReads(runner)
        self.topics = TopicsReads(runner)
