from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from src.storage.repositories.diagnosis_repository import DiagnosisRepository


def test_fetch_known_characters_falls_back_when_graph_missing() -> None:
    """2026-08-09 用于验证无图版本时诊断人物名单回退到原始实体节点"""
    session = MagicMock()
    with patch(
        "src.knowledge.authority.KnowledgeGraphAuthorityService"
    ) as authority_service:
        authority_service.from_session.return_value.build_export_view.side_effect = ValueError(
            "run 尚无已完成章节图版本"
        )
        with patch("src.storage.repositories.diagnosis_repository.GraphRepository") as graph_repository:
            graph_repository.return_value.fetch_latest_entities.return_value = [
                SimpleNamespace(name="顾霜"),
                SimpleNamespace(name="司夜"),
            ]

            known = DiagnosisRepository(session).fetch_known_characters("run-1")

    assert known == ["司夜", "顾霜"]


def test_fetch_known_characters_uses_canonical_view_with_aliases() -> None:
    """2026-08-09 用于验证诊断人物名单来自消歧后的规范视图并附别名映射"""
    session = MagicMock()
    canonical_entity = SimpleNamespace(
        entity_type="character",
        name="贺伯安",
        aliases=["贺重明", "伯安"],
    )
    null_entity = SimpleNamespace(
        entity_type="character",
        name="null",
        aliases=[],
    )
    location_entity = SimpleNamespace(
        entity_type="location",
        name="贺府",
        aliases=[],
    )
    with patch(
        "src.knowledge.authority.KnowledgeGraphAuthorityService"
    ) as authority_service:
        view = MagicMock()
        view.canonical_entities = [canonical_entity, null_entity, location_entity]
        authority_service.from_session.return_value.build_export_view.return_value = view

        known = DiagnosisRepository(session).fetch_known_characters("run-1")

    assert known == ["贺伯安（别名：贺重明、伯安）"]

