from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from src.storage.repositories.diagnosis_repository import DiagnosisRepository


def test_fetch_known_characters_reads_graph_entity_nodes() -> None:
    """2026-08-06 用于验证诊断人物合同只读取数据库图实体节点"""
    session = MagicMock()
    with patch("src.storage.repositories.diagnosis_repository.GraphRepository") as graph_repository:
        graph_repository.return_value.fetch_latest_entities.return_value = [
            SimpleNamespace(name="顾霜"),
            SimpleNamespace(name="司夜"),
        ]

        known = DiagnosisRepository(session).fetch_known_characters("run-1")

    assert known == ["司夜", "顾霜"]
