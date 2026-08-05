from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from src.storage.repositories.diagnosis_repository import DiagnosisRepository


def test_fetch_character_disambig_data_reads_graph_characters_and_aliases() -> None:
    """2026-08-05 用于验证诊断人物合同只读取数据库图实体与别名"""
    session = MagicMock()
    with patch("src.storage.repositories.diagnosis_repository.GraphRepository") as graph_repository:
        graph_repository.return_value.fetch_entities.return_value = [
            SimpleNamespace(canonical_name="顾霜"),
            SimpleNamespace(canonical_name="司夜"),
        ]
        graph_repository.return_value.fetch_alias_map.return_value = {
            "阿顾": "顾霜",
            "顾霜": "顾霜",
            "司夜": "司夜",
        }

        known, aliases = DiagnosisRepository(session).fetch_character_disambig_data("run-1")

    assert known == ["司夜", "顾霜"]
    assert aliases == {"阿顾": "顾霜"}


def test_fetch_character_disambig_data_filters_aliases_without_known_target() -> None:
    """2026-08-05 用于验证诊断别名只保留指向当前人物实体的非自映射"""
    session = MagicMock()
    with patch("src.storage.repositories.diagnosis_repository.GraphRepository") as graph_repository:
        graph_repository.return_value.fetch_entities.return_value = [
            SimpleNamespace(canonical_name="顾霜"),
        ]
        graph_repository.return_value.fetch_alias_map.return_value = {
            "顾霜": "顾霜",
            "灰衣人": "未知人物",
        }

        known, aliases = DiagnosisRepository(session).fetch_character_disambig_data("run-1")

    assert known == ["顾霜"]
    assert aliases == {}
