"""从伏笔声明与动作事实读取全书事件身份和原文证据"""

from __future__ import annotations

from typing import Any, cast

from src.event_trees import storage_map as smap
from src.event_trees.action_order import ForeshadowingActionRow, action_order, load_foreshadowing_actions
from src.event_trees.read.organization import EventTreeQuery
from src.storage import Storage
from src.storage.records.annotation import ForeshadowingTreeView
from src.storage.records.models import EventDeclarationRecord as EventDeclaration

_EXPECTATION_BASE_SCORE_BY_PAYOFF = {"high": 0.62, "medium": 0.38, "low": 0.14}
_EXPECTATION_STATUS_BONUS = {"open": -0.07, "reinforced": 0.03, "likely_paid_off": 0.28}
_EXPECTATION_STRENGTH_BONUS = {"high": 0.03, "medium": 0.0, "low": -0.05}
_EXPECTATION_STATUS_WEIGHT = {"open": 0.75, "reinforced": 1.0, "likely_paid_off": 1.2}
_EXPECTATION_STRENGTH_WEIGHT = {"high": 0.05, "medium": 0.0, "low": -0.05}


def _foreshadowing_roots(session: Storage, run_id: str) -> tuple[list[EventDeclaration], dict[str, Any]]:
    """本 run 的伏笔根声明及来源章信息，按真实章序与本地地址稳定排序"""
    declarations = smap.run_declaration_ids(session, run_id)
    if not declarations:
        return [], {}
    rows = list(session.reads.event_trees_read_foreshadowing_foreshadowing_roots_1(declarations))
    sources = smap.declaration_sources(session, {row.record_id for row in rows})
    rows.sort(
        key=lambda row: (
            sources[row.record_id].chapter_order or 0,
            row.local_key,
            row.declaration_id,
        )
    )
    return rows, sources


def _bound_events(session: Storage, run_id: str, declaration_ids: list[str]) -> dict[str, str]:
    """读取伏笔声明在本运行中的完整事件归属"""
    if not declaration_ids:
        return {}
    return {
        row.declaration_id: row.event_id
        for row in session.reads.event_trees_read_foreshadowing_bound_events_1(declaration_ids, run_id)
        if row.declaration_id is not None
    }


def foreshadowing_by_chapter(session: Storage, run_id: str) -> dict[int, dict[str, Any]]:
    """章节伏笔投影引用已发布事件，不把来源声明作为事件暴露

    动作事实携带来源声明列（root/target 事件身份是读投影），章号取动作真实来源章；
    诊断发布前没有正式事件身份，描述回退来源声明标题、章号仍按真实来源投影，
    事件身份保持空不回填冒充（与动作读取合同一致）。
    """
    query = EventTreeQuery(session, run_id)
    query.fetch()
    by_chapter: dict[int, dict[str, Any]] = {}
    for action in sorted(load_foreshadowing_actions(session, run_id), key=action_order):
        if action.chapter_id is None:
            raise ValueError("伏笔动作缺少真实来源章")
        declaration = query.declarations[action.source_declaration_id]
        event = None if action.root_event_id is None else query.events[action.root_event_id]
        by_chapter[action.chapter_id] = {
            "has_foreshadowing": True,
            "is_strong_setup": declaration.strength == "high" if declaration.strength is not None else None,
            "foreshadowing_desc": event.title if event is not None else declaration.title,
            "why_unresolved_now": None,
            "payoff_likelihood": declaration.payoff_likelihood,
            "foreshadowing_root_event_id": None if action.action_type == "setup" or event is None else event.event_id,
        }
    return by_chapter


