"""运行事务内的事件树、成员与父子引用保存"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sqlalchemy import select, update

from src.storage.ids import new_id
from src.storage.models import CompleteEvent, NarrativeGroup, NarrativeLink
from src.storage.repositories import narrative_records as smap
from src.utils.event_line_names import validate_event_line_names


@dataclass(frozen=True)
class StoredQueueIndex:
    """事务内已保存事件树的成员索引与无父树身份"""

    queues: dict[str, tuple[str, ...]]
    unparented: list[str]
    children: dict[str, set[str]]


def queue_graph(session: Any, run_id: str, *, require_complete: bool = True) -> StoredQueueIndex:
    executions = smap.run_execution_ids(run_id)
    events = set(session.scalars(select(CompleteEvent.event_id).where(CompleteEvent.producer_agent_id.in_(executions))))
    trees = set(
        session.scalars(
            select(NarrativeGroup.group_id).where(
                NarrativeGroup.producer_agent_id.in_(executions),
                NarrativeGroup.kind == "tree",
            )
        )
    )
    links = list(session.scalars(select(NarrativeLink).where(NarrativeLink.producer_agent_id.in_(executions))))
    return graph_from_links(links, events, trees, require_complete=require_complete)


def graph_from_links(
    links: list[Any], events: Any, trees: Any, *, require_complete: bool = True
) -> StoredQueueIndex:
    """核对树成员位置、端点与有向无环约束，空树合法"""
    known_events = set(events)
    members: dict[str, list[Any]] = {}
    for row in links:
        if row.tree_id is not None:
            members.setdefault(row.tree_id, []).append(row)
    queues: dict[str, tuple[str, ...]] = {}
    owned: set[str] = set()
    for tree_id in trees:
        rows = members.get(tree_id, [])
        rows.sort(key=lambda row: row.position)
        identifiers = tuple(row.member_event_id for row in rows)
        if [row.position for row in rows] != list(range(len(rows))):
            raise ValueError("事件树成员位置必须从 0 连续递增")
        if len(set(identifiers)) != len(identifiers) or owned.intersection(identifiers):
            raise ValueError("每个事件只能属于一棵事件树")
        queues[tree_id] = identifiers
        owned.update(identifiers)
    if set(members) - set(queues):
        raise ValueError("事件树成员引用了不存在的树")
    if not owned <= known_events or (require_complete and owned != known_events):
        raise ValueError("事件尚未完整登记事件树，请在 finish 前明确提交全部成员顺序")
    children: dict[str, set[str]] = {key: set() for key in queues}
    incoming = dict.fromkeys(queues, 0)
    for row in links:
        if row.parent_tree_id is None:
            continue
        parent, child = row.parent_tree_id, row.child_tree_id
        if parent not in queues or child not in queues:
            raise ValueError("父子引用端点必须是完整事件树")
        if child not in children[parent]:
            children[parent].add(child)
            incoming[child] += 1
    unparented = sorted(key for key, count in incoming.items() if not count)
    pending, visited = list(unparented), 0
    while pending:
        parent = pending.pop()
        visited += 1
        for child in children[parent]:
            incoming[child] -= 1
            if not incoming[child]:
                pending.append(child)
    if visited != len(queues):
        raise ValueError("父子引用不得成环")
    return StoredQueueIndex(queues, unparented, children)


def save_event_line_flags(
    session: Any, run_id: str, event_line_ids: list[str], line_names: dict[str, str] | None = None
) -> None:
    """事务内验证事件线树身份、数量与命名并保存树标记"""
    if len(set(event_line_ids)) != len(event_line_ids) or not 5 <= len(event_line_ids) <= 10:
        raise ValueError("事件线须为 5–10 棵不同事件树")
    graph = queue_graph(session, run_id)
    if not set(event_line_ids) <= set(graph.queues):
        raise ValueError("事件线入口必须属于本运行的事件树")
    if line_names is not None:
        validate_event_line_names(line_names, event_line_ids)
    session.execute(
        update(NarrativeGroup)
        .where(
            NarrativeGroup.producer_agent_id.in_(smap.run_execution_ids(run_id)),
            NarrativeGroup.kind == "tree",
        )
        .values(is_event_line=NarrativeGroup.group_id.in_(event_line_ids), line_name=None)
    )
    for tree_id, name in (line_names or {}).items():
        session.execute(update(NarrativeGroup).where(NarrativeGroup.group_id == tree_id).values(line_name=name))


def save_queues(session: Any, run_id: str, queues: list[Any], *, require_complete: bool = True) -> None:
    """调用方持有运行事务锁；先幂等写树行，再写成员与引用，失败整笔回滚"""
    for queue in queues:
        existing_tree = session.get(NarrativeGroup, queue.tree_id)
        if existing_tree is not None:
            if (
                existing_tree.kind != "tree"
                or existing_tree.producer_agent_id != queue.producer_agent_id
                or existing_tree.title != queue.title
                or existing_tree.description != queue.description
            ):
                raise ValueError("已保存事件树的作者、标题或说明与重投不一致")
        else:
            session.add(
                NarrativeGroup(
                    group_id=queue.tree_id,
                    producer_agent_id=queue.producer_agent_id,
                    kind="tree",
                    title=queue.title,
                    description=queue.description,
                    is_event_line=False,
                    tree_key=queue.tree_key,
                )
            )
            session.flush()
        existing = list(
            session.scalars(
                select(NarrativeLink)
                .where(NarrativeLink.tree_id == queue.tree_id)
                .order_by(NarrativeLink.position)
            )
        )
        if existing:
            if [row.member_event_id for row in existing] != queue.event_ids or any(
                row.producer_agent_id != queue.producer_agent_id or row.reason != queue.reason for row in existing
            ):
                raise ValueError("已保存事件树的作者、成员或顺序与重投不一致")
            for row in existing:
                _check_evidence(session, row.link_id, queue.evidence)
            continue
        for position, event_id in enumerate(queue.event_ids):
            row = NarrativeLink(
                link_id=new_id(),
                producer_agent_id=queue.producer_agent_id,
                reason=queue.reason,
                tree_id=queue.tree_id,
                member_event_id=event_id,
                position=position,
            )
            session.add(row)
            session.flush()
            smap.write_evidence_rows(session, {"narrative_link_id": row.link_id}, queue.evidence)
    session.flush()
    queue_graph(session, run_id, require_complete=require_complete)


def _check_evidence(session: Any, link_id: str, evidence: list[Any]) -> None:
    from src.storage.models import SourceEvidence

    actual = smap.fetch_evidence(session, SourceEvidence.narrative_link_id, [link_id]).get(link_id, [])
    wanted = [
        ref if isinstance(ref, dict) else ref.model_dump() if hasattr(ref, "model_dump") else vars(ref)
        for ref in evidence
    ]
    if [(r.paragraph_id, r.start_char, r.end_char, r.related_complete_event_id) for r in actual] != [
        (r["paragraph_id"], r.get("char_start", 0), r["char_end"], r.get("event_id")) for r in wanted
    ]:
        raise ValueError("已保存事件树证据与重投不一致")
