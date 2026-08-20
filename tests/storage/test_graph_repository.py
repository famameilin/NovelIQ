"""章节图谱历史查询仓储测试"""

from __future__ import annotations

from sqlalchemy import select

from src.agents.annotation.schema import ResolvedCase
from src.storage.models import GraphRelation
from src.storage.repositories import GraphRepository
from tests.support.chapter_annotation_helpers import (
    character_fact,
    create_run_with_chunks,
    persist_chapter_annotation,
    relation_fact,
)


def test_graph_repository_returns_frozen_chapter_snapshots_and_changes(db_session) -> None:
    """2026-08-07 用于验证章节快照继承状态并按事实原因返回关系变化"""
    _novel_id, run_id = create_run_with_chunks(
        db_session,
        texts=["林渡与顾霜并肩迎敌", "两人此后分道扬镳"],
        chapter_ids=[1, 2],
        title="图快照查询",
    )
    persist_chapter_annotation(
        db_session,
        run_id=run_id,
        chapter_id=1,
        characters=[
            character_fact(chunk_id=1, name="林渡", action="迎敌"),
            character_fact(chunk_id=1, name="顾霜", action="迎敌"),
        ],
        relations=[
            relation_fact(
                chunk_id=1,
                from_name="林渡",
                to_name="顾霜",
                relation_type="盟友",
            )
        ],
    )
    db_session.commit()
    first_boundary = GraphRepository(db_session).resolve_chapter_boundary(run_id, chapter_id=1)
    assert first_boundary is not None
    relation_id = db_session.execute(
        select(GraphRelation.relation_id).where(GraphRelation.run_id == run_id)
    ).scalar_one()
    persist_chapter_annotation(
        db_session,
        run_id=run_id,
        chapter_id=2,
        resolved_cases=[
            ResolvedCase(
                case_id="case-break",
                action="fact",
                type="relation_change",
                reason="分道扬镳",
                target_key="target-break",
                target_ref={"kind": "relation_change", "chunk_id": 2},
                from_entity="林渡",
                to_entity="顾霜",
                relation_type="盟友",
                change_kind="break",
            )
        ],
    )
    db_session.commit()
    second_boundary = GraphRepository(db_session).resolve_chapter_boundary(run_id, chapter_id=2)
    assert second_boundary is not None

    repository = GraphRepository(db_session)
    first_snapshot = repository.fetch_snapshot(run_id, chapter_id=1)
    second_snapshot = repository.fetch_snapshot(run_id, chapter_id=2)
    changes, total = repository.fetch_changes(run_id)

    assert first_snapshot is not None
    assert second_snapshot is not None
    assert [(row.from_name, row.to_name, row.is_active) for row in first_snapshot.relations] == [
        ("林渡", "顾霜", True)
    ]
    assert second_snapshot.relations == []
    assert {(entity.name, entity.state_chapter_id) for entity in second_snapshot.entities} == {
        ("林渡", 1),
        ("顾霜", 1),
    }
    assert total == len(changes)
    # 变化 ID 必须在当前 run 内唯一，供前端列表和深链使用
    assert len({row.change_id for row in changes}) == len(changes)
    relation_changes = [row for row in changes if row.change_kind == "relation"]
    assert [(row.chapter_id, row.relation_id) for row in relation_changes] == [
        (2, relation_id),
        (1, relation_id),
    ]
    assert relation_changes[0].changes[0]["change_kind"] == "break"
    assert relation_changes[0].effective_chapter_id == 2


def test_graph_repository_keeps_parallel_stable_relations_for_same_entity_pair(db_session) -> None:
    """2026-08-07 用于验证同一实体对可并行保存不同关系语义"""
    _novel_id, run_id = create_run_with_chunks(
        db_session,
        texts=["林渡与顾霜既是盟友也是师徒"],
        title="并行稳定关系",
    )
    persist_chapter_annotation(
        db_session,
        run_id=run_id,
        chapter_id=1,
        characters=[
            character_fact(chunk_id=1, name="林渡", action="授艺"),
            character_fact(chunk_id=1, name="顾霜", action="学习"),
        ],
        relations=[
            relation_fact(
                chunk_id=1,
                from_name="林渡",
                to_name="顾霜",
                relation_type="盟友",
            ),
            relation_fact(
                chunk_id=1,
                from_name="林渡",
                to_name="顾霜",
                relation_type="师徒",
            ),
        ],
    )
    db_session.commit()

    snapshot = GraphRepository(db_session).fetch_snapshot(run_id, chapter_id=1)

    assert snapshot is not None
    assert len({row.relation_id for row in snapshot.relations}) == 2
    assert {row.relation_type for row in snapshot.relations} == {"盟友", "师徒"}
    assert all(row.chapter_id == 1 for row in snapshot.relations)


