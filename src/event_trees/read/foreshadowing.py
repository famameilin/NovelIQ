"""从伏笔事件与动作事实读取全书事件身份和原文证据"""

from __future__ import annotations

from typing import Any, cast

from src.event_trees import storage_map as smap
from src.event_trees.action_order import ForeshadowingActionRow, action_order, load_foreshadowing_actions
from src.event_trees.read.organization import EventTreeQuery
from src.storage import Storage
from src.storage.records.annotation import ForeshadowingTreeView
from src.storage.records.models import CompleteEventRecord as CompleteEvent

_EXPECTATION_BASE_SCORE_BY_PAYOFF = {"high": 0.62, "medium": 0.38, "low": 0.14}
_EXPECTATION_STATUS_BONUS = {"open": -0.07, "reinforced": 0.03, "likely_paid_off": 0.28}
_EXPECTATION_STRENGTH_BONUS = {"high": 0.03, "medium": 0.0, "low": -0.05}
_EXPECTATION_STATUS_WEIGHT = {"open": 0.75, "reinforced": 1.0, "likely_paid_off": 1.2}
_EXPECTATION_STRENGTH_WEIGHT = {"high": 0.05, "medium": 0.0, "low": -0.05}


def _foreshadowing_roots(session: Storage, run_id: str) -> tuple[list[CompleteEvent], dict[str, Any]]:
    """本 run 的伏笔埋设事件及来源章信息，按真实章序与本地地址稳定排序"""
    annotation_events = smap.run_annotation_event_ids(session, run_id)
    if not annotation_events:
        return [], {}
    rows = list(session.reads.events.list_foreshadowing_roots(annotation_events))
    sources = smap.annotation_sources(session, {row.annotation_record_id for row in rows})
    rows.sort(
        key=lambda row: (
            sources[cast(str, row.annotation_record_id)].chapter_order or 0,
            row.local_key,
            row.event_id,
        )
    )
    return rows, sources


def foreshadowing_by_chapter(session: Storage, run_id: str) -> dict[int, dict[str, Any]]:
    """按动作实际来源章节投影埋设事件与回收可能性"""
    actions = load_foreshadowing_actions(session, run_id)
    if not actions:
        return {}
    events = smap.run_events(session, run_id)
    by_chapter: dict[int, dict[str, Any]] = {}
    for action in actions:
        if action.chapter_id is None:
            raise ValueError("伏笔动作缺少真实来源章")
        annotation_event = events[action.source_event_id]
        payoff_likelihood = annotation_event.payoff_likelihood
        by_chapter[action.chapter_id] = {
            "has_foreshadowing": True,
            "is_strong_setup": payoff_likelihood == "high" if payoff_likelihood is not None else None,
            "foreshadowing_desc": annotation_event.title,
            "why_unresolved_now": None,
            "payoff_likelihood": payoff_likelihood,
            "foreshadowing_source_event_id": action.source_event_id,
        }
    return by_chapter


def fetch_foreshadowing_trees(session: Storage, run_id: str) -> list[ForeshadowingTreeView]:
    """按埋设事件聚合动作，端点定位与动作原文证据分别保留"""
    query = EventTreeQuery(session, run_id)
    payload = query.fetch()
    by_source: dict[str, list[dict[str, Any]]] = {}
    for action in payload["foreshadowing_actions"]:
        by_source.setdefault(action["source_event_id"], []).append(action)
    result: list[ForeshadowingTreeView] = []
    for event_id, actions in by_source.items():
        event = query.events[event_id]
        first, latest = actions[0], actions[-1]
        chapters = sorted({row["chapter_id"] for row in actions}, key=query.orders.__getitem__)
        status = {"setup": "open", "reinforce": "reinforced", "payoff": "likely_paid_off"}[latest["action_type"]]
        result.append(
            ForeshadowingTreeView(
                source_event_id=event_id,
                source_locator=first["source_locator"],
                target_event_id=latest["target_event_id"],
                target_locator=latest["target_locator"],
                actions=actions,
                first_chapter_id=first["chapter_id"],
                last_chapter_id=latest["chapter_id"],
                anchor_chapter_ids=chapters,
                description=event.title,
                payoff_likelihood=event.payoff_likelihood,
                strength=event.strength,
                status=status,
                active=status != "likely_paid_off",
                latest_reason=latest["target_locator"]["title"] if latest["target_locator"] else None,
                latest_why_unresolved_now=None,
            )
        )
    return result


