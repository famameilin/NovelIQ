"""事件森林/DAG 查询仓储测试"""

from __future__ import annotations

from uuid import NAMESPACE_URL, uuid5

from src.agents.annotation.schema import BoundForeshadowing
from src.storage.repositories import ForeshadowingRepository
from src.storage.repositories.graph import EventForestRepository
from tests.support.chapter_annotation_helpers import (
    create_run_with_chunks,
    persist_chapter_annotation,
)


def test_fetch_snapshot_returns_event_trees_and_causal_edges(db_session) -> None:
    """2026-08-19 用于验证持久化后 fetch_snapshot 返回树视图与因果边（）"""
    text = "顾霜进入山门。\n顾霜拔剑。"
    _novel_id, run_id = create_run_with_chunks(
        db_session,
        texts=[text],
        title="事件森林快照",
    )
    eid1 = str(uuid5(NAMESPACE_URL, f"noveliq:event:{run_id}:1:1"))
    eid2 = str(uuid5(NAMESPACE_URL, f"noveliq:event:{run_id}:1:2"))
    persist_chapter_annotation(
        db_session,
        run_id=run_id,
        chapter_id=1,
        events=[
            {
                "description": "顾霜进入山门",
                "participants": ["顾霜"],
                "anchor_paragraph_ids": [0],
                "node_id": eid1,
                "tree_id": "gate-entry",
                "cause_role": "root",
            },
            {
                "description": "顾霜拔剑",
                "participants": ["顾霜"],
                "anchor_paragraph_ids": [1],
                "node_id": eid2,
                "causal_event_refs": [eid1],
                "tree_id": "draw-entry",
                "cause_role": "root",
            },
        ],
    )
    db_session.commit()

    repo = EventForestRepository(db_session)
    snapshot = repo.fetch_snapshot(run_id)
    assert snapshot is not None
    assert snapshot.chapter_order == 1
    assert len(snapshot.event_nodes) == 2
    nodes_by_desc = {n.description: n for n in snapshot.event_nodes}
    assert "顾霜进入山门" in nodes_by_desc
    assert "顾霜拔剑" in nodes_by_desc
    assert nodes_by_desc["顾霜进入山门"].event_id == eid1
    assert nodes_by_desc["顾霜拔剑"].event_id == eid2
    assert nodes_by_desc["顾霜进入山门"].tree_id == "gate-entry"
    assert nodes_by_desc["顾霜进入山门"].cause_role == "root"

    # 树视图：两棵树，因果边跨树；主链按原文顺序
    assert len(snapshot.event_trees) == 2
    gate_tree = next(t for t in snapshot.event_trees if t.tree_id == "gate-entry")
    assert gate_tree.root_event_id == eid1
    assert gate_tree.main_chain == [eid1]
    assert gate_tree.secondary_groups == []
    assert gate_tree.chapter_ids == [1]

    # 因果边（contains 已派生化：只返回 causal 且两端必非空）
    causal_edges = snapshot.causal_edges
    assert len(causal_edges) == 1
    assert all(edge.edge_type == "causal" for edge in causal_edges)
    assert all(edge.source_event_id is not None for edge in causal_edges)
    assert causal_edges[0].source_event_id == eid1
    assert causal_edges[0].target_event_id == eid2
    assert causal_edges[0].is_active is True


def test_fetch_snapshot_builds_secondary_branch_groups(db_session) -> None:
    """2026-08-19 用于验证次因分支（secondary）按因果前驱 target 归组（）"""
    text = "顾霜拔剑。\n顾霜喝止。\n顾霜降敌。"
    _novel_id, run_id = create_run_with_chunks(
        db_session,
        texts=[text],
        title="次因分支聚合",
    )
    eid1 = str(uuid5(NAMESPACE_URL, f"noveliq:event:{run_id}:1:1"))
    eid2 = str(uuid5(NAMESPACE_URL, f"noveliq:event:{run_id}:1:2"))
    eid3 = str(uuid5(NAMESPACE_URL, f"noveliq:event:{run_id}:1:3"))
    persist_chapter_annotation(
        db_session,
        run_id=run_id,
        chapter_id=1,
        events=[
            {
                "description": "顾霜拔剑",
                "participants": ["顾霜"],
                "anchor_paragraph_ids": [0],
                "node_id": eid1,
                "tree_id": "duel",
                "cause_role": "root",
            },
            {
                "description": "顾霜喝止",
                "participants": ["顾霜"],
                "anchor_paragraph_ids": [1],
                "node_id": eid2,
                "parent_node_id": eid1,
                "tree_id": "duel",
                "cause_role": "main",
            },
            {
                "description": "顾霜降敌",
                "participants": ["顾霜"],
                "anchor_paragraph_ids": [2],
                "node_id": eid3,
                "parent_node_id": eid2,
                "causal_event_refs": [eid2],
                "tree_id": "duel",
                "cause_role": "secondary",
            },
        ],
    )
    db_session.commit()

    snapshot = EventForestRepository(db_session).fetch_snapshot(run_id)
    assert snapshot is not None
    assert len(snapshot.event_trees) == 1
    tree = snapshot.event_trees[0]
    assert tree.root_event_id == eid1
    assert tree.main_chain == [eid1, eid2]
    # 次因分支（secondary 挂在主链事件 2 下）
    assert len(tree.secondary_groups) == 1
    assert tree.secondary_groups[0].target_event_id == eid2
    assert tree.secondary_groups[0].branch == [eid3]


