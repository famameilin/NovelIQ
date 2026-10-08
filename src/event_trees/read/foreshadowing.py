"""本领域的独立只读投影，不返回 HTTP 模型"""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from src.storage.models import (
    EventEdge,
    EventNode,
)
from src.storage.repositories.annotation.repository import AnnotationRepository
from src.storage.repositories.annotation.rows import (
    ForeshadowingTreeView,
)

_EXPECTATION_BASE_SCORE_BY_PAYOFF = {"high": 0.62, "medium": 0.38, "low": 0.14}
_EXPECTATION_STATUS_BONUS = {"open": -0.07, "reinforced": 0.03, "likely_paid_off": 0.28}
_EXPECTATION_STRENGTH_BONUS = {"high": 0.03, "medium": 0.0, "low": -0.05}
_EXPECTATION_STATUS_WEIGHT = {"open": 0.75, "reinforced": 1.0, "likely_paid_off": 1.2}
_EXPECTATION_STRENGTH_WEIGHT = {"high": 0.05, "medium": 0.0, "low": -0.05}


def foreshadowing_by_chapter(session: Session, run_id: str) -> dict[int, dict[str, Any]]:
    """2026-09-13 用于把伏笔树（根事件 + foreshadowing 挂边）展开到实际命中章节

    埋设章 linked 为 None（该章就是根所在）；后续挂边章 linked 指向树根事件 id。
    """
    roots = AnnotationRepository(session).fetch_foreshadowing_roots(run_id)
    if not roots:
        return {}
    root_by_id = {root.event_id: root for root in roots}
    sequence_map = AnnotationRepository(session).fetch_chapter_sequence_map(run_id)

    def _entry(root: EventNode, *, linked: str | None) -> dict[str, Any]:
        return {
            "has_foreshadowing": True,
            "is_strong_setup": (root.strength == "high") if root.strength is not None else None,
            "foreshadowing_desc": root.description,
            "why_unresolved_now": None,
            "payoff_likelihood": root.payoff_likelihood,
            "foreshadowing_root_event_id": linked,
        }

    by_chapter: dict[int, dict[str, Any]] = {}
    for root in sorted(roots, key=lambda r: (sequence_map.get(r.chapter_id, r.chapter_id), r.event_id)):
        by_chapter[root.chapter_id] = _entry(root, linked=None)
    edges = AnnotationRepository(session).fetch_foreshadowing_edges(run_id)
    for edge in sorted(
        edges,
        key=lambda e: (sequence_map.get(e.target_chapter_id, e.target_chapter_id), e.edge_id),
    ):
        root_node = root_by_id.get(edge.source_event_id)
        if root_node is None:
            continue
        by_chapter[edge.target_chapter_id] = _entry(root_node, linked=root_node.event_id)
    return by_chapter


def fetch_foreshadowing_trees(session: Session, run_id: str) -> list[ForeshadowingTreeView]:
    """2026-09-13 用于汇总伏笔树（根事件属性 + 全部挂边章节与事件）"""
    sequence_map = AnnotationRepository(session).fetch_chapter_sequence_map(run_id)
    roots = AnnotationRepository(session).fetch_foreshadowing_roots(run_id, ordered=True)
    if not roots:
        return []
    edges_by_root: dict[str, list[EventEdge]] = {}
    targets_by_id: dict[str, EventNode] = {}
    all_edges = AnnotationRepository(session).fetch_foreshadowing_edges(run_id, ordered=True)
    for edge in all_edges:
        edges_by_root.setdefault(edge.source_event_id, []).append(edge)
    target_ids = {edge.target_event_id for edge in all_edges}
    if target_ids:
        for node in AnnotationRepository(session).fetch_event_records(run_id, target_ids):
            targets_by_id[node.event_id] = node
    views: list[ForeshadowingTreeView] = []
    for root in roots:
        edges = edges_by_root.get(root.event_id, [])
        anchor_chapter_ids = sorted(
            {root.chapter_id, *(edge.target_chapter_id for edge in edges)},
            key=lambda chapter_id: (sequence_map.get(chapter_id, chapter_id), chapter_id),
        )
        last_chapter_id = anchor_chapter_ids[-1] if anchor_chapter_ids else root.chapter_id
        latest_edge = edges[-1] if edges else None
        latest_node = targets_by_id.get(latest_edge.target_event_id) if latest_edge else None
        status = root.foreshadowing_status or "open"
        views.append(
            ForeshadowingTreeView(
                root_event_id=root.event_id,
                tree_id=root.tree_id,
                first_chapter_id=root.chapter_id,
                last_chapter_id=last_chapter_id,
                anchor_chapter_ids=anchor_chapter_ids,
                description=root.description,
                payoff_likelihood=root.payoff_likelihood,
                strength=root.strength,
                status=status,
                active=status != "likely_paid_off",
                latest_reason=latest_node.description if latest_node is not None else None,
                latest_why_unresolved_now=None,
            )
        )
    return views


def calculate_foreshadow_expectation(session: Session, run_id: str) -> float | None:
    """2026-09-13 用于按伏笔树根生命周期属性计算回收预期（权重口径不变）"""
    roots = AnnotationRepository(session).fetch_foreshadowing_roots(run_id)
    if not roots:
        return None
    edge_counts = AnnotationRepository(session).fetch_foreshadowing_edge_counts(run_id)
    weighted_total = 0.0
    total_weight = 0.0
    has_evidence = False
    for root in roots:
        # 挂边数 + 埋设本体记 1（旧 hit_count 口径：埋设也是一条命中）
        hit_count = 1 + edge_counts.get(root.event_id, 0)
        # 2026-08-16 P3：字段为 None 时不冒充 LLM 判断；若全树都无
        # payoff_likelihood/strength 证据，说明上游输入退化，结果为 None。
        has_evidence = has_evidence or any(value is not None for value in (root.payoff_likelihood, root.strength))
        status = root.foreshadowing_status or "open"
        base = _EXPECTATION_BASE_SCORE_BY_PAYOFF.get(
            root.payoff_likelihood or "",
            _EXPECTATION_BASE_SCORE_BY_PAYOFF["medium"],
        )
        status_bonus = _EXPECTATION_STATUS_BONUS.get(
            status,
            _EXPECTATION_STATUS_BONUS["open"],
        )
        strength_bonus = _EXPECTATION_STRENGTH_BONUS.get(
            root.strength or "",
            _EXPECTATION_STRENGTH_BONUS["low"],
        )
        score = min(
            1.0,
            max(
                0.0,
                base + status_bonus + strength_bonus + (0.08 if hit_count >= 3 else 0.04 if hit_count == 2 else 0.0),
            ),
        )
        status_weight = _EXPECTATION_STATUS_WEIGHT.get(
            status,
            _EXPECTATION_STATUS_WEIGHT["open"],
        )
        strength_weight = _EXPECTATION_STRENGTH_WEIGHT.get(
            root.strength or "",
            _EXPECTATION_STRENGTH_WEIGHT["low"],
        )
        weight = status_weight + (0.20 if hit_count >= 3 else 0.10 if hit_count == 2 else 0.0) + strength_weight
        weighted_total += score * weight
        total_weight += weight
    if not has_evidence:
        return None
    return round(weighted_total / total_weight, 4)
