"""GET /{novel_id}/event-forest 端点测试（事件森林/DAG 过程层 API）

覆盖：
- 200 全量快照：事件节点、contains/causal 边、伏笔边（线程即边）、章节根与可见边界、确定性 event_id
- chapter_id 按章边界截断
- 422 chapter_id 与 graph_version_id 同时提供
- 404 无匹配章节图版本
- 409 旧合同 run（analysis_contract_version=NULL）要求重新分析
- 400 非 completed run
"""

from __future__ import annotations

from uuid import NAMESPACE_URL, uuid5

from fastapi.testclient import TestClient
from sqlalchemy import text

from src.agents.annotation.schema import BoundForeshadowing
from src.storage.repositories import ForeshadowingRepository, RunRepository
from tests.support.chapter_annotation_helpers import (
    create_run_with_chunks,
    persist_chapter_annotation,
)


def _event_id(run_id: str, chapter_id: int, ordinal: int) -> str:
    """2026-08-18 与生产侧 _event_id 保持一致的确定性事件 ID"""
    return str(uuid5(NAMESPACE_URL, f"noveliq:event:{run_id}:{chapter_id}:{ordinal}"))


def _insert_event_forest_run(db_session) -> tuple[str, str]:
    """两章三事件：章 1 双事件（含因果边）+ 伏笔绑定章 1 事件 1；章 2 单事件。"""
    novel_id, run_id = create_run_with_chunks(
        db_session,
        texts=["顾霜进入山门。\n顾霜立誓。", "顾霜拔剑。"],
        chapter_ids=[1, 2],
        title="事件森林端点",
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
                "tree_id": "gate",
                "cause_role": "root",
            },
            {
                "description": "顾霜立誓",
                "participants": ["顾霜"],
                "anchor_paragraph_ids": [1],
                "causal_event_refs": [_event_id(run_id, 1, 1)],
                "tree_id": "gate",
                "cause_role": "main",
            },
        ],
    )
    # 伏笔线程由 ForeshadowingRepository.sync 落库（持久化 helper 不代步）
    ForeshadowingRepository(db_session).sync(
        run_id=run_id,
        chapter_id=1,
        foreshadowing=BoundForeshadowing(
            description="顾霜承诺护佑山门",
            confidence="high",
            setup_event_index=1,
        ),
        setup_event_id=_event_id(run_id, 1, 1),
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
    RunRepository(db_session).update_run_status(run_id, "completed")
    db_session.commit()
    return novel_id, run_id


def test_event_forest_returns_full_snapshot(api_client: TestClient, db_session) -> None:
    """2026-08-19 用于验证事件森林快照的树视图、因果边、伏笔边与可见边界（契约 v3）"""
    novel_id, run_id = _insert_event_forest_run(db_session)

    response = api_client.get(
        f"/api/novels/{novel_id}/event-forest",
        params={"task_id": run_id[:8]},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["chapter_order"] == 2
    assert payload["visible_through_chapter_order"] == 2
    assert payload["graph_version_id"]

    nodes = {node["event_id"]: node for node in payload["event_nodes"]}
    assert set(nodes) == {
        _event_id(run_id, 1, 1),
        _event_id(run_id, 1, 2),
        _event_id(run_id, 2, 1),
    }
    assert nodes[_event_id(run_id, 1, 1)]["description"] == "顾霜进入山门"
    assert nodes[_event_id(run_id, 1, 2)]["description"] == "顾霜立誓"
    assert nodes[_event_id(run_id, 2, 1)]["description"] == "顾霜拔剑"
    assert nodes[_event_id(run_id, 1, 1)]["anchor_paragraph_ids"] == [0]
    assert nodes[_event_id(run_id, 1, 1)]["tree_id"] == "gate"
    assert nodes[_event_id(run_id, 1, 1)]["cause_role"] == "root"

    # 树视图：章 1 双事件一棵树（主链），章 2 单事件一棵树；contains 派生化不再返回
    assert "event_edges" not in payload
    assert "chapter_roots" not in payload
    trees = {tree["tree_id"]: tree for tree in payload["event_trees"]}
    assert set(trees) == {"gate", "tree-main"}
    gate = trees["gate"]
    assert gate["root_event_id"] == _event_id(run_id, 1, 1)
    assert gate["main_chain"] == [_event_id(run_id, 1, 1), _event_id(run_id, 1, 2)]
    assert gate["chapter_ids"] == [1]

    causal_edges = payload["causal_edges"]
    assert len(causal_edges) == 1
    assert all(edge["edge_type"] == "causal" for edge in causal_edges)
    assert causal_edges[0]["source_event_id"] == _event_id(run_id, 1, 1)
    assert causal_edges[0]["target_event_id"] == _event_id(run_id, 1, 2)
    assert causal_edges[0]["source_event_revision"] is not None
    assert causal_edges[0]["is_active"] is True

    assert len(payload["foreshadowing_edges"]) == 1
    foreshadowing = payload["foreshadowing_edges"][0]
    assert foreshadowing["setup_event_id"] == _event_id(run_id, 1, 1)
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


def test_event_forest_returns_404_without_matching_graph_version(api_client: TestClient, db_session) -> None:
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
    assert response.json()["detail"] == "当前 run 尚无匹配的章节图版本"


def test_event_forest_rejects_both_filters(api_client: TestClient, db_session) -> None:
    """2026-08-18 用于验证同时提供 chapter_id 与 graph_version_id 返回 422"""
    novel_id, run_id = _insert_event_forest_run(db_session)

    response = api_client.get(
        f"/api/novels/{novel_id}/event-forest",
        params={
            "task_id": run_id[:8],
            "chapter_id": 1,
            "graph_version_id": "graph-version-1",
        },
    )

    assert response.status_code == 422


def test_event_forest_requires_paragraph_contract(api_client: TestClient, db_session) -> None:
    """2026-08-18 用于验证旧合同 run（analysis_contract_version=NULL）被 409 拒绝"""
    novel_id, run_id = _insert_event_forest_run(db_session)
    db_session.execute(
        text(
            "UPDATE analysis_runs SET analysis_contract_version = NULL "
            "WHERE run_id = :run_id"
        ),
        {"run_id": run_id},
    )
    db_session.commit()

    response = api_client.get(
        f"/api/novels/{novel_id}/event-forest",
        params={"task_id": run_id[:8]},
    )

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "paragraph_contract_rerun_required"


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