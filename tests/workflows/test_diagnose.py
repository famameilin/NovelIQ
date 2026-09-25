"""
创建时间: 2026-04-26
任务: fix-phase2-setup-pool-followup-findings
说明: 覆盖 diagnosis 工作流日志的正式预期输出标签。
"""

from __future__ import annotations

from unittest.mock import MagicMock

from src.storage.models import GraphEntity
from src.workflows.diagnose import _persist_main_character_attributes
from tests.support.chapter_annotation_helpers import create_run_with_chunks


def test_persist_main_character_attributes_clears_previous_run_flags(db_session, monkeypatch) -> None:
    """2026-08-13 P2-2 重跑诊断先清除该 run 全部实体的 is_main_character 标记，
    避免只置位不清理导致已下榜角色残留主角标记"""
    from uuid import NAMESPACE_DNS, uuid5

    from src.knowledge.authority import KnowledgeGraphAuthorityService

    _novel_id, run_id = create_run_with_chunks(db_session, texts=["原文"])

    def _entity_id(name: str) -> str:
        # 2026-09-19 id 纪律：entity_id 是 uuid 主键，手工构造必须显式给
        # （与 persistence 同一铸造规则：uuid5(run_scope + 规范名)）
        return str(uuid5(NAMESPACE_DNS, f"novel-annotation-entity:{run_id}:{name.casefold()}"))

    former = GraphEntity(
        entity_id=_entity_id("旧主角"),
        run_id=run_id,
        canonical_name="旧主角",
        entity_type="character",
        attributes={"is_main_character": True},
        first_seen_chapter=0,
        last_seen_chapter=0,
    )
    current = GraphEntity(
        entity_id=_entity_id("新主角"),
        run_id=run_id,
        canonical_name="新主角",
        entity_type="character",
        attributes={},
        first_seen_chapter=0,
        last_seen_chapter=0,
    )
    db_session.add_all([former, current])
    db_session.flush()

    class _Item:
        def __init__(self, entity_id: str, name: str) -> None:
            self.entity_id = entity_id
            self.name = name
            self.aliases: list[str] = []

    class _FakeView:
        canonical_entities = [_Item(current.entity_id, "新主角")]

    fake_service = MagicMock()
    fake_service.build_export_view.return_value = _FakeView()
    monkeypatch.setattr(
        KnowledgeGraphAuthorityService,
        "from_session",
        lambda session: fake_service,
    )

    _persist_main_character_attributes(
        db_session,
        run_id=run_id,
        main_characters=["新主角"],
    )

    db_session.flush()
    rows = {
        row.canonical_name: dict(row.attributes or {})
        for row in db_session.query(GraphEntity).filter(GraphEntity.run_id == run_id)
    }
    assert "is_main_character" not in rows["旧主角"]
    assert rows["新主角"].get("is_main_character") is True
