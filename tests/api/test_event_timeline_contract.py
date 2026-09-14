"""2026-08-20 事件森林时间轴契约测试（一树一节点）- 重构版"""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi.testclient import TestClient
from sqlalchemy import select

from src.storage.models import EventEdge
from src.storage.repositories import RunRepository
from tests.support.chapter_annotation_helpers import create_run_with_chunks, persist_chapter_annotation


def _insert_two_chapter_forest(db_session):
    novel_id, run_id = create_run_with_chunks(
        db_session,
        texts=["顾霜进入山门。\n顾霜立誓。", "顾霜拔剑。\n顾霜归来。"],
        chapter_ids=[1, 2],
        title="事件森林契约",
    )
    t = run_id[:8]
    # chapter 1: two events in same tree gate
    persist_chapter_annotation(
        db_session,
        run_id=run_id,
        chapter_id=1,
        events=[
            {
                "description": "顾霜进入山门",
                "participants": ["顾霜"],
                "anchor_paragraph_ids": [0],
                "node_id": f"evt-{t}-gate-root",
                "tree_id": "gate",
                "cause_role": "root",
            },
            {
                "description": "顾霜立誓",
                "participants": ["顾霜", "苏映雪"],
                "anchor_paragraph_ids": [1],
                "node_id": f"evt-{t}-gate-main",
                "parent_node_id": f"evt-{t}-gate-root",
                "tree_id": "gate",
                "cause_role": "main",
            },
        ],
    )
    # chapter 2: another tree
    persist_chapter_annotation(
        db_session,
        run_id=run_id,
        chapter_id=2,
        events=[
            {
                "description": "顾霜拔剑",
                "participants": ["顾霜"],
                "anchor_paragraph_ids": [0],
                "node_id": f"evt-{t}-sword-root",
                "causal_event_refs": [f"evt-{t}-gate-main", f"evt-{t}-gate-root"],
                "tree_id": "sword",
                "cause_role": "root",
            },
            {
                "description": "顾霜归来",
                "participants": ["顾霜"],
                "anchor_paragraph_ids": [1],
                "node_id": f"evt-{t}-sword-main",
                "parent_node_id": f"evt-{t}-sword-root",
                "tree_id": "sword",
                "cause_role": "main",
            },
        ],
    )
    # Insert paragraph tension curves for include_curve check (5 -> but we have 2 chapters, so 2 scores)
    from src.storage.repositories.paragraph_repository import ParagraphCurveRow, ParagraphRepository

    ParagraphRepository(db_session).insert_paragraph_curves(
        run_id,
        [
            ParagraphCurveRow(
                paragraph_id=0,
                pos_density=0.1,
                neg_density=0.02,
                net_density=0.08,
                smoothed_net_density=0.08,
                surface_tension=0.6,
                smoothed_surface_tension=0.6,
            ),
            ParagraphCurveRow(
                paragraph_id=1,
                pos_density=0.03,
                neg_density=0.22,
                net_density=-0.19,
                smoothed_net_density=-0.17,
                surface_tension=0.9,
                smoothed_surface_tension=0.9,
            ),
        ],
    )
    RunRepository(db_session).update_run_status(run_id, "completed")
    db_session.commit()
    return novel_id, run_id


