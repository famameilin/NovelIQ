"""全书静态组织查询，分支分页与全书搜索共用同一真实节点身份"""

from __future__ import annotations

import base64
import json
from collections import Counter, defaultdict
from functools import cached_property
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.storage.models import Chapter, EventEdge, EventMembership, EventNode, EventReference, NarrativeArc


class EventOrganizationQuery:
    def __init__(self, session: Session, run_id: str) -> None:
        self.session, self.run_id = session, run_id
        self.events = {
            row.event_id: row
            for row in session.scalars(
                select(EventNode)
                .where(EventNode.run_id == run_id)
                .order_by(EventNode.chapter_order, EventNode.event_id)
            )
        }
        self.arcs = {
            row.arc_id: row
            for row in session.scalars(
                select(NarrativeArc).where(NarrativeArc.run_id == run_id).order_by(NarrativeArc.arc_id)
            )
        }
        self.members = {
            row.event_id: row
            for row in session.scalars(select(EventMembership).where(EventMembership.run_id == run_id))
        }
        if set(self.members) != set(self.events):
            raise ValueError("已保存诊断的事件归属与原子事件不一致")
        self.references = list(
            session.scalars(
                select(EventReference)
                .where(EventReference.run_id == run_id)
                .order_by(EventReference.arc_id, EventReference.event_id)
            )
        )
        self.chapters = [
            {"chapter_id": row.chapter_id, "order": index + 1, "title": row.display_title or row.title}
            for index, row in enumerate(
                session.scalars(
                    select(Chapter)
                    .where(Chapter.run_id == run_id, Chapter.text.is_not(None))
                    .order_by(Chapter.sequence, Chapter.chapter_id)
                )
            )
        ]
        self.orders = {row["chapter_id"]: row["order"] for row in self.chapters}
        self.active_edges = list(
            session.scalars(
                select(EventEdge)
                .where(EventEdge.run_id == run_id, EventEdge.is_active.is_(True))
                .order_by(EventEdge.edge_id)
            )
        )
        self.title = " / ".join(arc.objective for arc in self.arcs.values() if arc.kind == "main") or "全书叙事组织"
        self.nodes: dict[str, dict[str, Any]] = {"root": self._node("root", "root", self.title, None)}
        for arc in self.arcs.values():
            key = f"arc:{arc.arc_id}"
            self.nodes[key] = self._node(
                key, "arc", arc.title, f"arc:{arc.parent_arc_id}" if arc.parent_arc_id else "root", arc_id=arc.arc_id
            )
        for event in self.events.values():
            membership = self.members.get(event.event_id)
            arc_id = membership.arc_id if membership else None
            parent = f"arc:{arc_id}" if arc_id else "unassigned"
            if not arc_id:
                self.nodes.setdefault("unassigned", self._node("unassigned", "unassigned", "待归属", "root"))
            group = f"group:{arc_id or 'unassigned'}:{event.tree_id}"
            self.nodes.setdefault(
                group, self._node(group, "group", "局部事件组", parent, arc_id=arc_id, tree_id=event.tree_id)
            )
            self.nodes[f"event:{event.event_id}"] = self._node(
                f"event:{event.event_id}",
                "event",
                event.description,
                group,
                arc_id=arc_id,
                tree_id=event.tree_id,
                event_id=event.event_id,
                chapter_id=event.chapter_id,
                chapter_order=self.orders[event.chapter_id],
                is_foreshadowing_root=event.is_foreshadowing_root,
                foreshadowing_status=event.foreshadowing_status if event.is_foreshadowing_root else None,
            )
        # 局部结构只服从已保存父字段，跨归属父边另列为真实关系
        for event in self.events.values():
            node = self.nodes[f"event:{event.event_id}"]
            parent = self.nodes.get(f"event:{event.parent_node_id}")
            if parent and parent["arc_id"] == node["arc_id"] and parent["tree_id"] == node["tree_id"]:
                node["parent_id"] = parent["node_id"]
            if event.cause_role == "root":
                group_id = f"group:{node['arc_id'] or 'unassigned'}:{event.tree_id}"
                self.nodes[group_id]["title"] = event.description
        self.group_events: dict[str, list[EventNode]] = defaultdict(list)
        for event in self.events.values():
            node = self.nodes[f"event:{event.event_id}"]
            group_id = f"group:{node['arc_id'] or 'unassigned'}:{event.tree_id}"
            self.group_events[group_id].append(event)
        for group_id, events in self.group_events.items():
            group = self.nodes[group_id]
            first = events[0]
            # 跨线分组可能没有原树根，仍用本组最早事件标识，不能冒用其他分组或整条支线
            if group["title"] == "局部事件组":
                group["title"] = first.description
            group.update(chapter_id=first.chapter_id, chapter_order=self.orders[first.chapter_id])
        counts = Counter(node["parent_id"] for node in self.nodes.values())
        for node in self.nodes.values():
            node["child_count"] = counts[node["node_id"]]

    @staticmethod
    def _node(key: str, kind: str, title: str, parent: str | None, **fields: Any) -> dict[str, Any]:
        return {"node_id": key, "kind": kind, "title": title, "parent_id": parent, "child_count": 0, **fields}

    def path(self, key: str) -> list[str]:
        result: list[str] = []
        current: str | None = key
        while current is not None:
            if current in result or current not in self.nodes:
                raise ValueError("已保存组织路径无效")
            result.append(current)
            current = self.nodes[current]["parent_id"]
        return list(reversed(result))

    @cached_property
    def relations(self) -> list[dict[str, str]]:
        edges = [
            {
                "source_id": node["parent_id"],
                "target_id": node["node_id"],
                "kind": "local_parent" if node["parent_id"].startswith("event:") else "organization",
            }
            for node in self.nodes.values()
            if node["parent_id"]
        ]
        for event in self.events.values():
            if (
                event.parent_node_id
                and self.nodes[f"event:{event.event_id}"]["parent_id"] != f"event:{event.parent_node_id}"
            ):
                edges.append(
                    {
                        "source_id": f"event:{event.parent_node_id}",
                        "target_id": f"event:{event.event_id}",
                        "kind": "local_parent",
                    }
                )
        edges.extend(
            {
                "source_id": f"event:{edge.source_event_id}",
                "target_id": f"event:{edge.target_event_id}",
                "kind": edge.edge_type,
            }
            for edge in self.active_edges
        )
        edges.extend(
            {"source_id": f"arc:{ref.arc_id}", "target_id": f"event:{ref.event_id}", "kind": "reference"}
            for ref in self.references
        )
        return edges

    def fetch(
        self,
        *,
        parent_id: str | None = None,
        q: str = "",
        chapter_id: int | None = None,
        cursor: str | None = None,
        limit: int = 100,
        expand_all: bool = False,
    ) -> dict[str, Any]:
        if not 1 <= limit <= 500:
            raise ValueError("分页大小必须在1到500之间")
        if parent_id and parent_id not in self.nodes:
            raise LookupError("NODE_NOT_FOUND")
        if chapter_id is not None and chapter_id not in self.orders:
            raise ValueError("章节不存在")
        searching = bool(q) or chapter_id is not None
        if expand_all and (searching or parent_id):
            raise ValueError("全书展开不能与分支或搜索条件混用")
        if searching:
            candidates = [
                node
                for node in self.nodes.values()
                if node["kind"] == "event"
                and (not q or q.casefold() in node["title"].casefold())
                and (chapter_id is None or node.get("chapter_id") == chapter_id)
            ]
        elif parent_id:
            candidates = [node for node in self.nodes.values() if node["parent_id"] == parent_id]
        elif expand_all:
            candidates = list(self.nodes.values())
        else:
            candidates = [node for node in self.nodes.values() if node["kind"] in {"root", "arc", "unassigned"}]
        candidates.sort(key=lambda node: (node.get("chapter_order", 0), node["node_id"]))
        if searching and parent_id:
            candidates = [node for node in candidates if parent_id in self.path(node["node_id"])[:-1]]
        # 全书分页具有独立查询身份，不能误用骨架、分支或搜索的游标
        context = [self.run_id, "all"] if expand_all else [self.run_id, parent_id, q, chapter_id]
        offset = 0
        if cursor:
            try:
                data = json.loads(base64.urlsafe_b64decode(cursor.encode()).decode())
                if data["query"] != context or not isinstance(data["offset"], int) or data["offset"] < 0:
                    raise ValueError
                offset = data["offset"]
            except (ValueError, KeyError, TypeError, UnicodeError) as exc:
                raise ValueError("分页游标与当前事件树条件不匹配") from exc
        page = candidates[offset : offset + limit]
        next_cursor = base64.urlsafe_b64encode(
            json.dumps({"query": context, "offset": offset + limit}).encode()
        ).decode()
        keys = {node["node_id"] for node in page}
        if expand_all:
            # 关系端点作为本页上下文一并返回，跨页因果和引用不能在合并全书时丢失
            page_keys = keys.copy()
            for edge in self.relations:
                if edge["source_id"] in page_keys or edge["target_id"] in page_keys:
                    keys.update((edge["source_id"], edge["target_id"]))
        if parent_id:
            keys.update(self.path(parent_id))
        # 每页带完整祖先，骨架分页也不会丢失跨页组织边
        for key in list(keys):
            keys.update(self.path(key))
        nodes = [self.nodes[key] for key in sorted(keys)]
        return {
            "run_id": self.run_id,
            "title": self.title,
            "chapters": self.chapters,
            "total_events": len(self.events),
            "arcs": [
                {
                    field: getattr(arc, field)
                    for field in ("arc_id", "parent_arc_id", "kind", "title", "objective", "role", "reason", "evidence")
                }
                for arc in self.arcs.values()
            ],
            "nodes": nodes,
            "edges": [edge for edge in self.relations if edge["source_id"] in keys and edge["target_id"] in keys],
            "total": len(candidates),
            "next_cursor": next_cursor if offset + limit < len(candidates) else None,
            "matches": [
                {
                    "node_id": node["node_id"],
                    "title": node["title"],
                    "ancestor_ids": self.path(node["node_id"])[:-1],
                    "chapter_id": node.get("chapter_id"),
                    "chapter_order": node.get("chapter_order"),
                }
                for node in page
            ]
            if searching
            else [],
        }

    @cached_property
    def relations_by_node(self) -> dict[str, list[dict[str, str]]]:
        result = defaultdict(list)
        for edge in self.relations:
            result[edge["source_id"]].append(edge)
            result[edge["target_id"]].append(edge)
        return dict(result)

    @cached_property
    def references_by_node(self) -> dict[str, list[dict[str, Any]]]:
        result = defaultdict(list)
        for ref in self.references:
            value = {field: getattr(ref, field) for field in ("arc_id", "event_id", "role", "reason", "evidence")}
            value.update(arc_title=self.arcs[ref.arc_id].title, event_title=self.events[ref.event_id].description)
            result[f"arc:{ref.arc_id}"].append(value)
            result[f"event:{ref.event_id}"].append(value)
        return dict(result)

    def detail(self, key: str) -> dict[str, Any]:
        if key not in self.nodes:
            raise LookupError("NODE_NOT_FOUND")
        node = self.nodes[key]
        event = self.events.get(node.get("event_id"))
        group_events = self.group_events.get(key, [])
        owner = self.members.get(event.event_id) if event else self.arcs.get(node.get("arc_id"))
        evidence = list(event.evidence) if event else [item for member in group_events for item in member.evidence]
        if node["kind"] == "arc" and owner:
            for reference in owner.evidence:
                source = self.events[reference["event_id"]]
                evidence.extend(
                    item
                    for item in source.evidence
                    if reference.get("paragraph_id") is None or item.get("paragraph_id") == reference["paragraph_id"]
                )
        # 分组依据只取本组事件；归属理由仍来自这些事件的已保存成员记录
        group_members = [self.members[member.event_id] for member in group_events]
        role = (
            " / ".join(dict.fromkeys(member.role for member in group_members))
            if group_members
            else owner.role
            if owner
            else None
        )
        reason = (
            "\n".join(dict.fromkeys(member.reason for member in group_members))
            if group_members
            else owner.reason
            if owner
            else None
        )
        organization_evidence = (
            [item for member in group_members for item in member.evidence]
            if group_members
            else owner.evidence
            if owner
            else []
        )
        evidence = list({json.dumps(item, sort_keys=True, ensure_ascii=False): item for item in evidence}.values())
        anchors = (
            list(event.anchor_paragraph_ids)
            if event
            else list(dict.fromkeys(anchor for member in group_events for anchor in member.anchor_paragraph_ids))
        )
        scope = (
            "paragraph"
            if anchors
            and all(any(item.get("paragraph_id") == anchor for item in evidence) for anchor in anchors)
            and all(item.get("paragraph_id") is not None for item in evidence)
            else "chapter"
        )
        labels = {
            "organization": "组织归属",
            "local_parent": "局部父子",
            "causal": "因果关联",
            "foreshadowing": "伏笔照应",
            "reference": "跨线引用",
        }
        return {
            **node,
            "path": [self.nodes[value] for value in self.path(key)],
            "role": role,
            "reason": reason,
            "organization_evidence": organization_evidence,
            "evidence": evidence,
            "evidence_scope": scope,
            "anchor_paragraph_ids": anchors if scope == "paragraph" else [],
            "participants": event.participants if event else [],
            "relations": [
                {
                    **edge,
                    "title": labels[edge["kind"]],
                    "direction": "outgoing" if edge["source_id"] == key else "incoming",
                    "related_node": self.nodes[edge["target_id"] if edge["source_id"] == key else edge["source_id"]],
                    "ancestor_ids": self.path(edge["target_id"] if edge["source_id"] == key else edge["source_id"])[
                        :-1
                    ],
                }
                for edge in self.relations_by_node.get(key, [])
            ],
            "references": self.references_by_node.get(key, []),
        }

    def export(self) -> dict[str, Any]:
        result = self.fetch()
        result.update(nodes=list(self.nodes.values()), edges=self.relations, total=len(self.nodes), next_cursor=None)
        result["details"] = [self.detail(key) for key in self.nodes]
        return result
