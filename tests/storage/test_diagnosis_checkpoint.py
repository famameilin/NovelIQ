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


def test_fetch_high_tension_chunks_orders_by_tension_composite_not_net_density() -> None:
    """2026-08-14 修复 §19.7：高张力诊断按张力复合指数 tension_composite 排序，
    不再按情绪强度 abs(net_density) 排序；NULL 处理保持原行为（> 0.01 过滤排除）。"""
    session = MagicMock()
    rows = [
        SimpleNamespace(chunk_id=1, text="情绪强但张力弱", tension=0.1),
        SimpleNamespace(chunk_id=2, text="张力强", tension=0.9),
        SimpleNamespace(chunk_id=3, text="中等", tension=0.5),
    ]
    session.execute.return_value = rows

    result = DiagnosisRepository(session).fetch_high_tension_chunks("run-1", limit=10)

    # 返回结构不变：(chunk_id, text, tension)
    assert result == [(1, "情绪强但张力弱", 0.1), (2, "张力强", 0.9), (3, "中等", 0.5)]

    # 排序与过滤表达式必须基于 tension_composite，而不是 net_density。
    stmt = session.execute.call_args.args[0]
    sql = str(stmt.compile(compile_kwargs={"literal_binds": True}))
    assert "tension_composite" in sql
    assert "net_density" not in sql