def test_snapshot_none_returns_200_empty(api_client: TestClient, db_session) -> None:
    """snapshot is None → 200 空结构，total_chapters 0，tension None，header 可选"""
    novel_id, run_id = create_run_with_chunks(
        db_session,
        texts=["未标注原文。"],
        title="空快照",
    )
    RunRepository(db_session).update_run_status(run_id, "completed")
    db_session.commit()
    task_id = run_id[:8]
    response = api_client.get(
        f"/api/novels/{novel_id}/timeline",
        params={"task_id": task_id, "include_curve": "false"},
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["total_chapters"] == 0
    assert payload["meta"]["total_chapters"] == 0
    assert payload["nodes"] == []
    assert payload["phases"] == []
    assert payload["causal_edges"] == []
    assert payload["foreshadowing_edges"] == []
    assert payload["derived_event_order"] == []
    assert payload["tension_curve"] is None
    # optional header
    assert response.headers.get("X-Timeline-Empty-Reason") in (None, "no_event_forest")


def test_returns_nodes_sorted_by_derived_order(api_client: TestClient, db_session) -> None:
    """有森林返回 nodes 按 derivedOrder 排序"""
    novel_id, run_id = _insert_two_chapter_forest(db_session)
    task_id = run_id[:8]
    response = api_client.get(
        f"/api/novels/{novel_id}/timeline",
        params={"task_id": task_id, "include_curve": "true"},
    )
    assert response.status_code == 200
    payload = response.json()
    assert len(payload["nodes"]) == 2  # two trees
    assert payload["total_chapters"] == 2
    assert len(payload["derived_event_order"]) == 4
    # nodes should be sorted by progress / anchor_order / tree_id
    nodes = payload["nodes"]
    progresses = [n["progress"] for n in nodes]
    assert progresses == sorted(progresses)
    # derived order first two belong to gate tree, ordering preserved
    derived = payload["derived_event_order"]
    t = run_id[:8]
    # check that gate root is before sword root in derived order (chapter order)
    assert derived.index(f"evt-{t}-gate-root") < derived.index(f"evt-{t}-sword-root")
    # also ensure nodes' tree_id respects derived order: gate before sword
    assert nodes[0]["tree_id"] == "gate"
    assert nodes[1]["tree_id"] == "sword"


def test_include_curve_false_tension_none(api_client: TestClient, db_session) -> None:
    """include_curve=false 时 tension_curve 为 None"""
    novel_id, run_id = _insert_two_chapter_forest(db_session)
    task_id = run_id[:8]
    with_curve = api_client.get(
        f"/api/novels/{novel_id}/timeline",
        params={"task_id": task_id, "include_curve": "true"},
    )
    without_curve = api_client.get(
        f"/api/novels/{novel_id}/timeline",
        params={"task_id": task_id, "include_curve": "false"},
    )
    assert with_curve.status_code == 200
    assert without_curve.status_code == 200
    assert without_curve.json().get("tension_curve") is None
    # with_curve may have tension_curve list (length == total_chapters)
    tension = with_curve.json().get("tension_curve")
    if tension is not None:
        assert isinstance(tension, list)
        assert len(tension) == 2
    # nodes保持一致
    assert without_curve.json().get("nodes") == with_curve.json().get("nodes")
    assert without_curve.json().get("causal_edges") == with_curve.json().get("causal_edges")


def test_participants_keep_dict(api_client: TestClient, db_session) -> None:
    """participants 保持 dict 结构，不压平"""
    novel_id, run_id = _insert_two_chapter_forest(db_session)
    task_id = run_id[:8]
    response = api_client.get(
        f"/api/novels/{novel_id}/timeline",
        params={"task_id": task_id},
    )
    assert response.status_code == 200
    payload = response.json()
    for node in payload["nodes"]:
        assert "participants" in node
        assert "character_names" in node
        assert isinstance(node["participants"], list)
        assert isinstance(node["character_names"], list)
        if node["participants"]:
            assert isinstance(node["participants"][0], dict)
            p0 = node["participants"][0]
            has_name = "name" in p0 or "entity" in p0
            assert has_name
            if "name" not in p0 and "entity" in p0:
                assert "name" in p0["entity"]
        assert all(isinstance(c, str) for c in node["character_names"])
        assert node.get("node_type") == "event"


def test_causal_edges_include_inactive_and_expired_at(api_client: TestClient, db_session) -> None:
    """causal_edges 含 inactive/expired_at，前端灰显全量

    2026-09-14 跨章因果链退役：写面不再产生 causal 边（旧版经 causal_event_refs
    派生），但 EventEdge 表与时间轴读侧保留读旧数据。这里按读侧现行为以遗留
    数据直接构造两条跨章 causal 边（gate-main→sword-root 活性、
    gate-root→sword-root 置 inactive 且含 expired_at），断言不变。
    """
    from uuid import NAMESPACE_URL, uuid5

    from src.storage.models import ChapterAnnotationRecord, EventNode

    novel_id, run_id = _insert_two_chapter_forest(db_session)
    t = run_id[:8]
    gate_root = f"evt-{t}-gate-root"
    gate_main = f"evt-{t}-gate-main"
    sword_root = f"evt-{t}-sword-root"
    annotation_id = str(
        db_session.execute(
            select(ChapterAnnotationRecord.annotation_id).where(ChapterAnnotationRecord.run_id == run_id).limit(1)
        ).scalar_one()
    )
    gate_main_node = db_session.get(EventNode, gate_main)
    gate_root_node = db_session.get(EventNode, gate_root)
    assert gate_main_node is not None and gate_root_node is not None
    db_session.add_all(
        [
            EventEdge(
                edge_id=str(uuid5(NAMESPACE_URL, f"noveliq:event-edge:{run_id}:causal:{gate_main}:{sword_root}")),
                run_id=run_id,
                edge_type="causal",
                source_event_id=gate_main,
                target_event_id=sword_root,
                source_chapter_id=1,
                target_chapter_id=2,
                is_active=True,
                evidence=list(gate_main_node.evidence),
                annotation_id=annotation_id,
                payload_path=f"legacy/causal/{sword_root}-main",
            ),
            EventEdge(
                edge_id=str(uuid5(NAMESPACE_URL, f"noveliq:event-edge:{run_id}:causal:{gate_root}:{sword_root}")),
                run_id=run_id,
                edge_type="causal",
                source_event_id=gate_root,
                target_event_id=sword_root,
                source_chapter_id=1,
                target_chapter_id=2,
                is_active=False,
                evidence=list(gate_root_node.evidence),
                annotation_id=annotation_id,
                payload_path=f"legacy/causal/{sword_root}-root",
                expired_at=datetime.now(UTC),
            ),
        ]
    )
    db_session.commit()

    task_id = run_id[:8]
    response = api_client.get(
        f"/api/novels/{novel_id}/timeline",
        params={"task_id": task_id},
    )
    assert response.status_code == 200
    payload = response.json()
    edges = payload["causal_edges"]
    assert len(edges) >= 2  # forest causal edges（含已置 inactive 的那条）
    # Should contain inactive entry
    inactive = [e for e in edges if e["is_active"] is False]
    assert len(inactive) >= 1
    for edge in edges:
        assert "edge_id" in edge
        assert "source_event_id" in edge
        assert "target_event_id" in edge
        assert "is_active" in edge
        assert "expired_at" in edge
        # expired_at nullable
        assert edge["expired_at"] is None or isinstance(edge["expired_at"], str)
    # Verify inactive edge's expired_at not None
    assert any(e["expired_at"] is not None for e in inactive)


def test_analysis_not_complete_returns_400(api_client: TestClient, db_session) -> None:
    """AnalysisNotComplete 仍返回 400"""
    novel_id, run_id = _insert_two_chapter_forest(db_session)
    # revert to pending
    RunRepository(db_session).update_run_status(run_id, "pending")
    db_session.commit()
    task_id = run_id[:8]
    response = api_client.get(
        f"/api/novels/{novel_id}/timeline",
        params={"task_id": task_id},
    )
    assert response.status_code == 400
    # error shape may be {"error_type": ...} or detail
    body = response.json()
    assert body.get("error_type") == "AnalysisNotCompleteError" or "尚未完成" in str(body)


def test_empty_forest_still_returns_phases_and_edges(api_client: TestClient, db_session) -> None:
    """验证快照存在时阶段和边仍会返回"""
    novel_id, run_id = _insert_two_chapter_forest(db_session)
    task_id = run_id[:8]
    response = api_client.get(
        f"/api/novels/{novel_id}/timeline",
        params={"task_id": task_id, "include_curve": "false"},
    )
    assert response.status_code == 200
    payload = response.json()
    assert isinstance(payload["phases"], list)
    assert len(payload["phases"]) >= 1
    assert payload["phase_basis"] in ("tension", "fixed_percentage")
    # still returns derived_event_order even when nodes empty would, but here nodes non-empty
    assert isinstance(payload["derived_event_order"], list)


def test_total_chapters_and_phase_mapping(api_client: TestClient, db_session) -> None:
    novel_id, run_id = _insert_two_chapter_forest(db_session)
    task_id = run_id[:8]
    response = api_client.get(
        f"/api/novels/{novel_id}/timeline",
        params={"task_id": task_id},
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["total_chapters"] == payload["meta"]["total_chapters"] == 2
    # phase_name mapped per node anchor_chapter_order
    phase_names = {p["name"] for p in payload["phases"]}
    for node in payload["nodes"]:
        assert node["phase_name"] in phase_names
        assert 0 <= node["progress"] <= 1
        assert node["start_chapter_id"] <= node["end_chapter_id"]
