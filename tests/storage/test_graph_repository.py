"""章节图谱历史查询仓储测试"""

from __future__ import annotations

import pytest

from src.storage.repositories import GraphRepository, ParagraphRepository
from tests.support.chapter_annotation_helpers import (
    character_fact,
    commit_test_annotation,
    create_run_with_chunks,
    persist_chapter_annotation,
    relation_fact,
)


def _relation_id(session, run_id: str, from_name: str, to_name: str, relation_type: str) -> str:
    """按正式关系读面定位唯一关系身份（关系行的 run 从端点实体取得）"""
    rows = [
        row
        for row in GraphRepository(session).fetch_latest_relations(run_id, active_only=False)
        if row.relation_type == relation_type and {str(row.from_name), str(row.to_name)} == {from_name, to_name}
    ]
    if len(rows) != 1:
        raise ValueError(f"测试夹具未唯一定位关系: {from_name}/{to_name}/{relation_type}")
    return str(rows[0].relation_id)


def _retract_relation(
    session,
    *,
    run_id: str,
    chapter_id: int,
    from_name: str,
    to_name: str,
    relation_type: str,
    reason: str,
    characters: list[dict] | None = None,
) -> None:
    """按正式 work 保存入口提交本章事实图操作：人物观察 + 一次关系撤回

    2026-10-16 3NF：关系变化是 chapter_annotations 的事实图操作，经 agent._save
    与原文证据同事务落库；这里沿用同一入口，不手拼图事实行。
    """
    from src.agents.annotation.output_models import BoundChapterAnnotation
    from src.event_trees.models import EventParticipantInput
    from src.fact_graph.inputs import ChapterMetricsInput
    from src.fact_graph.outputs import BoundCharacterObservation

    entity_ops: list[dict] = []
    observations: list[BoundCharacterObservation] = []
    participants: list[EventParticipantInput] = []
    for fact in characters or []:
        for spec in fact["_entity_specs"]:
            key = (str(spec["name"]), str(spec["entity_type"]))
            if all((str(op["name"]), str(op["entity_type"])) != key for op in entity_ops):
                entity_ops.append(
                    {
                        "name": spec["name"],
                        "entity_type": spec["entity_type"],
                        "tags": list(spec.get("tags") or []),
                        "description": None,
                        "representative": None,
                        "chapter_id": chapter_id,
                    }
                )
        observation = BoundCharacterObservation(
            character=fact["character"],
            role_function=fact["role_function"],
            action=fact["action"],
            emotion=fact["emotion"],
        )
        observations.append(observation)
        # 人物动态观测随事件参与者落账（participant 事实，不与实体操作混写）
        participants.append(
            EventParticipantInput(
                entity=str(fact["character"]),
                role="主体",
                narrative_role=observation.role_function,
                action=observation.action,
                emotion=observation.emotion,
            )
        )
    events = []
    if participants:
        from uuid import uuid4

        from src.event_trees.models import BoundEvent

        paragraph_id = min(
            row.paragraph_id
            for row in ParagraphRepository(session).fetch_paragraph_rows_batch(
                run_id, chapter_id=chapter_id, limit=None
            )
        )
        node_id = str(uuid4())
        events.append(
            BoundEvent(
                declaration_id=node_id,
                node_id=node_id,
                tree_id=f"tree-{uuid4()}",
                parent_node_id=None,
                cause_role="root",
                title="本章人物动态",
                problem="本章人物如何行动",
                summary="本章人物动态",
                event_type="行动",
                status="ongoing",
                description="本章人物动态",
                evidence_paragraph_id=paragraph_id,
                participants=participants,
            )
        )

    commit_test_annotation(
        session,
        run_id=run_id,
        chapter_id=chapter_id,
        annotation=BoundChapterAnnotation(
            metrics=ChapterMetricsInput(summary="关系变化", emotional_valence=0, narrative_function="转折"),
            character_observations=observations,
            dialogues=[],
            events=events,
        ),
        entity_ops=entity_ops,
        relation_assert_ops=[
            {
                "from_entity": from_name,
                "to_entity": to_name,
                "relation_type": relation_type,
                "chapter_id": chapter_id,
                "change_kind": "retract",
                "reason": reason,
            }
        ],
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
            character_fact(chapter_id=1, name="林渡", action="迎敌"),
            character_fact(chapter_id=1, name="顾霜", action="迎敌"),
        ],
        relations=[
            relation_fact(
                chapter_id=1,
                from_name="林渡",
                to_name="顾霜",
                relation_type="盟友",
            )
        ],
    )
    db_session.commit()
    first_boundary = GraphRepository(db_session).resolve_chapter_boundary(run_id, chapter_id=1)
    assert first_boundary is not None
    relation_id = _relation_id(db_session, run_id, "林渡", "顾霜", "盟友")
    _retract_relation(
        db_session,
        run_id=run_id,
        chapter_id=2,
        from_name="林渡",
        to_name="顾霜",
        relation_type="盟友",
        reason="分道扬镳",
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
    assert [(row.from_name, row.to_name, row.is_active) for row in first_snapshot.relations] == [("林渡", "顾霜", True)]
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
    assert relation_changes[0].changes[0]["change_kind"] == "retract"
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
            character_fact(chapter_id=1, name="林渡", action="授艺"),
            character_fact(chapter_id=1, name="顾霜", action="学习"),
        ],
        relations=[
            relation_fact(
                chapter_id=1,
                from_name="林渡",
                to_name="顾霜",
                relation_type="盟友",
            ),
            relation_fact(
                chapter_id=1,
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
                chapter_id=1,
                from_name="林渡",
                to_name="顾霜",
                relation_type="盟友",
            )
        ],
    )
    _retract_relation(
        db_session,
        run_id=run_id,
        chapter_id=2,
        from_name="林渡",
        to_name="顾霜",
        relation_type="盟友",
        reason="分道扬镳",
        characters=[character_fact(chapter_id=2, name="林渡", action="离开")],
    )
    db_session.commit()

    repository = GraphRepository(db_session)
    changes, total = repository.fetch_changes(run_id, chapter_id=2)

    state_changes = [row for row in changes if row.change_kind == "state"]
    relation_changes = [row for row in changes if row.change_kind == "relation"]
    # 章 2 的人物更新（动作=离开）与关系撤回都必须出现在本章变化里
    assert any(
        change.get("field") == "action" and change.get("after") == "离开"
        for row in state_changes
        for change in row.changes
    )
    assert any(
        change.get("change_kind") == "retract"
        for row in relation_changes
        for change in row.changes
    )
    assert total == len(changes) == len(state_changes) + len(relation_changes)
    assert all(row.chapter_id == 2 for row in changes)


