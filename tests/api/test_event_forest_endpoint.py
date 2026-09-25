"""GET /{novel_id}/event-forest 端点测试（事件森林/DAG 过程层 API）

覆盖：
- 200 全量快照：事件节点、causal 边、伏笔树（伏笔即事件树）、章节根与可见边界、确定性 event_id
- chapter_id 按章边界截断
- 404 无匹配章节图数据
- 400 非 completed run
"""

from __future__ import annotations

from uuid import NAMESPACE_URL, uuid5

from fastapi.testclient import TestClient

from src.storage.models import EventEdge, EventNode
from src.storage.repositories import RunRepository
from tests.support.chapter_annotation_helpers import (
    create_run_with_chunks,
    persist_chapter_annotation,
)


def _insert_event_forest_run(db_session) -> tuple[str, str]:
    """两章三事件：章 1 双事件（遗留因果边连向章 2）+ 伏笔绑定章 1 事件 1；章 2 单事件。

    节点 id 按 run 前缀派生：event_id 为全局主键，避免跨测试数据残留冲突。
    2026-09-14 跨章因果链退役：write 面不再产生 causal 边（expected_payoff_family
    同步退役），但 EventEdge 表与快照读侧字段保留读旧数据，端点断言按读侧现行为
    以遗留边数据构造跨章因果边。
    """
    novel_id, run_id = create_run_with_chunks(
        db_session,
        texts=["顾霜进入山门。\n顾霜立誓。", "顾霜拔剑。"],
        chapter_ids=[1, 2],
        title="事件森林端点",
    )
    t = run_id[:8]
    gate_root = f"evt-{t}-gate-root"
    gate_main = f"evt-{t}-gate-main"
    sword_root = f"evt-{t}-sword-root"
    persist_chapter_annotation(
        db_session,
        run_id=run_id,
        chapter_id=1,
        events=[
            {
                "description": "顾霜进入山门",
                "participants": ["顾霜"],
                "anchor_paragraph_ids": [0],
                "node_id": gate_root,
                "tree_id": "gate",
                "cause_role": "root",
                # 2026-09-13 伏笔即事件树：该事件即伏笔树根
                # （2026-09-14 伏笔属性收敛：只剩 payoff_likelihood 三档）
                "isforeshadowing": True,
                "payoff_likelihood": "high",
            },
            {
                "description": "顾霜立誓",
                "participants": ["顾霜"],
                "anchor_paragraph_ids": [1],
                "node_id": gate_main,
                "parent_node_id": gate_root,
                "tree_id": "gate",
                "cause_role": "main",
            },
        ],
    )
    sword_annotation_id = persist_chapter_annotation(
        db_session,
        run_id=run_id,
        chapter_id=2,
        events=[
            {
                "description": "顾霜拔剑",
                "participants": ["顾霜"],
                "anchor_paragraph_ids": [0],
                "node_id": sword_root,
                "tree_id": "sword",
                "cause_role": "root",
            },
        ],
    )
    # 读侧现行为：跨章因果唯一出口是 causal EventEdge 行（遗留数据仍可读出，
    # edge_id 派生公式与生产写面退役前一致；evidence 取因果源节点的章级盖章）
    gate_root_node = db_session.get(EventNode, gate_root)
    assert gate_root_node is not None
    db_session.add(
        EventEdge(
            edge_id=str(uuid5(NAMESPACE_URL, f"noveliq:event-edge:{run_id}:causal:{gate_root}:{sword_root}")),
            run_id=run_id,
            edge_type="causal",
            source_event_id=gate_root,
            target_event_id=sword_root,
            source_chapter_id=1,
            target_chapter_id=2,
            is_active=True,
            evidence=list(gate_root_node.evidence),
            annotation_id=sword_annotation_id,
            payload_path=f"legacy/causal/{sword_root}",
        )
    )
    RunRepository(db_session).update_run_status(run_id, "completed")
    db_session.commit()
    return novel_id, run_id


