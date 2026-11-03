"""完整事件树及其多父引用的事件结构校验与遍历"""

from __future__ import annotations

from collections import deque
from collections.abc import Iterable, Mapping, Sequence
from typing import Any

EVENT_LINE_MIN = 5
EVENT_LINE_MAX = 10


class QueueGraph:
    """树身份独立于成员事件，成员唯一归属，父树先于子树，空树合法"""

    @classmethod
    def from_rows(
        cls,
        links: Iterable[Any],
        event_ids: Iterable[str],
        tree_ids: Iterable[str],
        *,
        require_complete: bool = True,
        event_line_ids: Iterable[str] | None = None,
    ) -> QueueGraph:
        trees: dict[str, list[tuple[int, str]]] = {}
        references: list[tuple[str, str]] = []
        for row in links:
            if row.tree_id is not None:
                trees.setdefault(row.tree_id, []).append((row.position, row.member_event_id))
            elif row.parent_tree_id is not None:
                references.append((row.parent_tree_id, row.child_tree_id))
        ordered: dict[str, list[str]] = {}
        for tree_id in tree_ids:
            members = trees.get(tree_id, [])
            members.sort()
            if [position for position, _ in members] != list(range(len(members))):
                raise ValueError("事件树成员位置必须从 0 连续递增")
            ordered[tree_id] = [event_id for _, event_id in members]
        if set(trees) - set(ordered):
            raise ValueError("事件树成员引用了不存在的树")
        return cls(
            ordered,
            references,
            event_ids,
            require_complete=require_complete,
            event_line_ids=event_line_ids,
        )

    def __init__(
        self,
        queues: Mapping[str, Sequence[str]],
        references: Iterable[tuple[str, str]],
        event_ids: Iterable[str],
        *,
        require_complete: bool = True,
        event_line_ids: Iterable[str] | None = None,
    ) -> None:
        self.queues = {key: tuple(values) for key, values in queues.items()}
        self.event_tree: dict[str, str] = {}
        self.positions: dict[str, int] = {}
        known = set(event_ids)
        for tree_id, members in self.queues.items():
            for position, event_id in enumerate(members):
                if event_id not in known:
                    raise ValueError(f"事件树成员不属于本运行: {event_id}")
                if event_id in self.event_tree:
                    raise ValueError(f"事件只能属于一棵原生事件树，且不得重复: {event_id}")
                self.event_tree[event_id] = tree_id
                self.positions[event_id] = position
        if require_complete and known != set(self.event_tree):
            raise ValueError("事件尚未完整登记事件树，请在 finish 前明确提交全部成员顺序")
        self.children: dict[str, list[str]] = {key: [] for key in self.queues}
        self.parents: dict[str, list[str]] = {key: [] for key in self.queues}
        for parent, child in references:
            if parent not in self.queues or child not in self.queues:
                raise ValueError("父子引用只能连接本运行的完整事件树")
            if parent == child:
                raise ValueError("事件树不能引用自身")
            if child in self.children[parent]:
                raise ValueError("事件树父子引用重复")
            self.children[parent].append(child)
            self.parents[child].append(parent)
        remaining = {key: len(values) for key, values in self.parents.items()}
        ready = deque(key for key, count in remaining.items() if count == 0)
        self.order: list[str] = []
        while ready:
            key = ready.popleft()
            self.order.append(key)
            for child in self.children[key]:
                remaining[child] -= 1
                if remaining[child] == 0:
                    ready.append(child)
        if len(self.order) != len(self.queues):
            raise ValueError("事件树父子引用不能成环")
        self.unparented = [key for key in self.order if not self.parents[key]]
        self.event_line_ids = tuple(event_line_ids or ())
        self.lines: dict[str, set[str]] = {}
        for key in self.order:
            self.lines[key] = (
                {key} if not self.parents[key] else set().union(*(self.lines[parent] for parent in self.parents[key]))
            )

    def reachable(self, tree_id: str) -> list[str]:
        """返回稳定拓扑序中的可达事件树，共享节点只计一次"""
        if tree_id not in self.queues:
            raise ValueError(f"事件树不属于本运行: {tree_id}")
        found: set[str] = set()
        pending = [tree_id]
        while pending:
            key = pending.pop()
            if key not in found:
                found.add(key)
                pending.extend(self.children[key])
        return [key for key in self.order if key in found]

    def event_parents(self, event_id: str) -> list[str]:
        tree_id = self.event_tree[event_id]
        members = self.queues[tree_id]
        index = self.positions[event_id]
        if index:
            return [members[index - 1]]
        return [self.queues[parent][-1] for parent in self.parents[tree_id] if self.queues[parent]]

    def event_children(self, event_id: str) -> list[str]:
        tree_id = self.event_tree[event_id]
        members = self.queues[tree_id]
        index = self.positions[event_id]
        if index + 1 < len(members):
            return [members[index + 1]]
        return [self.queues[child][0] for child in self.children[tree_id] if self.queues[child]]

    def event_lines(self, event_id: str) -> list[str]:
        tree_id = self.event_tree[event_id]
        return [line for line in self.event_line_ids if line in self.lines[tree_id]]

    def ancestors(self, event_id: str) -> list[str]:
        found: set[str] = set()
        pending = self.event_parents(event_id)
        while pending:
            key = pending.pop()
            if key not in found:
                found.add(key)
                pending.extend(self.event_parents(key))
        return [member for key in self.order for member in self.queues[key] if member in found]

    def tree_events(self, tree_id: str) -> list[str]:
        """返回一棵树及其全部后代树的成员事件，空树返回空列表"""
        if tree_id not in self.queues:
            raise ValueError(f"事件树入口不属于本运行: {tree_id}")
        reachable = set(self.reachable(tree_id))
        return [identifier for key in self.order if key in reachable for identifier in self.queues[key]]

    def event_line_coverage(self, event_line_ids: Iterable[str]) -> dict[str, int | float]:
        """按事件 ID 去重计算所选事件树对全书正式事件的覆盖"""
        covered: set[str] = set()
        for identifier in event_line_ids:
            covered.update(self.tree_events(identifier))
        total = len(self.event_tree)
        return {
            "covered_events": len(covered),
            "total_events": total,
            "coverage": len(covered) / total if total else 0.0,
        }

    def require_event_lines(self, event_line_ids: Sequence[str]) -> dict[str, int | float]:
        """校验事件线为 5–10 棵不同事件树并计算去重覆盖率"""
        if (
            len(set(event_line_ids)) != len(event_line_ids)
            or not EVENT_LINE_MIN <= len(event_line_ids) <= EVENT_LINE_MAX
        ):
            raise ValueError(f"诊断须挑选 {EVENT_LINE_MIN}–{EVENT_LINE_MAX} 棵不同事件树作为事件线")
        missing = sorted(set(event_line_ids) - set(self.queues))
        if missing:
            raise ValueError(f"事件线入口不属于本运行的事件树: {missing}")
        return self.event_line_coverage(event_line_ids)
