"""2026-08-20 事件森林时间轴度量单元测试（一树一节点）"""

from __future__ import annotations

import pytest

from src.metrics.event_timeline_metrics import (
    build_event_timeline_plan,
    serialize_event_timeline_node,
)
from src.storage.repositories import ChapterRepository, StatsRepository
from src.storage.repositories.graph.event_forest import EventForestRepository
from tests.support.chapter_annotation_helpers import create_run_with_chunks, persist_chapter_annotation


def _build_forest_three_trees(db_session, *, tension_scores: list[float] | None = None):
    """构造三棵事件树用于验证重要性分级"""
    novel_id, run_id = create_run_with_chunks(
        db_session,
        texts=["章一文本。", "章二文本。", "章三文本。"],
        chapter_ids=[1, 2, 3],
        title="事件时间轴分位数",
    )
    t = run_id[:8]
    persist_chapter_annotation(
        db_session,
        run_id=run_id,
        chapter_id=1,
        events=[
            {
                "description": "事件A根",
                "participants": ["顾霜"],
                "anchor_paragraph_ids": [0],
                "node_id": f"evt-{t}-a-root",
                "tree_id": "tree-A",
                "cause_role": "root",
            },
            {
                "description": "事件A主2",
                "participants": ["顾霜"],
                "anchor_paragraph_ids": [0],
                "node_id": f"evt-{t}-a-main2",
                "parent_node_id": f"evt-{t}-a-root",
                "tree_id": "tree-A",
                "cause_role": "main",
            },
        ],
    )
    persist_chapter_annotation(
        db_session,
        run_id=run_id,
        chapter_id=2,
        events=[
            {
                "description": "事件B根",
                "participants": ["顾霜", "苏映雪"],
                "anchor_paragraph_ids": [0],
                "node_id": f"evt-{t}-b-root",
                "tree_id": "tree-B",
                "cause_role": "root",
            },
            {
                "description": "事件B主2",
                "participants": ["苏映雪"],
                "anchor_paragraph_ids": [0],
                "node_id": f"evt-{t}-b-main2",
                "parent_node_id": f"evt-{t}-b-root",
                "tree_id": "tree-B",
                "cause_role": "main",
            },
            {
                "description": "事件B主3",
                "participants": ["顾霜"],
                "anchor_paragraph_ids": [0],
                "node_id": f"evt-{t}-b-main3",
                "parent_node_id": f"evt-{t}-b-main2",
                "tree_id": "tree-B",
                "cause_role": "main",
            },
            {
                "description": "事件B次1",
                "participants": ["顾霜"],
                "anchor_paragraph_ids": [0],
                "node_id": f"evt-{t}-b-sec1",
                "parent_node_id": f"evt-{t}-b-main2",
                "tree_id": "tree-B",
                "cause_role": "secondary",
            },
        ],
    )
    persist_chapter_annotation(
        db_session,
        run_id=run_id,
        chapter_id=3,
        events=[
            {
                "description": "事件C根",
                "participants": ["顾霜"],
                "anchor_paragraph_ids": [0],
                "tree_id": "tree-C",
                "cause_role": "root",
            },
        ],
    )
    from src.storage.repositories.paragraph_repository import ParagraphCurveRow, ParagraphRepository

    scores = tension_scores or [0.4, 0.9, 0.5]
    rows = [
        ParagraphCurveRow(
            paragraph_id=i,
            pos_density=0.1,
            neg_density=0.02,
            net_density=0.08,
            smoothed_net_density=0.08,
            surface_tension=s,
            smoothed_surface_tension=s,
        )
        for i, s in enumerate(scores)
    ]
    ParagraphRepository(db_session).insert_paragraph_curves(run_id, rows)
    db_session.commit()
    return novel_id, run_id


def test_level_quantile_66_33(db_session) -> None:
    _, run_id = _build_forest_three_trees(db_session)
    chapter_repo = ChapterRepository(db_session)
    stats_repo = StatsRepository(db_session)
    snapshot = EventForestRepository(db_session).fetch_snapshot(run_id)
    assert snapshot is not None
    plan = build_event_timeline_plan(run_id, chapter_repo, stats_repo, snapshot)
    assert len(plan.nodes) == 3
    by_tree = {n.tree_id: n for n in plan.nodes}
    assert by_tree["tree-B"].level == 1
    assert by_tree["tree-B"].level <= by_tree["tree-C"].level <= by_tree["tree-A"].level
    for node in plan.nodes:
        assert node.level in (1, 2, 3)