def test_event_forest_returns_full_snapshot(api_client: TestClient, db_session) -> None:
    """2026-08-19 用于验证事件森林快照的树视图、因果边、伏笔边与可见边界

    2026-08-22节点 id 由测试显式指定（服务端 uuid4 的可预测替身）。
    """
    novel_id, run_id = _insert_event_forest_run(db_session)
    t = run_id[:8]
    gate_root = f"evt-{t}-gate-root"
    gate_main = f"evt-{t}-gate-main"
    sword_root = f"evt-{t}-sword-root"

    response = api_client.get(
        f"/api/novels/{novel_id}/event-forest",
        params={"task_id": run_id[:8]},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["chapter_id"] == 2
    assert payload["chapter_order"] == 2
    assert payload["visible_through_chapter_order"] == 2

    nodes = {node["event_id"]: node for node in payload["event_nodes"]}
    assert set(nodes) == {gate_root, gate_main, sword_root}
    assert nodes[gate_root]["description"] == "顾霜进入山门"
    assert nodes[gate_main]["description"] == "顾霜立誓"
    assert nodes[sword_root]["description"] == "顾霜拔剑"
    assert nodes[gate_root]["anchor_paragraph_ids"] == [0, 1]
    assert nodes[gate_root]["tree_id"] == "gate"
    assert nodes[gate_root]["cause_role"] == "root"

    # 树视图：章 1 双事件一棵树（主链），章 2 单事件一棵树；contains 派生化不再返回
    assert "event_edges" not in payload
    assert "chapter_roots" not in payload
    trees = {tree["tree_id"]: tree for tree in payload["event_trees"]}
    assert set(trees) == {"gate", "sword"}
    gate = trees["gate"]
    assert gate["root_event_id"] == gate_root
    assert gate["main_chain"] == [gate_root, gate_main]
    assert gate["chapter_ids"] == [1]

    causal_edges = payload["causal_edges"]
    assert len(causal_edges) == 1
    assert all(edge["edge_type"] == "causal" for edge in causal_edges)
    assert causal_edges[0]["source_event_id"] == gate_root
    assert causal_edges[0]["target_event_id"] == sword_root
    assert causal_edges[0]["source_chapter_id"] == 1
    assert causal_edges[0]["target_chapter_id"] == 2
    assert causal_edges[0]["is_active"] is True

    assert len(payload["foreshadowing_edges"]) == 1
    foreshadowing = payload["foreshadowing_edges"][0]
    assert foreshadowing["root_event_id"] == gate_root
    assert foreshadowing["payoff_event_id"] is None
    assert foreshadowing["status"] == "open"
    assert foreshadowing["active"] is True

    assert sorted(payload["derived_event_order"]) == sorted(nodes)


def test_event_forest_filters_by_chapter_boundary(api_client: TestClient, db_session) -> None:
    """2026-08-18 用于验证 chapter_id 按章边界截断事件节点"""
    novel_id, run_id = _insert_event_forest_run(db_session)

    response = api_client.get(
        f"/api/novels/{novel_id}/event-forest",
        params={"task_id": run_id[:8], "chapter_id": 1},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["visible_through_chapter_order"] == 1
    assert {node["description"] for node in payload["event_nodes"]} == {
        "顾霜进入山门",
        "顾霜立誓",
    }
    assert all(node["chapter_id"] == 1 for node in payload["event_nodes"])


def test_event_forest_returns_404_without_matching_chapter_data(api_client: TestClient, db_session) -> None:
    """2026-08-18 用于验证无任何章节标注的 run 返回 404"""
    novel_id, run_id = create_run_with_chunks(
        db_session,
        texts=["未标注原文。"],
        title="无事件森林",
    )
    RunRepository(db_session).update_run_status(run_id, "completed")
    db_session.commit()

    response = api_client.get(
        f"/api/novels/{novel_id}/event-forest",
        params={"task_id": run_id[:8]},
    )

    assert response.status_code == 404
    assert response.json()["detail"] == "当前 run 尚无匹配的章节图数据"


def test_event_forest_rejects_non_completed_run(api_client: TestClient, db_session) -> None:
    """2026-08-18 用于验证未完成 run 被 400 拒绝"""
    novel_id, run_id = _insert_event_forest_run(db_session)
    RunRepository(db_session).update_run_status(run_id, "pending")
    db_session.commit()

    response = api_client.get(
        f"/api/novels/{novel_id}/event-forest",
        params={"task_id": run_id[:8]},
    )

    assert response.status_code == 400
    assert response.json()["error_type"] == "AnalysisNotCompleteError"