def test_graph_repository_fetch_changes_filters_by_chapter_id(db_session) -> None:
    """2026-08-12 用于验证带 chapter_id 的 fetch_changes 在 PostgreSQL 上按章节过滤，
    不因 CTE 表别名错误（gv.chapter_id）报 missing FROM-clause entry"""
    _novel_id, run_id = create_run_with_chunks(
        db_session,
        texts=["林渡与顾霜并肩迎敌", "两人此后分道扬镳"],
        chapter_ids=[1, 2],
        title="章节过滤变化",
    )
    persist_chapter_annotation(
        db_session,
        run_id=run_id,
        chapter_id=1,
        relations=[
            relation_fact(
                chunk_id=1,
                from_name="林渡",
                to_name="顾霜",
                relation_type="盟友",
            )
        ],
    )
    persist_chapter_annotation(
        db_session,
        run_id=run_id,
        chapter_id=2,
        characters=[character_fact(chunk_id=2, name="林渡", action="离开")],
        resolved_cases=[
            ResolvedCase(
                case_id="case-break",
                action="fact",
                type="relation_change",
                reason="分道扬镳",
                target_key="target-break",
                target_ref={"kind": "relation_change", "chunk_id": 2},
                from_entity="林渡",
                to_entity="顾霜",
                relation_type="盟友",
                change_kind="break",
            )
        ],
    )
    db_session.commit()

    repository = GraphRepository(db_session)
    changes, total = repository.fetch_changes(run_id, chapter_id=2)

    assert total == len(changes) == 2
    assert {row.change_kind for row in changes} == {"state", "relation"}
    assert all(row.chapter_id == 2 for row in changes)


def test_graph_repository_fetch_changes_pagination_matches_full_set(db_session) -> None:
    """2026-08-13 补测试 P1：fetch_changes 的 offset/limit 分页 SQL 此前零真实执行覆盖。
    构造 3 章变化验证：分页拼接 = 全量、无重叠、倒序、total 一致。"""
    _novel_id, run_id = create_run_with_chunks(
        db_session,
        texts=["林渡与顾霜并肩迎敌", "两人关系日渐紧密", "两人最终分道扬镳"],
        chapter_ids=[1, 2, 3],
        title="分页测试",
    )
    # 章1：新建盟友关系（assert）
    persist_chapter_annotation(
        db_session,
        run_id=run_id,
        chapter_id=1,
        characters=[
            character_fact(chunk_id=1, name="林渡", action="迎敌"),
            character_fact(chunk_id=1, name="顾霜", action="迎敌"),
        ],
        relations=[relation_fact(chunk_id=1, from_name="林渡", to_name="顾霜", relation_type="盟友")],
    )
    db_session.commit()
    # 章2：强化关系 + 新增实体
    persist_chapter_annotation(
        db_session,
        run_id=run_id,
        chapter_id=2,
        characters=[
            character_fact(chunk_id=2, name="林渡", action="同行"),
            character_fact(chunk_id=2, name="顾霜", action="同行"),
            character_fact(chunk_id=2, name="白鹤", action="旁观"),
        ],
        resolved_cases=[
            ResolvedCase(
                case_id="case-2",
                action="fact",
                type="relation_change",
                reason="关系加深",
                target_key="target-2",
                target_ref={"kind": "relation_change", "chunk_id": 2},
                from_entity="林渡",
                to_entity="顾霜",
                relation_type="盟友",
                change_kind="reinforce",
            )
        ],
    )
    db_session.commit()
    # 章3：关系断裂
    persist_chapter_annotation(
        db_session,
        run_id=run_id,
        chapter_id=3,
        characters=[
            character_fact(chunk_id=3, name="林渡", action="离去"),
            character_fact(chunk_id=3, name="顾霜", action="离去"),
        ],
        resolved_cases=[
            ResolvedCase(
                case_id="case-3",
                action="fact",
                type="relation_change",
                reason="分道扬镳",
                target_key="target-3",
                target_ref={"kind": "relation_change", "chunk_id": 3},
                from_entity="林渡",
                to_entity="顾霜",
                relation_type="盟友",
                change_kind="break",
            )
        ],
    )
    db_session.commit()

    repository = GraphRepository(db_session)
    full, total = repository.fetch_changes(run_id)
    assert total == len(full) >= 4

    # 按章倒序：章3 的变化在前
    assert full[0].chapter_id == 3

    # 分页：limit=2 两页拼接须与全量一致且无重叠
    page1, total1 = repository.fetch_changes(run_id, offset=0, limit=2)
    page2, total2 = repository.fetch_changes(run_id, offset=2, limit=2)
    assert total1 == total2 == total
    assert len(page1) == 2
    assert len(page2) == 2
    page1_ids = {row.change_id for row in page1}
    page2_ids = {row.change_id for row in page2}
    assert not page1_ids & page2_ids
    # 分页按行号顺序取前 4 条，须与全量前 4 条完全一致（同序、无缺口）
    assert [row.change_id for row in page1 + page2] == [row.change_id for row in full[:4]]
    # 全量其余条目必须出现在后续页码中（第 5 条起）
    page3, _total3 = repository.fetch_changes(run_id, offset=4, limit=2)
    assert page3
    assert [row.change_id for row in page3] == [row.change_id for row in full[4:6]]

    # 越过末尾的页码返回空列表但 total 不变
    beyond, total_beyond = repository.fetch_changes(run_id, offset=1000, limit=2)
    assert beyond == []
    assert total_beyond == total


def test_graph_repository_fetch_changes_rejects_negative_offset(db_session) -> None:
    """2026-08-13 补测试 P1：负 offset 必须抛 ValueError（路由层 400 的依据）。"""
    _novel_id, run_id = create_run_with_chunks(db_session, texts=["第一章内容"], title="负偏移")
    repository = GraphRepository(db_session)
    import pytest as _pytest

    with _pytest.raises(ValueError):
        repository.fetch_changes(run_id, offset=-1)