def test_fetch_snapshot_includes_foreshadowing_edges(db_session) -> None:
    """2026-08-18 用于验证 fetch_snapshot 返回伏笔边（线程即边）"""
    _novel_id, run_id = create_run_with_chunks(
        db_session,
        texts=["顾霜立誓"],
        title="伏笔边快照",
    )
    persist_chapter_annotation(
        db_session,
        run_id=run_id,
        chapter_id=1,
        events=[
            {
                "description": "顾霜立誓",
                "participants": ["顾霜"],
                "anchor_paragraph_ids": [0],
            },
        ],
    )
    setup_eid = str(uuid5(NAMESPACE_URL, f"noveliq:event:{run_id}:1:1"))
    ForeshadowingRepository(db_session).sync(
        run_id=run_id,
        chapter_id=1,
        foreshadowing=BoundForeshadowing(
            description="顾霜承诺护佑山门",
            confidence="high",
            setup_node_id=setup_eid,
        ),
        setup_event_id=setup_eid,
    )
    db_session.commit()

    repo = EventForestRepository(db_session)
    snapshot = repo.fetch_snapshot(run_id)
    assert snapshot is not None
    assert len(snapshot.foreshadowing_edges) == 1
    edge = snapshot.foreshadowing_edges[0]
    assert edge.setup_summary == "顾霜承诺护佑山门"
    assert edge.setup_event_id == setup_eid
    assert edge.payoff_event_id is None
    assert edge.active is True


def test_fetch_snapshot_returns_none_for_missing_run(db_session) -> None:
    """2026-08-18 用于验证不存在的 run 查询返回 None"""
    repo = EventForestRepository(db_session)
    snapshot = repo.fetch_snapshot("nonexistent-run-id")
    assert snapshot is None


def test_fetch_snapshot_filters_by_chapter_id(db_session) -> None:
    """2026-08-18 用于验证 chapter_id 参数按章节边界截断事件节点"""
    _novel_id, run_id = create_run_with_chunks(
        db_session,
        texts=["顾霜进入山门。", "顾霜拔剑。"],
        chapter_ids=[1, 2],
        title="章节边界截断",
    )
    persist_chapter_annotation(
        db_session,
        run_id=run_id,
        chapter_id=1,
        events=[
            {
                "description": "顾霜进入山门",
                "participants": ["顾霜"],
                "anchor_paragraph_ids": [0],
            },
        ],
    )
    persist_chapter_annotation(
        db_session,
        run_id=run_id,
        chapter_id=2,
        events=[
            {
                "description": "顾霜拔剑",
                "participants": ["顾霜"],
                "anchor_paragraph_ids": [0],
            },
        ],
    )
    db_session.commit()

    repo = EventForestRepository(db_session)
    # 只取第 1 章：只有 1 个事件节点
    snapshot_ch1 = repo.fetch_snapshot(run_id, chapter_id=1)
    assert snapshot_ch1 is not None
    assert len(snapshot_ch1.event_nodes) == 1
    assert snapshot_ch1.event_nodes[0].description == "顾霜进入山门"

    # 取全部（最新版本=第 2 章）：2 个事件节点
    snapshot_all = repo.fetch_snapshot(run_id)
    assert snapshot_all is not None
    assert len(snapshot_all.event_nodes) == 2
    assert {n.description for n in snapshot_all.event_nodes} == {
        "顾霜进入山门",
        "顾霜拔剑",
    }
