"""全书事件节点与显式连接，节点生产执行与读取内容共同授权引用"""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from sqlalchemy.orm import Session

from src.event_trees.contributions import EventContribution
from src.utils.identity import stable_uuid


class EventTrees:
    """内存方法只由 agent 在 run 锁内调用，不订阅事件总线"""

    def __init__(self, run_id: str) -> None:
        self.run_id = run_id
        self.nodes: dict[str, dict[str, Any]] = {}
        self.connections: dict[str, dict[str, Any]] = {}
        self.executions: set[tuple[str, str]] = set()
        self.saved: set[tuple[str, str]] = set()
        self.actions: dict[str, dict[str, Any]] = {}

    def begin(self, work_id: str, invocation_id: str) -> None:
        self.executions.add((work_id, invocation_id))

    def sync(self, author: tuple[str, str], chapter_id: int, events: list[Any]) -> None:
        if author not in self.executions:
            raise ValueError(f"事件执行已停止: {author}")
        for event in events:
            content = event.model_dump(mode="json")
            identifier = content["node_id"]
            current = self.nodes.get(identifier)
            if current is not None and (current["author"] != author or current["author"] in self.saved):
                raise ValueError(f"node_id={identifier} 已属于其他或已保存执行")
            if current is not None:
                immutable = {"description", "evidence_paragraph_id", "tree_id", "parent_node_id", "cause_role"}
                if any(current["content"][key] != content[key] for key in immutable):
                    raise ValueError(f"node_id={identifier} 重复节点业务内容冲突")
            self.nodes[identifier] = {"author": author, "chapter_id": chapter_id, "content": deepcopy(content)}
        self._parents()

    def write_action(self, author: tuple[str, str], value: dict[str, Any]) -> str:
        """明确动作沿用来源操作身份，同章多次动作分别保留"""
        if author not in self.executions or author in self.saved:
            raise ValueError(f"事件执行已停止: {author}")
        identifier = stable_uuid(self.run_id, author[0], value["source_operation_id"])
        action = {**deepcopy(value), "author": author}
        existing = self.actions.get(identifier)
        if existing is not None:
            # 相同来源重试不能因已写动作数量增加而误判为内容冲突
            action["operation_order"] = existing["operation_order"]
        if existing is not None and existing != action:
            raise ValueError(f"source_operation_id={value['source_operation_id']} 业务内容冲突")
        self.actions[identifier] = action
        return identifier

    def _parents(self) -> dict[str, str]:
        parents = {
            key: node["content"]["parent_node_id"]
            for key, node in self.nodes.items()
            if node["content"].get("parent_node_id")
        }
        if any(parent not in self.nodes for parent in parents.values()):
            raise ValueError("事件父节点不存在")
        for connection in self.connections.values():
            if connection["type"] in {"causal", "foreshadowing"}:
                continue
            child, parent = connection["child"], connection["parent"]
            if child not in self.nodes or parent not in self.nodes:
                raise ValueError(f"连接端点不存在: {parent}->{child}")
            if child in parents and parents[child] != parent:
                raise ValueError(f"node_id={child} 已有父节点={parents[child]}，不能连接父节点={parent}")
            parents[child] = parent
        for child in parents:
            seen: set[str] = set()
            current = child
            while current in parents:
                if current in seen:
                    raise ValueError(f"事件连接形成环: node_id={current}")
                seen.add(current)
                current = parents[current]
        return parents

    def read(self, node_id: str) -> dict[str, Any]:
        node = self.nodes.get(node_id)
        if node is None:
            raise ValueError(f"node_id={node_id} 当前不存在")
        parents = self._parents()
        root = node_id
        while root in parents:
            root = parents[root]
        content = deepcopy(node["content"])
        content["parent_node_id"] = parents.get(node_id)
        content["tree_id"] = self.nodes[root]["content"]["tree_id"]
        explicit = next(
            (
                item
                for item in self.connections.values()
                if item["child"] == node_id and item["type"] not in {"causal", "foreshadowing"}
            ),
            None,
        )
        if explicit is not None:
            content["cause_role"] = explicit["type"]
        return {
            "run_id": self.run_id,
            "node_id": node_id,
            "work_id": node["author"][0],
            "producer_invocation_id": node["author"][1],
            "chapter_id": node["chapter_id"],
            "saved": node["author"] in self.saved,
            "content": content,
        }

    def search_ids(
        self,
        query: str = "",
        *,
        chapter_id: int | None = None,
        tree_id: str | None = None,
    ) -> list[str]:
        """先筛选稳定节点 ID，分页读取详情时不复制整本书的节点正文"""
        parents = self._parents() if tree_id is not None else {}
        values: list[str] = []
        for identifier, node in sorted(self.nodes.items()):
            if chapter_id is not None and node["chapter_id"] != chapter_id:
                continue
            if query.casefold() not in node["content"]["description"].casefold():
                continue
            if tree_id is not None:
                root = identifier
                while root in parents:
                    root = parents[root]
                if self.nodes[root]["content"]["tree_id"] != tree_id:
                    continue
            values.append(identifier)
        return values

    def connect(
        self,
        author: tuple[str, str],
        child: str,
        parent: str,
        kind: str,
        reads: dict[str, dict[str, Any]],
        authorized_paragraphs: set[int],
    ) -> str:
        if author not in self.executions:
            raise ValueError(f"事件执行已停止: {author}")
        if kind not in {"main", "secondary", "causal", "foreshadowing"}:
            raise ValueError(f"连接类型={kind!r}，期望 main/secondary/foreshadowing")
        if child == parent:
            raise ValueError(f"node_id={child} 不能连接自身")
        for identifier in (child, parent):
            current = self.read(identifier)
            read = reads.get(identifier)
            if read is None:
                raise ValueError(f"node_id={identifier} 本 invocation 尚未实际读取，请重新读取")
            if read["producer_invocation_id"] != current["producer_invocation_id"]:
                raise ValueError(
                    f"node_id={identifier} 读取生产者={read['producer_invocation_id']} "
                    f"当前生产者={current['producer_invocation_id']}，请重新读取"
                )
            if read["content"] != current["content"]:
                raise ValueError(f"node_id={identifier} 当前业务内容已变化，请重新读取")
            if self.nodes[identifier]["author"] != author and not current["saved"]:
                raise ValueError(f"node_id={identifier} 属于其他未成功保存 work={current['work_id']}")
            paragraph_id = current["content"]["evidence_paragraph_id"]
            if paragraph_id not in authorized_paragraphs:
                raise ValueError(f"node_id={identifier} 原文 paragraph_id={paragraph_id} 尚未实际读取")
        connection_id = stable_uuid(self.run_id, author[0], parent, child, kind)
        if kind == "foreshadowing" and not self.nodes[parent]["content"]["is_foreshadow_setup"]:
            raise ValueError(f"node_id={parent} is_foreshadow_setup=False，不能作为伏笔来源")
        existing = self.connections.get(connection_id)
        if existing is not None:
            return connection_id
        self.connections[connection_id] = {"parent": parent, "child": child, "type": kind, "author": author}
        try:
            self._parents()
            self._check_dag(
                [
                    (value["parent"], value["child"])
                    for value in self.connections.values()
                    if value["type"] != "foreshadowing"
                ]
                + [
                    (value["content"]["parent_node_id"], key)
                    for key, value in self.nodes.items()
                    if value["content"]["parent_node_id"]
                ]
            )
        except Exception:
            self.connections.pop(connection_id)
            raise
        return connection_id

    @staticmethod
    def _check_dag(edges: list[tuple[str, str]]) -> None:
        """普通因果边与父边共同禁止环，伏笔边不参与因果排序"""
        children: dict[str, set[str]] = {}
        indegree: dict[str, int] = {}
        for parent, child in set(edges):
            children.setdefault(parent, set()).add(child)
            indegree.setdefault(parent, 0)
            indegree[child] = indegree.get(child, 0) + 1
        ready = [key for key, value in indegree.items() if value == 0]
        visited = 0
        while ready:
            current = ready.pop()
            visited += 1
            for child in children.get(current, set()):
                indegree[child] -= 1
                if indegree[child] == 0:
                    ready.append(child)
        if visited != len(indegree):
            raise ValueError(f"事件连接形成环 node_ids={sorted(key for key, value in indegree.items() if value)}")

    def stop(self, author: tuple[str, str]) -> None:
        self.executions.discard(author)

    def confirm(self, work_id: str, invocation_id: str) -> None:
        author = (work_id, invocation_id)
        self.saved.add(author)
        self.stop(author)

    def rollback(self, work_id: str, invocation_id: str) -> None:
        author = (work_id, invocation_id)
        if author in self.saved:
            return
        self.stop(author)
        removed = {key for key, value in self.nodes.items() if value["author"] == author}
        for key in removed:
            self.nodes.pop(key)
        self.connections = {
            key: value
            for key, value in self.connections.items()
            if value["author"] != author and not {value["parent"], value["child"]} & removed
        }
        self.actions = {key: value for key, value in self.actions.items() if value["author"] != author}

    def snapshot(self, author: tuple[str, str]) -> dict[str, Any]:
        return deepcopy({"nodes": self.nodes, "connections": self.connections, "actions": self.actions})

    def restore(self, snapshot: dict[str, Any]) -> None:
        self.nodes = snapshot["nodes"]
        self.connections = snapshot["connections"]
        self.actions = snapshot.get("actions", {})

    def freeze_actions(self, author: tuple[str, str], paragraphs: Any) -> dict[str, dict[str, Any]]:
        """自动埋设和显式动作进入同一冻结贡献，保存确认与恢复按同一份事实核对"""
        from src.fact_graph.evidence import evidence_for

        actions = deepcopy({key: value for key, value in self.actions.items() if value["author"] == author})
        for node_id, node in self.nodes.items():
            if node["author"] != author or not node["content"]["is_foreshadow_setup"]:
                continue
            paragraph = next(row for row in paragraphs if row.paragraph_id == node["content"]["evidence_paragraph_id"])
            operation = f"setup/{node_id}"
            actions[stable_uuid(self.run_id, author[0], operation)] = {
                "author": author,
                "root_event_id": node_id,
                "target_event_id": node_id,
                "action_type": "setup",
                "chapter_id": node["chapter_id"],
                "source_operation_id": operation,
                "operation_order": 0,
                "evidence": [
                    {**item, "text": paragraph.text} for item in evidence_for(paragraphs, paragraph.paragraph_id)
                ],
            }
        return actions

    def search(self, query: str = "") -> list[dict[str, Any]]:
        return [
            self.read(identifier)
            for identifier, node in sorted(self.nodes.items())
            if query.casefold() in node["content"]["description"].casefold()
        ]

    def save_work(self, session: Session, frozen: EventContribution, annotation_id: str) -> None:
        from sqlalchemy import text

        from src.fact_graph.evidence import evidence_for
        from src.storage.models import AnnotationWork, EventEdge, EventNode
        from src.storage.models.foreshadowing_action import ForeshadowingAction

        session.execute(
            text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"), {"key": f"event_trees:{self.run_id}"}
        )
        contribution = frozen.snapshot()
        nodes = contribution["nodes"]
        actions = deepcopy(contribution.get("actions", {}))
        for node_id, node in nodes.items():
            content = node["content"]
            paragraph = next(row for row in frozen.paragraphs if row.paragraph_id == content["evidence_paragraph_id"])
            participants = []
            for participant in content["participants"]:
                name = participant["entity"]
                from src.fact_graph.graph import mention_uuid

                identifier = mention_uuid(self.run_id, node["chapter_id"], name)
                participants.append({**participant, "entity": frozen.entities()[identifier]})
            session.add(
                EventNode(
                    event_id=node_id,
                    run_id=self.run_id,
                    chapter_id=node["chapter_id"],
                    chapter_order=frozen.chapter_order,
                    description=content["description"],
                    participants=participants,
                    anchor_paragraph_ids=[paragraph.paragraph_id],
                    char_start=paragraph.local_start_char,
                    char_end=paragraph.local_end_char,
                    evidence=evidence_for(frozen.paragraphs, paragraph.paragraph_id),
                    causal_event_refs=[],
                    tree_id=content["tree_id"],
                    cause_role=content["cause_role"],
                    is_foreshadowing_root=content["is_foreshadow_setup"],
                    foreshadowing_status="open" if content["is_foreshadow_setup"] else None,
                    payoff_likelihood=content["payoff_likelihood"],
                    strength=content["payoff_likelihood"],
                    annotation_id=annotation_id,
                    source_kind="annotation",
                    payload_path=f"work/{frozen.work_id}/{node_id}",
                    author_work_id=frozen.work_id,
                    producer_invocation_id=frozen.invocation_id,
                    parent_node_id=content["parent_node_id"],
                )
            )
        session.flush()
        for identifier, action in actions.items():
            root = session.get(EventNode, action["root_event_id"])
            if root is None or not root.is_foreshadowing_root:
                raise ValueError(f"root_event_id={action['root_event_id']} 不是已保存伏笔根")
            action_paragraph = next(
                (row for row in frozen.paragraphs if row.paragraph_id == action["evidence"][0]["paragraph_id"]), None
            )
            if action_paragraph is None or action["chapter_id"] != action_paragraph.chapter_id:
                raise ValueError("伏笔动作证据必须属于当前保存章")
            for key in ("root_event_id", "target_event_id"):
                endpoint_id = action.get(key)
                endpoint = session.get(EventNode, endpoint_id) if endpoint_id else None
                if endpoint_id and (endpoint is None or endpoint.run_id != self.run_id):
                    raise ValueError(f"{key}={endpoint_id} 没有有效保存")
                if endpoint is not None and endpoint.chapter_order > frozen.chapter_order:
                    raise ValueError(f"{key}={endpoint_id} 来源章晚于当前动作章")
                if endpoint is not None and endpoint.author_work_id != frozen.work_id:
                    work = session.get(AnnotationWork, endpoint.author_work_id)
                    if work is None or work.state != "saved" or work.invocation_id != endpoint.producer_invocation_id:
                        raise ValueError(f"{key}={endpoint_id} 所属 work 未有效保存")
            if session.get(ForeshadowingAction, identifier) is None:
                session.add(
                    ForeshadowingAction(
                        action_id=identifier,
                        run_id=self.run_id,
                        root_event_id=action["root_event_id"],
                        target_event_id=action.get("target_event_id"),
                        action_type=action["action_type"],
                        chapter_id=action["chapter_id"],
                        chapter_order=frozen.chapter_order,
                        source_work_id=frozen.work_id,
                        source_operation_id=action["source_operation_id"],
                        operation_order=action["operation_order"],
                        evidence=action["evidence"],
                        evidence_scope="paragraph",
                        annotation_id=annotation_id,
                    )
                )
        connections = dict(contribution["connections"])
        for node_id, node in nodes.items():
            content = node["content"]
            if content["parent_node_id"]:
                identifier = stable_uuid(
                    self.run_id, frozen.work_id, content["parent_node_id"], node_id, content["cause_role"]
                )
                connections[identifier] = {
                    "parent": content["parent_node_id"],
                    "child": node_id,
                    "type": content["cause_role"],
                    "author": (frozen.work_id, frozen.invocation_id),
                }
        for identifier, connection in connections.items():
            parent, child = (session.get(EventNode, connection[name]) for name in ("parent", "child"))
            if parent is None or child is None:
                raise ValueError(f"连接端点没有有效保存: {connection}")
            for endpoint in (parent, child):
                if endpoint.author_work_id != frozen.work_id:
                    work = session.get(AnnotationWork, endpoint.author_work_id)
                    if work is None or work.state != "saved" or work.invocation_id != endpoint.producer_invocation_id:
                        raise ValueError(f"node_id={endpoint.event_id} 所属 work 未有效保存")
            if session.get(EventEdge, identifier) is None:
                session.add(
                    EventEdge(
                        edge_id=identifier,
                        run_id=self.run_id,
                        source_event_id=parent.event_id,
                        target_event_id=child.event_id,
                        source_chapter_id=parent.chapter_id,
                        target_chapter_id=child.chapter_id,
                        edge_type="foreshadowing" if connection["type"] == "foreshadowing" else "causal",
                        evidence=evidence_for(frozen.paragraphs),
                        is_active=True,
                        annotation_id=annotation_id,
                        payload_path=f"work/{frozen.work_id}/{identifier}",
                        author_work_id=frozen.work_id,
                        cause_role=None if connection["type"] in {"causal", "foreshadowing"} else connection["type"],
                    )
                )
        session.flush()
        self.rebuild_storage(session)

    def rebuild_structure(self, session: Any) -> None:
        """重折有效父边和整个子树，后续连接不修改生产 work 的不可变输出"""
        from sqlalchemy import select

        from src.storage.models import AnalysisOutput, EventEdge, EventNode

        nodes = {
            row.event_id: row
            for row in session.execute(select(EventNode).where(EventNode.run_id == self.run_id)).scalars()
        }
        base = {
            content["node_id"]: content
            for record in session.execute(
                select(AnalysisOutput).where(
                    AnalysisOutput.run_id == self.run_id, AnalysisOutput.kind == "chapter_annotation"
                )
            ).scalars()
            for content in record.payload["events"]
        }
        causal = (
            session.execute(
                select(EventEdge).where(
                    EventEdge.run_id == self.run_id, EventEdge.edge_type == "causal", EventEdge.is_active.is_(True)
                )
            )
            .scalars()
            .all()
        )
        self._check_dag([(edge.source_event_id, edge.target_event_id) for edge in causal])
        parents: dict[str, str] = {}
        kinds: dict[str, str] = {}
        for edge in session.execute(
            select(EventEdge).where(
                EventEdge.run_id == self.run_id,
                EventEdge.edge_type == "causal",
                EventEdge.cause_role.in_(("main", "secondary")),
                EventEdge.is_active.is_(True),
            )
        ).scalars():
            child, parent = edge.target_event_id, edge.source_event_id
            if child in parents and parents[child] != parent:
                raise ValueError(f"node_id={child} 保存连接产生多个父节点")
            parents[child], kinds[child] = parent, edge.cause_role
        for identifier, node in nodes.items():
            seen: set[str] = set()
            root = identifier
            while root in parents:
                if root in seen:
                    raise ValueError(f"事件保存连接形成环 node_id={root}")
                seen.add(root)
                root = parents[root]
            if root not in nodes:
                raise ValueError(f"事件保存连接端点缺失 node_id={root}")
            node.tree_id = base[root]["tree_id"]
            node.parent_node_id = parents.get(identifier)
            node.cause_role = kinds.get(identifier, "root")
        session.flush()

    def rebuild_storage(self, session: Any) -> None:
        """更新保存后的结构与明确伏笔动作状态，二者使用各自的领域事实"""
        from sqlalchemy import select

        from src.event_trees.action_order import action_order
        from src.storage.models import EventNode
        from src.storage.models.foreshadowing_action import ForeshadowingAction

        self.rebuild_structure(session)
        actions = sorted(
            session.scalars(select(ForeshadowingAction).where(ForeshadowingAction.run_id == self.run_id)),
            key=action_order,
        )
        statuses = {
            action.root_event_id: {"setup": "open", "reinforce": "reinforced", "payoff": "likely_paid_off"}[
                action.action_type
            ]
            for action in actions
        }
        for node in session.scalars(select(EventNode).where(EventNode.run_id == self.run_id)):
            if node.is_foreshadowing_root:
                node.foreshadowing_status = statuses.get(node.event_id, "open")
        session.flush()

    def discard_storage(self, session: Any, work_ids: set[str]) -> None:
        from sqlalchemy import delete, select

        from src.storage.models import EventEdge, EventNode, GraphFact
        from src.storage.models.foreshadowing_action import ForeshadowingAction

        identifiers = list(
            session.execute(
                select(EventNode.event_id).where(
                    EventNode.run_id == self.run_id, EventNode.author_work_id.in_(work_ids)
                )
            ).scalars()
        )
        session.execute(delete(GraphFact).where(GraphFact.event_id.in_(identifiers)))
        session.execute(
            delete(ForeshadowingAction).where(
                ForeshadowingAction.run_id == self.run_id,
                ForeshadowingAction.source_work_id.in_(work_ids)
                | ForeshadowingAction.root_event_id.in_(identifiers)
                | ForeshadowingAction.target_event_id.in_(identifiers),
            )
        )
        session.execute(
            delete(EventEdge).where(
                EventEdge.run_id == self.run_id,
                (EventEdge.author_work_id.in_(work_ids))
                | EventEdge.source_event_id.in_(identifiers)
                | EventEdge.target_event_id.in_(identifiers),
            )
        )
        session.execute(delete(EventNode).where(EventNode.event_id.in_(identifiers)))

    def restore_storage(self, session: Any, records: list[Any]) -> None:
        from sqlalchemy import select

        from src.storage.models import EventEdge

        self.nodes.clear()
        self.connections.clear()
        self.actions.clear()
        self.saved.clear()
        self.executions.clear()
        authors = {record.work_id: (record.work_id, record.invocation_id) for record in records}
        for record in records:
            author = authors[record.work_id]
            self.actions.update(
                self.load_saved_work(session, record.work_id, record.invocation_id, record.output_id)["actions"]
            )
            for content in record.payload["events"]:
                self.nodes[content["node_id"]] = {
                    "author": author,
                    "chapter_id": record.chapter_id,
                    "content": deepcopy(content),
                }
            self.saved.add(author)
        for edge in session.execute(
            select(EventEdge).where(EventEdge.run_id == self.run_id, EventEdge.is_active.is_(True))
        ).scalars():
            self.connections[edge.edge_id] = {
                "parent": edge.source_event_id,
                "child": edge.target_event_id,
                "type": "foreshadowing" if edge.edge_type == "foreshadowing" else edge.cause_role or "causal",
                "author": authors[edge.author_work_id],
            }
        self._parents()

    def load_saved_work(self, session: Any, work_id: str, invocation_id: str, annotation_id: str) -> dict[str, Any]:
        """锁外取得已保存作者的原始节点和实际有效连接"""
        from sqlalchemy import select

        from src.storage.models import AnalysisOutput, EventEdge

        record = session.get(AnalysisOutput, annotation_id)
        if record is None or record.work_id != work_id or record.invocation_id != invocation_id:
            raise ValueError(f"事件保存身份不一致: {work_id}/{invocation_id}")
        author = (work_id, invocation_id)
        nodes = {
            content["node_id"]: {"author": author, "chapter_id": record.chapter_id, "content": deepcopy(content)}
            for content in record.payload["events"]
        }
        connections = {
            edge.edge_id: {
                "parent": edge.source_event_id,
                "child": edge.target_event_id,
                "type": "foreshadowing" if edge.edge_type == "foreshadowing" else edge.cause_role or "causal",
                "author": author,
            }
            for edge in session.execute(
                select(EventEdge).where(
                    EventEdge.run_id == self.run_id, EventEdge.author_work_id == work_id, EventEdge.is_active.is_(True)
                )
            ).scalars()
        }
        from src.storage.models import ForeshadowingAction

        actions = {
            row.action_id: {
                "author": author,
                **{
                    name: getattr(row, name)
                    for name in (
                        "root_event_id",
                        "target_event_id",
                        "action_type",
                        "chapter_id",
                        "source_operation_id",
                        "operation_order",
                        "evidence",
                    )
                },
            }
            for row in session.scalars(
                select(ForeshadowingAction).where(
                    ForeshadowingAction.run_id == self.run_id, ForeshadowingAction.source_work_id == work_id
                )
            )
        }
        return {"author": author, "nodes": nodes, "connections": connections, "actions": actions}

    def recover_work(self, snapshot: dict[str, Any]) -> None:
        """同 run 锁内只替换当前作者的贡献，不恢复全书快照"""
        author = tuple(snapshot["author"])
        self.nodes = {key: value for key, value in self.nodes.items() if value["author"] != author}
        self.connections = {key: value for key, value in self.connections.items() if value["author"] != author}
        self.nodes.update(deepcopy(snapshot["nodes"]))
        self.connections.update(deepcopy(snapshot["connections"]))
        self.actions = {key: value for key, value in self.actions.items() if value["author"] != author}
        self.actions.update(deepcopy(snapshot.get("actions", {})))
        self.saved.add(author)
        self.stop(author)
        self._parents()