def fetch_foreshadowing_trees(session: Storage, run_id: str) -> list[ForeshadowingTreeView]:
    """按正式事件聚合明确伏笔动作；没有正式事件身份的来源不进入树"""
    query = EventTreeQuery(session, run_id)
    query.fetch()
    by_root: dict[str, list[ForeshadowingActionRow]] = {}
    for action in sorted(load_foreshadowing_actions(session, run_id), key=action_order):
        if action.root_event_id is None:
            continue
        by_root.setdefault(action.root_event_id, []).append(action)
    result: list[ForeshadowingTreeView] = []
    for event_id, actions in by_root.items():
        event = query.events[event_id]
        first, latest = actions[0], actions[-1]
        declaration = query.declarations[first.source_declaration_id]
        chapters = sorted(
            {row.chapter_id for row in actions if row.chapter_id is not None}, key=query.orders.__getitem__
        )
        status = {"setup": "open", "reinforce": "reinforced", "payoff": "likely_paid_off"}[latest.action_type]
        result.append(
            ForeshadowingTreeView(
                root_event_id=event_id,
                tree_id=event_id,
                # 动作事实的真实生产者是标注 work（trees.save_work 写入），来源章随该 work 投影
                first_chapter_id=cast(int, first.chapter_id),
                last_chapter_id=cast(int, latest.chapter_id),
                anchor_chapter_ids=chapters,
                description=cast(str, event.title),
                payoff_likelihood=declaration.payoff_likelihood,
                strength=declaration.strength,
                status=status,
                active=status != "likely_paid_off",
                latest_reason=query.events[latest.target_event_id].title if latest.target_event_id else None,
                latest_why_unresolved_now=None,
            )
        )
    return result


def fetch_foreshadowing_sources(session: Storage, run_id: str) -> list[dict[str, Any]]:
    """诊断发布前读取真实声明及动作材料，来源标识不能冒充正式事件"""
    roots, sources = _foreshadowing_roots(session, run_id)
    actions = sorted(load_foreshadowing_actions(session, run_id), key=action_order)
    evidence = smap.fetch_evidence(session, "declaration_id", [row.declaration_id for row in roots])
    bindings = _bound_events(session, run_id, [row.declaration_id for row in roots])
    return [
        {
            "declaration_id": row.declaration_id,
            "event_id": bindings.get(row.declaration_id),
            "title": row.title,
            "problem": row.problem,
            "summary": row.summary,
            "chapter_id": sources[row.record_id].chapter_id,
            "payoff_likelihood": row.payoff_likelihood,
            # strength 是 payoff_likelihood 的读投影，不双存第二份属性
            "strength": row.payoff_likelihood,
            "evidence": smap.evidence_payloads(session, run_id, evidence.get(row.declaration_id, [])),
            "source_actions": [
                {
                    "action_id": action.action_id,
                    "action_type": action.action_type,
                    "source_declaration_id": action.source_declaration_id,
                    "target_declaration_id": action.target_declaration_id,
                    "chapter_id": action.chapter_id,
                    "evidence": action.evidence,
                }
                for action in actions
                if action.source_declaration_id == row.declaration_id
            ],
        }
        for row in roots
    ]


def calculate_foreshadow_expectation(
    session: Storage,
    run_id: str,
    *,
    declaration_bindings: dict[str, str] | None = None,
) -> float | None:
    """沿明确身份归组及正文动作计算既有指标，不改写不可变声明状态"""
    roots, _sources = _foreshadowing_roots(session, run_id)
    if not roots:
        return None
    bindings = (
        declaration_bindings
        if declaration_bindings is not None
        else _bound_events(session, run_id, [root.declaration_id for root in roots])
    )
    grouped_roots: dict[str, list[EventDeclaration]] = {}
    for root in roots:
        grouped_roots.setdefault(bindings.get(root.declaration_id, root.declaration_id), []).append(root)
    grouped_actions: dict[str, list[ForeshadowingActionRow]] = {}
    for action in sorted(load_foreshadowing_actions(session, run_id), key=action_order):
        grouped_actions.setdefault(bindings.get(action.source_declaration_id, action.source_declaration_id), []).append(
            action
        )
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
