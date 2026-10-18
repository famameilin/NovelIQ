"Storage 对外只提供完整读写操作、普通记录及生命周期能力"

from __future__ import annotations

from src.storage.access import (
    AnnotationAccess,
    ChapterAccess,
    DiagnosisAccess,
    ForestAccess,
    GraphAccess,
    LinguisticAccess,
    ParagraphAccess,
    RunAccess,
    StatisticsAccess,
)
from src.storage.audit_access import AuditAccess
from src.storage.case_access import CaseAccess
from src.storage.ids import new_id
from src.storage.narrative_access import NarrativeAccess
from src.storage.novel_access import NovelAccess
from src.storage.operations import OperationRunner
from src.storage.read_access import ReadAccess
from src.storage.sse_access import SseAccess


class Storage:
    "Repository、SQL 和事务由包内维护，业务不能获得活动连接或工作单元"

    def __init__(self, *, _runner: OperationRunner | None = None):
        self._runner = _runner or OperationRunner()
        self.audit = AuditAccess(self._runner)
        self.sse = SseAccess(self._runner)
        self.reads = ReadAccess(self._runner)
        self.cases = CaseAccess(self._runner)
        self.novels = NovelAccess(self._runner)
        self.narrative = NarrativeAccess(self._runner)
        self.runs = RunAccess(self._runner)
        self.chapters = ChapterAccess(self._runner)
        self.paragraphs = ParagraphAccess(self._runner)
        self.annotations = AnnotationAccess(self._runner)
        self.graph = GraphAccess(self._runner)
        self.working_graph = GraphAccess(self._runner, internal=True)
        self.diagnosis = DiagnosisAccess(self._runner)
        self.statistics = StatisticsAccess(self._runner)
        self.linguistic = LinguisticAccess(self._runner)
        self.forest = ForestAccess(self._runner)

    @staticmethod
    def new_id() -> str:
        "统一分配 UUIDv7；task 短 ID 是独立业务标识"
        return new_id()

    def initialize(self) -> None:
        from src.storage.db import init_db
        from src.storage.errors import translate_errors

        with translate_errors():
            init_db()

    def check_health(self) -> dict:
        "只返回健康状态和连接池计数，不输出连接或连接串"
        from sqlalchemy import text

        from src.storage.db import get_pool_status

        self._runner.run(lambda session: session.execute(text("SELECT 1")).scalar_one(), read_only=True)
        return {"database": "connected", "pool": get_pool_status()}

    def prepare_paragraph_vectors(self, embedding_dim: int) -> None:
        "向量结构准备是完整独立操作，提交时机由 Storage 保证"
        from src.storage.vector_schema import ensure_paragraph_embeddings_schema

        self._runner.run(lambda session: ensure_paragraph_embeddings_schema(session, embedding_dim))

    def validate_paragraph_vectors(self) -> None:
        "只验证正式向量结构，不自动改写旧结果"
        from src.storage.vector_schema import validate_paragraph_embeddings_schema

        self._runner.run(validate_paragraph_embeddings_schema, read_only=True)

    @staticmethod
    def pool_status() -> dict | None:
        "读取本进程连接池普通统计"
        from src.storage.db import get_pool_status

        return get_pool_status()

    @staticmethod
    def close() -> None:
        "应用关闭时释放本进程连接池，业务操作无需管理连接生命周期"
        from src.storage.db import dispose_engine

        dispose_engine()


_storage = Storage()


def get_storage() -> Storage:
    "获取无活动事务的 Storage 入口"
    return _storage


def get_storage_factory():
    "装配层注入 Storage 工厂；返回的入口没有活动连接或事务"
    return get_storage