@pytest.mark.parametrize("reverse_endpoints", [False, True])
def test_graph_repository_break_targets_relation_created_after_first_chapter(
    db_session, reverse_endpoints: bool,
) -> None:
    """同名的第一章提及不能替代第二章实际建立关系的端点"""
    _novel_id, run_id = create_run_with_chunks(
        db_session, texts=["林渡与顾霜初遇", "林渡与顾霜结盟", "两人分道扬镳"],
        chapter_ids=[1, 2, 3], title="关系端点来源",
    )
    persist_chapter_annotation(
        db_session, run_id=run_id, chapter_id=1,
        characters=[character_fact(chapter_id=1, name="林渡", action="初遇"),
                    character_fact(chapter_id=1, name="顾霜", action="初遇")],
    )
    persist_chapter_annotation(
        db_session, run_id=run_id, chapter_id=2,
        relations=[relation_fact(chapter_id=2, from_name="林渡", to_name="顾霜", relation_type="盟友")],
    )
    relation_id = _relation_id(db_session, run_id, "林渡", "顾霜", "盟友")
    from_name, to_name = ("顾霜", "林渡") if reverse_endpoints else ("林渡", "顾霜")
    _retract_relation(
        db_session, run_id=run_id, chapter_id=3,
        from_name=from_name, to_name=to_name, relation_type="盟友", reason="分道扬镳",
    )

    repository = GraphRepository(db_session)
    snapshot = repository.fetch_snapshot(run_id, chapter_id=3)
    assert snapshot is not None
    assert snapshot.relations == []
    changes, total = repository.fetch_changes(run_id, chapter_id=3)
    assert total == len(changes) == 1
    assert changes[0].relation_id == relation_id
    assert changes[0].changes[0]["change_kind"] == "retract"


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
            character_fact(chapter_id=1, name="林渡", action="迎敌"),
            character_fact(chapter_id=1, name="顾霜", action="迎敌"),
        ],
        relations=[relation_fact(chapter_id=1, from_name="林渡", to_name="顾霜", relation_type="盟友")],
    )
    db_session.commit()
    # 章2：再次确认关系（关系形态只有 assert/retract，加深=重新断言）+ 新增实体
    persist_chapter_annotation(
        db_session,
        run_id=run_id,
        chapter_id=2,
        characters=[
            character_fact(chapter_id=2, name="林渡", action="同行"),
            character_fact(chapter_id=2, name="顾霜", action="同行"),
            character_fact(chapter_id=2, name="白鹤", action="旁观"),
        ],
        relations=[relation_fact(chapter_id=2, from_name="林渡", to_name="顾霜", relation_type="盟友")],
    )
    db_session.commit()
    # 章3：关系撤回
    _retract_relation(
        db_session,
        run_id=run_id,
        chapter_id=3,
        from_name="林渡",
        to_name="顾霜",
        relation_type="盟友",
        reason="分道扬镳",
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