def test_level_all_equal_only_max_is_1(db_session) -> None:
    """全相等时仅 max 为 1 其余 2"""
    novel_id, run_id = create_run_with_chunks(
        db_session,
        texts=["章一", "章二", "章三"],
        chapter_ids=[1, 2, 3],
        title="等分",
    )
    for cid, tid in [(1, "eq-A"), (2, "eq-B"), (3, "eq-C")]:
        persist_chapter_annotation(
            db_session,
            run_id=run_id,
            chapter_id=cid,
            events=[
                {
                    "description": f"事件{tid}",
                    "participants": ["顾霜"],
                    "anchor_paragraph_ids": [0],
                    "tree_id": tid,
                    "cause_role": "root",
                },
            ],
        )
    from src.storage.repositories.paragraph_repository import ParagraphCurveRow, ParagraphRepository

    ParagraphRepository(db_session).insert_paragraph_curves(
        run_id,
        [
            ParagraphCurveRow(0, 0.1, 0.02, 0.08, 0.08, 0.5, 0.5),
            ParagraphCurveRow(1, 0.1, 0.02, 0.08, 0.08, 0.5, 0.5),
            ParagraphCurveRow(2, 0.1, 0.02, 0.08, 0.08, 0.5, 0.5),
        ],
    )
    db_session.commit()
    snapshot = EventForestRepository(db_session).fetch_snapshot(run_id)
    assert snapshot is not None
    plan = build_event_timeline_plan(run_id, ChapterRepository(db_session), StatsRepository(db_session), snapshot)
    assert len(plan.nodes) == 3
    levels = [n.level for n in plan.nodes]
    assert levels.count(1) == 1, f"全相等时仅 max 为1其余为2，实际 levels={levels}"
    assert levels.count(2) == 2


def test_progress_calculation(db_session) -> None:
    _, run_id = _build_forest_three_trees(db_session)
    snapshot = EventForestRepository(db_session).fetch_snapshot(run_id)
    plan = build_event_timeline_plan(run_id, ChapterRepository(db_session), StatsRepository(db_session), snapshot)
    by_tree = {n.tree_id: n for n in plan.nodes}
    assert by_tree["tree-A"].progress == pytest.approx(1 / 3)
    assert by_tree["tree-B"].progress == pytest.approx(2 / 3)
    assert by_tree["tree-C"].progress == pytest.approx(3 / 3)
    for node in plan.nodes:
        assert 0 <= node.start_progress <= node.end_progress <= 1
        assert node.start_chapter_id <= node.end_chapter_id


def test_phase_mapping(db_session) -> None:
    _, run_id = _build_forest_three_trees(db_session)
    snapshot = EventForestRepository(db_session).fetch_snapshot(run_id)
    plan = build_event_timeline_plan(run_id, ChapterRepository(db_session), StatsRepository(db_session), snapshot)
    phase_names = {p.name for p in plan.phases}
    for node in plan.nodes:
        assert node.phase_name in phase_names
    assert plan.total_chapters == 3


def test_importance_score_formula(db_session) -> None:
    _, run_id = _build_forest_three_trees(db_session)
    snapshot = EventForestRepository(db_session).fetch_snapshot(run_id)
    plan = build_event_timeline_plan(run_id, ChapterRepository(db_session), StatsRepository(db_session), snapshot)
    by_tree = {n.tree_id: n for n in plan.nodes}
    assert by_tree["tree-B"].importance_score > by_tree["tree-C"].importance_score
    assert by_tree["tree-C"].importance_score > by_tree["tree-A"].importance_score
    for node in plan.nodes:
        payload = serialize_event_timeline_node(node)
        assert isinstance(payload["participants"], list)
        assert payload["node_type"] == "event"
        assert "tree_id" in payload
        assert "main_chain" in payload


def test_empty_snapshot_returns_no_nodes_but_phases(db_session) -> None:
    _, run_id = create_run_with_chunks(db_session, texts=["章一"], chapter_ids=[1], title="空")
    from src.storage.repositories.paragraph_repository import ParagraphCurveRow, ParagraphRepository

    ParagraphRepository(db_session).insert_paragraph_curves(
        run_id,
        [ParagraphCurveRow(0, 0.1, 0.02, 0.08, 0.08, 0.6, 0.6)],
    )
    db_session.commit()
    snapshot = EventForestRepository(db_session).fetch_snapshot(run_id)
    assert snapshot is None
    plan = build_event_timeline_plan(
        run_id,
        ChapterRepository(db_session),
        StatsRepository(db_session),
        snapshot,
    )
    assert plan.nodes == []
    assert plan.total_chapters == 1
    assert len(plan.phases) >= 1