def fetch_foreshadowing_sources(session: Storage, run_id: str) -> list[dict[str, Any]]:
    """诊断发布前读取真实事件及动作材料，来源标识不能冒充正式事件"""
    roots, sources = _foreshadowing_roots(session, run_id)
    actions = sorted(load_foreshadowing_actions(session, run_id), key=action_order)
    evidence = smap.fetch_evidence(session, "complete_event_id", [row.event_id for row in roots])
    return [
        {
            "event_id": row.event_id,
            "title": row.title,
            "problem": row.problem,
            "summary": row.summary,
            "chapter_id": sources[cast(str, row.annotation_record_id)].chapter_id,
            "payoff_likelihood": row.payoff_likelihood,
            # strength 是 payoff_likelihood 的读投影，不双存第二份属性
            "strength": row.payoff_likelihood,
            "evidence": smap.evidence_payloads(session, run_id, evidence.get(row.event_id, [])),
            "source_actions": [
                {
                    "action_id": action.action_id,
                    "action_type": action.action_type,
                    "source_event_id": action.source_event_id,
                    "target_event_id": action.target_event_id,
                    "chapter_id": action.chapter_id,
                    "evidence": action.evidence,
                }
                for action in actions
                if action.source_event_id == row.event_id
            ],
        }
        for row in roots
    ]


def calculate_foreshadow_expectation(
    session: Storage,
    run_id: str,
) -> float | None:
    """沿明确身份归组及正文动作计算既有指标，不改写不可变事件状态"""
    roots, _sources = _foreshadowing_roots(session, run_id)
    if not roots:
        return None
    grouped_roots: dict[str, list[CompleteEvent]] = {}
    for root in roots:
        grouped_roots.setdefault(root.event_id, []).append(root)
    grouped_actions: dict[str, list[ForeshadowingActionRow]] = {}
    for action in sorted(load_foreshadowing_actions(session, run_id), key=action_order):
        grouped_actions.setdefault(action.source_event_id, []).append(action)
    weighted_total = 0.0
    total_weight = 0.0
    has_evidence = False
    for identity, sources in grouped_roots.items():
        # 同一正式伏笔沿最初埋设的属性计分，后续动作只贡献命中和正文最新状态
        root = sources[0]
        actions = grouped_actions.get(identity, [])
        hit_count = max(1, len(actions))
        # 字段为 None 时不冒充 LLM 判断；若全树都无
        # payoff_likelihood 证据，说明上游输入退化，结果为 None。
        has_evidence = has_evidence or root.payoff_likelihood is not None
        status = (
            {"setup": "open", "reinforce": "reinforced", "payoff": "likely_paid_off"}[actions[-1].action_type]
            if actions
            else "open"
        )
        base = _EXPECTATION_BASE_SCORE_BY_PAYOFF.get(
            root.payoff_likelihood or "",
            _EXPECTATION_BASE_SCORE_BY_PAYOFF["medium"],
        )
        status_bonus = _EXPECTATION_STATUS_BONUS.get(
            status,
            _EXPECTATION_STATUS_BONUS["open"],
        )
        strength_bonus = _EXPECTATION_STRENGTH_BONUS.get(
            root.payoff_likelihood or "",
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
            root.payoff_likelihood or "",
            _EXPECTATION_STRENGTH_WEIGHT["low"],
        )
        weight = status_weight + (0.20 if hit_count >= 3 else 0.10 if hit_count == 2 else 0.0) + strength_weight
        weighted_total += score * weight
        total_weight += weight
    if not has_evidence:
        return None
    return round(weighted_total / total_weight, 4)
