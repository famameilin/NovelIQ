"""
创建时间: 2026-04-26
任务: fix-phase2-setup-pool-followup-findings
说明: 覆盖 diagnosis 工作流日志的正式预期输出标签。
"""

from __future__ import annotations

from unittest.mock import MagicMock

from src.models.cloud.schema import CloudAnalysis
from src.storage.models import GraphEntity
from src.workflows.diagnose import _log_diagnosis_results, _persist_main_character_attributes
from tests.support.chapter_annotation_helpers import create_run_with_chunks


def test_log_diagnosis_results_labels_expectation(monkeypatch) -> None:
    """
    校验 diagnosis 工作流日志输出正式的伏笔回收预期字段。

    创建时间: 2026-04-26
    任务: remove-foreshadow-rate-contract
    新建原因: 彻底移除 foreshadow_rate 后，工作流日志也必须只展示正式的 foreshadow_expectation。
    """

    messages: list[str] = []

    def _capture(message: str) -> None:
        messages.append(message)

    monkeypatch.setattr("src.workflows.diagnose.logger.info", _capture)

    _log_diagnosis_results(
        CloudAnalysis(
            novel_id="novel-1",
            foreshadow_expectation=0.35,
            arc_scores={"沈砚": 8.0},
            genre_labels=["通用"],
            style_labels=["严肃"],
            topic_labels=["成长"],
            diagnosis="ok",
            value_logic_type="善义有价值",
            narrative_arc_type="白手起家",
            focus_structure="single",
            focus_characters=["沈砚"],
            main_characters=["沈砚"],
            core_cast=["沈砚"],
        )
    )

    assert any("Foreshadow Expectation: 35.00%" in message for message in messages)


def test_persist_main_character_attributes_clears_previous_run_flags(db_session, monkeypatch) -> None:
    """2026-08-13 P2-2 重跑诊断先清除该 run 全部实体的 is_main_character 标记，
    避免只置位不清理导致已下榜角色残留主角标记"""
    from src.knowledge.authority import KnowledgeGraphAuthorityService

    _novel_id, run_id = create_run_with_chunks(db_session, texts=["原文"])
    former = GraphEntity(
        run_id=run_id,
        canonical_name="旧主角",
        entity_type="character",
        attributes={"is_main_character": True},
        first_seen_chapter=0,
        last_seen_chapter=0,
    )
    current = GraphEntity(
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
        def __init__(self, entity_id: int, name: str) -> None:
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
