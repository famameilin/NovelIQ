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


def test_fetch_snapshot_returns_event_nodes_and_causal_edges(db_session) -> None:
    """2026-08-18 用于验证持久化后 fetch_snapshot 返回事件节点和因果边"""
    text = "顾霜进入山门。\n顾霜拔剑。"
    _novel_id, run_id = create_run_with_chunks(
        db_session,
        texts=[text],
        title="事件森林快照",
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
            {
                "description": "顾霜拔剑",
                "participants": ["顾霜"],
                "anchor_paragraph_ids": [1],
                "causal_event_refs": [1],
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

    eid1 = str(uuid5(NAMESPACE_URL, f"noveliq:event:{run_id}:1:1"))
    eid2 = str(uuid5(NAMESPACE_URL, f"noveliq:event:{run_id}:1:2"))
    assert nodes_by_desc["顾霜进入山门"].event_id == eid1
    assert nodes_by_desc["顾霜拔剑"].event_id == eid2

    causal_edges = [e for e in snapshot.event_edges if e.edge_type == "causal"]
    assert len(causal_edges) == 1
    assert causal_edges[0].source_event_id == eid1
    assert causal_edges[0].target_event_id == eid2
    assert causal_edges[0].is_active is True


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
            setup_event_index=1,
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
