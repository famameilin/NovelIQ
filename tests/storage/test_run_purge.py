"""run 级删除的范围与顺序：清理顺序覆盖全部 run 级表，且只清本 run"""

from __future__ import annotations

from sqlalchemy import func, select

from src.event_trees.storage_map import run_execution_ids
from src.storage.models import AnalysisRun, Base, Chapter, GraphEntity, GraphFact, Paragraph
from src.storage.repositories.run_repository import (
    _RUN_PURGE_ORDER,
    RunRepository,
    _run_purge_predicates,
)
from tests.support.chapter_annotation_helpers import (
    character_fact,
    create_run_with_chunks,
    persist_chapter_annotation,
)


def test_purge_order_covers_every_run_scoped_table() -> None:
    """35 表冻结结构：novels 是全局书目，其余每张表都必须有清理顺序与范围谓词"""
    assert set(_RUN_PURGE_ORDER) | {"novels"} == set(Base.metadata.tables)
    assert set(_run_purge_predicates("lock-probe")) == set(_RUN_PURGE_ORDER)


def test_delete_run_only_clears_its_own_run(db_session) -> None:
    _novel_a, run_a = create_run_with_chunks(db_session, texts=["第一段正文内容"])
    _novel_b, run_b = create_run_with_chunks(db_session, texts=["第一段正文内容"])
    persist_chapter_annotation(
        db_session, run_id=run_a, chapter_id=1, characters=[character_fact(chapter_id=1, name="甲", action="行动")]
    )
    persist_chapter_annotation(
        db_session, run_id=run_b, chapter_id=1, characters=[character_fact(chapter_id=1, name="乙", action="行动")]
    )

    def entity_names(run_id: str) -> list[str]:
        return list(
            db_session.scalars(
                select(GraphEntity.canonical_name)
                .where(GraphEntity.run_id == run_id)
                .order_by(GraphEntity.canonical_name)
            )
        )

    def scoped_count(model, column, run_id: str) -> int:
        return int(
            db_session.scalar(select(func.count()).select_from(model).where(column == run_id)) or 0
        )

    def direct_fact_count(run_id: str) -> int:
        return int(
            db_session.scalar(
                select(func.count())
                .select_from(GraphFact)
                .where(GraphFact.direct_producer_execution_id.in_(run_execution_ids(run_id)))
            )
            or 0
        )

    assert entity_names(run_a) == ["甲"] and entity_names(run_b) == ["乙"]
    facts_b = direct_fact_count(run_b)
    assert facts_b > 0

    assert RunRepository(db_session).delete_run(run_a) is True
    db_session.flush()

    assert db_session.get(AnalysisRun, run_a) is None
    assert entity_names(run_a) == []
    assert scoped_count(Chapter, Chapter.run_id, run_a) == 0
    assert scoped_count(Paragraph, Paragraph.run_id, run_a) == 0
    assert direct_fact_count(run_a) == 0
    assert RunRepository(db_session).delete_run(run_a) is False

    # 另一 run 的实体、事实与章节原样保留
    assert entity_names(run_b) == ["乙"]
    assert direct_fact_count(run_b) == facts_b
    assert scoped_count(Chapter, Chapter.run_id, run_b) == 1
    assert scoped_count(GraphEntity, GraphEntity.run_id, run_b) == 1
