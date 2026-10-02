"""事件森林/DAG 查询仓储测试"""

from __future__ import annotations

from uuid import NAMESPACE_URL, uuid5

import pytest

from src.storage.models import EventEdge
from src.storage.repositories.graph import EventForestRepository
from tests.support.chapter_annotation_helpers import (
    commit_test_event_link,
    create_run_with_chunks,
    persist_chapter_annotation,
)

pytestmark = pytest.mark.usefixtures("pipeline_run_cleanup")


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
                "evidence_paragraph_id": 0,
                "node_id": eid1,
                "tree_id": "gate-entry",
                "cause_role": "root",
            },
            {
                "description": "顾霜拔剑",
                "participants": ["顾霜"],
                "evidence_paragraph_id": 1,
                "node_id": eid2,
                "tree_id": "draw-entry",
                "cause_role": "root",
            },
        ],
    )
    commit_test_event_link(
        db_session, run_id=run_id, chapter_id=1, source_event_id=eid1, target_event_id=eid2,
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


def test_fetch_snapshot_excludes_foreshadowing_edges_from_causal_edges(db_session) -> None:
    """连续性提交的伏笔关联不混入因果边列表"""
    text = "顾霜立誓。\n顾霜离去。"
    _novel_id, run_id = create_run_with_chunks(
        db_session,
        texts=[text],
        title="伏笔边不混因果",
    )
    root_id = str(uuid5(NAMESPACE_URL, f"noveliq:event:{run_id}:1:1"))
    bind_id = str(uuid5(NAMESPACE_URL, f"noveliq:event:{run_id}:1:2"))
    persist_chapter_annotation(
        db_session,
        run_id=run_id,
        chapter_id=1,
        events=[
            {
                "description": "顾霜立誓",
                "participants": ["顾霜"],
                "evidence_paragraph_id": 0,
                "node_id": root_id,
                "tree_id": "oath-tree",
                "cause_role": "root",
                "isforeshadowing": True,
                "payoff_likelihood": "high",
            },
            {
                "description": "顾霜离去",
                "participants": ["顾霜"],
                "evidence_paragraph_id": 1,
                "node_id": bind_id,
                "tree_id": "leave-tree",
                "cause_role": "root",
            },
        ],
    )
    commit_test_event_link(
        db_session, run_id=run_id, chapter_id=1, source_event_id=root_id, target_event_id=bind_id,
        edge_type="foreshadowing",
    )
    db_session.commit()

    snapshot = EventForestRepository(db_session).fetch_snapshot(run_id)
    assert snapshot is not None
    assert snapshot.causal_edges == []
    assert repo_foreshadow_edges(db_session, run_id) == 1


def repo_foreshadow_edges(session, run_id: str) -> int:
    """伏笔边有独立读取通道：确认被排除的边确实还在（只过滤、不丢数据）"""
    from sqlalchemy import func, select

    return int(
        session.execute(
            select(func.count()).select_from(EventEdge).where(
                EventEdge.run_id == run_id,
                EventEdge.edge_type == "foreshadowing",
            )
        ).scalar_one()
    )


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
    # 反字典序的 id 用来证明旁支顺序来自写入序号，而非节点 id 排序
    eid3 = f"evt-{run_id[:8]}-z"
    eid4 = f"evt-{run_id[:8]}-a"
    persist_chapter_annotation(
        db_session,
        run_id=run_id,
        chapter_id=1,
        events=[
            {
                "description": "顾霜拔剑",
                "participants": ["顾霜"],
                "evidence_paragraph_id": 0,
                "node_id": eid1,
                "tree_id": "duel",
                "cause_role": "root",
            },
            {
                "description": "顾霜喝止",
                "participants": ["顾霜"],
                "evidence_paragraph_id": 1,
                "node_id": eid2,
                "parent_node_id": eid1,
                "tree_id": "duel",
                "cause_role": "main",
            },
            {
                "description": "顾霜降敌",
                "participants": ["顾霜"],
                "evidence_paragraph_id": 2,
                "node_id": eid3,
                "parent_node_id": eid2,
                "tree_id": "duel",
                "cause_role": "secondary",
            },
            {
                "description": "顾霜追问",
                "evidence_paragraph_id": 2,
                "node_id": eid4,
                "parent_node_id": eid2,
                "tree_id": "duel",
                "cause_role": "secondary",
            },
        ],
    )
    snapshot = EventForestRepository(db_session).fetch_snapshot(run_id)
    assert snapshot is not None
    assert len(snapshot.event_trees) == 1
    tree = snapshot.event_trees[0]
    assert tree.root_event_id == eid1
    assert tree.main_chain == [eid1, eid2]
    # 次因分支（secondary 挂在主链事件 2 下）
    assert len(tree.secondary_groups) == 1
    assert tree.secondary_groups[0].target_event_id == eid2
    assert tree.secondary_groups[0].branch == [eid3, eid4]
    nodes = {node.event_id: node for node in snapshot.event_nodes}
    assert nodes[eid1].parent_event_id is None
    assert nodes[eid2].parent_event_id == eid1
    assert nodes[eid3].parent_event_id == eid2
    assert nodes[eid3].evidence_scope == "paragraph"


def test_fetch_snapshot_includes_foreshadowing_edges(db_session) -> None:
    """2026-09-13 用于验证 fetch_snapshot 返回伏笔树视图（伏笔即事件树）"""
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
                "evidence_paragraph_id": 0,
                "isforeshadowing": True,
                "payoff_likelihood": "high",
            },
        ],
    )
    db_session.commit()

    repo = EventForestRepository(db_session)
    snapshot = repo.fetch_snapshot(run_id)
    assert snapshot is not None
    assert len(snapshot.foreshadowing_edges) == 1
    edge = snapshot.foreshadowing_edges[0]
    assert edge.description == "顾霜立誓"
    assert edge.root_event_id == snapshot.event_trees[0].root_event_id
    assert edge.payoff_event_id is None
    assert edge.status == "open"
    assert edge.active is True


def test_same_paragraph_links_follow_formal_event_order_and_reject_reverse(db_session) -> None:
    """同段偏序沿用正式写入序号，连续性不能反向关联"""
    _novel_id, run_id = create_run_with_chunks(db_session, texts=["顾霜入门，随后立誓。"])
    first_id = f"evt-{run_id[:8]}-z"
    second_id = f"evt-{run_id[:8]}-a"
    persist_chapter_annotation(
        db_session, run_id=run_id, chapter_id=1,
        events=[
            {"description": "顾霜入门", "node_id": first_id, "tree_id": "entry", "evidence_paragraph_id": 0},
            {"description": "顾霜立誓", "node_id": second_id, "tree_id": "oath", "evidence_paragraph_id": 0},
        ],
    )
    commit_test_event_link(
        db_session, run_id=run_id, chapter_id=1, source_event_id=first_id, target_event_id=second_id,
    )
    snapshot = EventForestRepository(db_session).fetch_snapshot(run_id)
    assert snapshot is not None
    assert snapshot.derived_event_order == [first_id, second_id]
    assert len(snapshot.causal_edges) == 1
    assert snapshot.event_nodes[0].char_start == snapshot.event_nodes[1].char_start == 0
    with pytest.raises(ValueError, match="文档严格偏序"):
        commit_test_event_link(
            db_session, run_id=run_id, chapter_id=1, source_event_id=second_id, target_event_id=first_id,
        )


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
                "evidence_paragraph_id": 0,
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
                "evidence_paragraph_id": 1,
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
