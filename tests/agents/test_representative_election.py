"""规范名选举纯函数测试"""

import uuid

from sqlalchemy import select

from src.storage.models import (
    ChapterAnnotationRecord,
    GraphEntity,
    GraphRelation,
    GraphRelationVersion,
    GraphVersion,
)
from src.storage.repositories.graph.election import elect_representatives
from src.workflows.annotate_helpers.storage import _reelect_representatives
from tests.support.chapter_annotation_helpers import create_run_with_chunks


class FakeEntity:
    def __init__(self, entity_id: int, canonical_name: str) -> None:
        self.entity_id = entity_id
        self.canonical_name = canonical_name
        self.attributes: dict = {}


def test_election_marks_single_component() -> None:
    entities = [FakeEntity(1, "石轩"), FakeEntity(2, "小石头"), FakeEntity(3, "张三")]
    flags = elect_representatives(entities, pairs=[(1, 2)])
    assert flags == {1: True, 2: False, 3: False}


def test_election_chain_converges_to_min_id() -> None:
    entities = [FakeEntity(100, "甲"), FakeEntity(200, "乙"), FakeEntity(300, "丙")]
    flags = elect_representatives(entities, pairs=[(100, 200), (200, 300)])
    assert flags[100] is True
    assert flags[200] is False
    assert flags[300] is False


def test_election_disjoint_components() -> None:
    entities = [FakeEntity(1, "A"), FakeEntity(2, "B"), FakeEntity(3, "C"), FakeEntity(4, "D")]
    flags = elect_representatives(entities, pairs=[(1, 2), (3, 4)])
    assert flags[1] is True and flags[2] is False
    assert flags[3] is True and flags[4] is False


def _add_entity(session, run_id: str, name: str) -> int:
    entity = GraphEntity(
        run_id=run_id,
        canonical_name=name,
        entity_type="character",
        tags=[],
        attributes={},
        first_seen_chapter=1,
        last_seen_chapter=1,
    )
    session.add(entity)
    session.flush()
    return int(entity.entity_id)


def test_reelect_uses_latest_relation_version_only(db_session) -> None:
    """2026-08-13 P1-3 用于验证选举只取每关系最新版本：历史残留 active 版本
    （关系已被后续章节 break）混入会让已解绑实体对被错误合并成同一人"""
    _novel_id, run_id = create_run_with_chunks(db_session, texts=["甲与乙同框"], title="选举防御")
    entity_a = _add_entity(db_session, run_id, "甲")
    entity_b = _add_entity(db_session, run_id, "乙")
    _add_entity(db_session, run_id, "丙")

    annotation = ChapterAnnotationRecord(
        annotation_id=f"ann-{run_id[:20]}",
        run_id=run_id,
        chapter_id=1,
        payload={},
    )
    annotation_2 = ChapterAnnotationRecord(
        annotation_id=f"ann-{run_id[:20]}2",
        run_id=run_id,
        chapter_id=2,
        payload={},
    )
    db_session.add_all([annotation, annotation_2])
    db_session.flush()

    graph_version = GraphVersion(
        graph_version_id=run_id,
        run_id=run_id,
        chapter_id=1,
        chapter_order=1,
        first_chapter_id=1,
        last_chapter_id=1,
        annotation_id=annotation.annotation_id,
    )
    graph_version_2 = GraphVersion(
        # 2026-08-13 修复 flaky：f"{run_id[:35]}2" 在 run_id 末位恰好为 '2' 时
        # 与 graph_version_id=run_id 相同 → 撞主键。改用独立 uuid4。
        graph_version_id=str(uuid.uuid4()),
        run_id=run_id,
        chapter_id=2,
        chapter_order=2,
        first_chapter_id=1,
        last_chapter_id=1,
        annotation_id=annotation_2.annotation_id,
    )
    db_session.add_all([graph_version, graph_version_2])
    db_session.flush()

    relation = GraphRelation(
        relation_id=run_id,
        run_id=run_id,
        from_entity_id=entity_a,
        to_entity_id=entity_b,
        directionality="bidirectional",
        relation_semantics="same_character",
    )
    db_session.add(relation)
    db_session.flush()
    # v1 断言 active（历史残留，chapter 1），v2 已 break（最新 inactive，chapter 2）
    # ——修复前 v1 仍会被计入选民对
    db_session.add_all(
        [
            GraphRelationVersion(
                graph_version_id=graph_version.graph_version_id,
                run_id=run_id,
                chapter_id=1,
                relation_id=relation.relation_id,
                relation_revision=1,
                relation_type="同一人物",
                attributes={},
                is_active=True,
                changes=[{"change_kind": "assert"}],
            ),
            GraphRelationVersion(
                graph_version_id=graph_version_2.graph_version_id,
                run_id=run_id,
                chapter_id=2,
                relation_id=relation.relation_id,
                relation_revision=2,
                relation_type="同一人物",
                attributes={},
                is_active=False,
                changes=[{"change_kind": "break"}],
            ),
        ]
    )
    db_session.commit()

    _reelect_representatives(db_session, run_id=run_id)
    db_session.commit()

    flags = {
        int(row.entity_id): row.attributes.get("is_representative")
        for row in db_session.execute(
            select(GraphEntity).where(GraphEntity.run_id == run_id)
        ).scalars()
    }
    # 最新版本已 break：甲/乙不再属于同一分量（未参与分量一律 false，
    # 修复前 v1 残留 active 会把甲选为 {甲,乙} 分量的代表 → flags[甲] is True）
    assert flags[entity_a] is False
    assert flags[entity_b] is False
