"""不可变章级事件事件及其显式候选关系，正式事件由诊断一次发布"""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from src.storage import new_id
from src.storage.query_terms import query_search_terms, term_matches

CONTRIBUTION_KEYS = ("complete_events", "containments", "ownerships", "relations")


def _event_search_text(content: dict[str, Any]) -> str:
    """拼装事件检索的召回文本

    召回面 = 标题/问题/概要/描述 + 参与者实体名与行动（对齐诊断面三字段口径）；
    词项与通配符语义见 storage.query_terms。
    """
    fields = [str(content.get(name) or "") for name in ("title", "problem", "summary", "description")]
    for item in content.get("participants") or []:
        if not isinstance(item, dict):
            continue
        entity = item.get("entity")
        if isinstance(entity, dict):
            fields.append(str(entity.get("name") or ""))
        else:
            fields.append(str(entity or ""))
        fields.append(str(item.get("action") or ""))
    return "\n".join(value for value in fields if value)


class EventTrees:
    """内存方法只由 agent 在 run 锁内调用，不订阅事件总线"""

    def __init__(self, run_id: str) -> None:
        self.run_id = run_id
        self._identifiers: dict[tuple, str] = {}
        self.nodes: dict[str, dict[str, Any]] = {}
        self.connections: dict[str, dict[str, Any]] = {}
        self.executions: set[str] = set()
        self.saved: set[str] = set()
        self.actions: dict[str, dict[str, Any]] = {}
        self.complete_events: dict[str, dict[str, Any]] = {}
        self.containments: dict[str, dict[str, Any]] = {}
        self.ownerships: dict[str, dict[str, Any]] = {}
        self.relations: dict[str, dict[str, Any]] = {}

    def _identifier(self, *key) -> str:
        """一次冻结内的重复业务键复用已分配身份"""
        if key not in self._identifiers:
            self._identifiers[key] = new_id()
        return self._identifiers[key]

    def begin(self, agent_id: str) -> None:
        self.executions.add(agent_id)

    def sync(self, author: str, chapter_id: int, events: list[Any]) -> None:
        if author not in self.executions:
            raise ValueError(f"事件执行已停止: {author}")
        for event in events:
            content = event.model_dump(mode="json")
            identifier = content["node_id"]
            current = self.nodes.get(identifier)
            if current is not None and (current["author"] != author or current["author"] in self.saved):
                raise ValueError(f"node_id={identifier} 已属于其他或已保存执行")
            if current is not None:
                immutable = {
                    "event_id",
                    "title",
                    "problem",
                    "summary",
                    "event_type",
                    "status",
                    "progress",
                    "from_chapter_id",
                    "to_chapter_id",
                    "reason",
                    "evidence_paragraph_id",
                    "is_foreshadow_setup",
                    "payoff_likelihood",
                }
                if any(current["content"][key] != content[key] for key in immutable):
                    raise ValueError(f"node_id={identifier} 重复节点业务内容冲突")
            self.nodes[identifier] = {"author": author, "chapter_id": chapter_id, "content": deepcopy(content)}
        self._parents()

    def sync_contributions(self, author: str, payloads: dict[str, dict[str, Any]]) -> None:
        """完整事件域挂起记录发布：与节点同一作者纪律（未保存前只允许本 work 重写）"""
        if author not in self.executions:
            raise ValueError(f"事件执行已停止: {author}")
        for key in CONTRIBUTION_KEYS:
            target = getattr(self, key)
            for identifier, content in (payloads.get(key) or {}).items():
                current = target.get(identifier)
                if current is not None and (current["author"] != author or current["author"] in self.saved):
                    raise ValueError(f"{key}={identifier} 已属于其他或已保存执行")
                if current is not None and current["content"] != content:
                    raise ValueError(f"{key}={identifier} 业务内容冲突")
                target[identifier] = {"author": author, "content": deepcopy(content)}
        self._parents()

    def confirmed_complete_event_index(self, *, through_paragraph_id: int | None = None) -> dict[str, dict[str, Any]]:
        "按真实原文可见范围读取已确认全书事件"
        result = {
            key: deepcopy(value["content"])
            for key, value in self.complete_events.items()
            if value["author"] in self.saved
        }
        for identifier, value in result.items():
            value["producer_agent_id"] = self.complete_events[identifier]["author"]
        if through_paragraph_id is not None:
            result = {
                identifier: value
                for identifier, value in result.items()
                if type(value.get("evidence_paragraph_id")) is int
                and 0 <= value["evidence_paragraph_id"] <= through_paragraph_id
            }
        return result

    def confirmed_source_event_ids(self) -> set[str]:
        """本 run 已确认的章级事件来源，供跨章候选关系和伏笔引用授权"""
        return {key for key, value in self.nodes.items() if value["author"] in self.saved}

    def confirmed_containment_parents(self) -> dict[str, str]:
        """本 run 已确认包含关系（child_event_id → parent_event_id）"""
        return {
            str(value["content"]["child_event_id"]): str(value["content"]["parent_event_id"])
            for key, value in self.containments.items()
            if value["author"] in self.saved
        }

    def write_action(self, author: str, value: dict[str, Any]) -> str:
        """明确动作沿用来源操作身份，同章多次动作分别保留"""
        if author not in self.executions or author in self.saved:
            raise ValueError(f"事件执行已停止: {author}")
        identifier = self._identifier(self.run_id, author, value["source_operation_id"])
        action = {**deepcopy(value), "author": author}
        existing = self.actions.get(identifier)
        if existing is not None:
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
        for value in self.containments.values():
            edge = value["content"]
            child, parent = edge["child_event_id"], edge["parent_event_id"]
            if child not in self.nodes or parent not in self.nodes:
                raise ValueError("包含关系端点不存在")
            if child in parents and parents[child] != parent:
                raise ValueError("子事件已有其他直接父")
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
        content = deepcopy(node["content"])
        return {
            "run_id": self.run_id,
            "node_id": node_id,
            "event_id": node_id,
            "kind": "event",
            "producer_agent_id": node["author"],
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
        isforeshadowing: bool | None = None,
    ) -> list[str]:
        """先筛选稳定节点 ID，分页读取详情时不复制整本书的节点正文；伏笔标记过滤在分页前生效

        query 按空白/标点拆分词项、任一命中即召回（% 匹配任意长度、_ 匹配单字符），
        召回面为标题/问题/概要/描述与参与者；空查询不按词项过滤。
        """
        parents = self._parents() if tree_id is not None else {}
        terms = query_search_terms(query)
        values: list[str] = []
        # 与正式过程读取同按正文排序，段内并列节点用稳定身份打破平局
        ordered = sorted(
            self.nodes.items(),
            key=lambda item: (
                item[1]["chapter_id"],
                item[1]["content"]["evidence_paragraph_id"],
                item[0],
            ),
        )
        for identifier, node in ordered:
            if chapter_id is not None and node["chapter_id"] != chapter_id:
                continue
            if isforeshadowing is not None and bool(node["content"]["is_foreshadow_setup"]) != isforeshadowing:
                continue
            if terms:
                haystack = _event_search_text(node["content"])
                if not any(term_matches(term, haystack) for term in terms):
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
        author: str,
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
            if read["producer_agent_id"] != current["producer_agent_id"]:
                raise ValueError(
                    f"node_id={identifier} 读取生产者={read[('producer_agent_id')]} 当前生产者={
                        current['producer_agent_id']
                    }，请重新读取"
                )
            if read["content"] != current["content"]:
                raise ValueError(f"node_id={identifier} 当前业务内容已变化，请重新读取")
            if self.nodes[identifier]["author"] != author and (not current["saved"]):
                raise ValueError(f"node_id={identifier} 属于其他未成功保存执行={current['producer_agent_id']}")
            paragraph_id = current["content"]["evidence_paragraph_id"]
            if paragraph_id not in authorized_paragraphs:
                raise ValueError(f"node_id={identifier} 原文 paragraph_id={paragraph_id} 尚未实际读取")
        connection_id = self._identifier(self.run_id, author, parent, child, kind)
        if kind == "foreshadowing" and (not self.nodes[parent]["content"]["is_foreshadow_setup"]):
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

    def stop(self, author: str) -> None:
        self.executions.discard(author)

    def confirm(self, agent_id: str) -> None:
        self.saved.add(agent_id)
        self.stop(agent_id)

    def rollback(self, agent_id: str) -> None:
        author = agent_id
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
        removed_events = {key for key, value in self.complete_events.items() if value["author"] == author}
        for key in CONTRIBUTION_KEYS:
            setattr(self, key, {k: v for k, v in getattr(self, key).items() if v["author"] != author})
        # 其他 work 的关联不得指向已随回滚消失的事件/过程端点
        self.containments = {
            key: value
            for key, value in self.containments.items()
            if value["content"]["parent_event_id"] not in removed_events and key not in removed_events
        }
        self.ownerships = {
            key: value
            for key, value in self.ownerships.items()
            if key not in removed and value["content"]["owner_event_id"] not in removed_events
        }
        self.relations = {
            key: value
            for key, value in self.relations.items()
            if not self._relation_touches(value["content"], removed_events, removed)
        }

    @staticmethod
    def _relation_touches(content: dict[str, Any], removed_events: set[str], removed_nodes: set[str]) -> bool:
        for kind_field, id_field in (("source_kind", "source_id"), ("target_kind", "target_id")):
            if content[kind_field] == "event" and content[id_field] in removed_events:
                return True
            if content[kind_field] == "process" and content[id_field] in removed_nodes:
                return True
        return False

    def snapshot(self, author: str) -> dict[str, Any]:
        del author
        return deepcopy(
            {
                "nodes": self.nodes,
                "connections": self.connections,
                "actions": self.actions,
                **{key: getattr(self, key) for key in CONTRIBUTION_KEYS},
            }
        )

    def restore(self, snapshot: dict[str, Any]) -> None:
        self.nodes = snapshot["nodes"]
        self.connections = snapshot["connections"]
        self.actions = snapshot.get("actions", {})
        for key in CONTRIBUTION_KEYS:
            setattr(self, key, snapshot.get(key, {}))

    def freeze_actions(self, author: str, paragraphs: Any) -> dict[str, dict[str, Any]]:
        """自动埋设和显式动作进入同一冻结贡献，保存确认与恢复按同一份事实核对"""
        from src.fact_graph.evidence import evidence_for

        actions = deepcopy({key: value for key, value in self.actions.items() if value["author"] == author})
        for node_id, node in self.nodes.items():
            if node["author"] != author or not node["content"]["is_foreshadow_setup"]:
                continue
            paragraph = next(row for row in paragraphs if row.paragraph_id == node["content"]["evidence_paragraph_id"])
            operation = f"setup/{node_id}"
            actions[self._identifier(self.run_id, author, operation)] = {
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

    def restore_storage(self, session: Any, records: list[Any]) -> None:

        self.nodes.clear()
        self.connections.clear()
        self.actions.clear()
        self.saved.clear()
        for key in CONTRIBUTION_KEYS:
            getattr(self, key).clear()
        self.executions.clear()
        for record in records:
            author = str(record.agent_id)
            saved = self.load_saved_work(session, str(record.agent_id), str(record.record_id))
            self.nodes.update(saved["nodes"])
            self.actions.update(saved["actions"])
            for key in CONTRIBUTION_KEYS:
                getattr(self, key).update(saved[key])
            self.saved.add(author)
        self._parents()

    def load_saved_work(self, session: Any, agent_id: str, annotation_id: str) -> dict[str, Any]:
        """锁外取得已保存执行的原始事件、实际有效动作与来源候选关系"""
        from src.event_trees import storage_map as smap

        record = session.reads.event_trees_trees_load_saved_work_1(annotation_id)
        if record is None or record.agent_id != agent_id:
            raise ValueError(f"事件保存身份不一致: {agent_id}")
        author = agent_id
        annotation_events = list(session.reads.event_trees_trees_load_saved_work_2(annotation_id))
        source_event_ids = [row.event_id for row in annotation_events]
        participant_rows = (
            list(session.reads.event_trees_trees_load_saved_work_3(source_event_ids)) if source_event_ids else []
        )
        names: dict[str, str] = {}
        if participant_rows:
            names = {
                row.entity_id: row.canonical_name
                for row in session.reads.event_trees_trees_load_saved_work_6(participant_rows)
            }
        evidence = smap.fetch_evidence(session, "complete_event_id", source_event_ids)
        source = smap.annotation_record_source(session, annotation_id)
        chapter_id = source.chapter_id if source is not None else None
        nodes: dict[str, Any] = {}
        for row in annotation_events:
            payloads = smap.evidence_payloads(session, self.run_id, evidence.get(row.event_id, []))
            content = {
                "event_id": row.event_id,
                "node_id": row.event_id,
                "title": row.title,
                "problem": row.problem,
                "summary": row.summary,
                "event_type": row.event_type,
                "status": row.status,
                "progress": row.progress,
                "from_chapter_id": row.from_chapter_id,
                "to_chapter_id": row.to_chapter_id,
                "reason": row.reason,
                "tree_id": row.event_id,
                "parent_node_id": None,
                "cause_role": "root",
                "description": row.summary,
                "evidence_paragraph_id": payloads[0]["paragraph_id"] if payloads else None,
                "participants": [
                    {
                        "entity": {"entity_id": item.entity_id, "name": names.get(item.entity_id, item.entity_id)},
                        "role": item.role,
                        "narrative_role": item.narrative_role,
                        "action": item.action,
                        "emotion": item.emotion,
                    }
                    for item in participant_rows
                    if item.event_id == row.event_id
                ],
                "is_foreshadow_setup": bool(row.is_foreshadowing_root),
                "payoff_likelihood": row.payoff_likelihood,
            }
            nodes[row.event_id] = {"author": author, "chapter_id": chapter_id, "content": deepcopy(content)}
        actions: dict[str, Any] = {}
        action_rows = list(session.reads.event_trees_trees_load_saved_work_4(agent_id)) if annotation_id else []
        action_evidence = smap.fetch_evidence(session, "foreshadow_action_id", [row.action_id for row in action_rows])
        for row in action_rows:
            actions[row.action_id] = {
                "author": author,
                "root_event_id": row.source_event_id,
                "target_event_id": row.target_event_id,
                "action_type": row.action_type,
                "chapter_id": chapter_id,
                "source_operation_id": row.source_operation_local_key,
                "operation_order": int(row.operation_order),
                "evidence": smap.evidence_payloads(session, self.run_id, action_evidence.get(row.action_id, [])),
            }
        relations = {
            row.link_id: {
                "author": author,
                "content": {
                    "relation_id": row.link_id,
                    "source_kind": "event",
                    "source_id": row.semantic_source_event_id,
                    "target_kind": "event",
                    "target_id": row.semantic_target_event_id,
                    "relation_type": row.relation_type,
                    "reason": row.reason,
                    "source_operation_id": row.source_operation_local_key,
                },
            }
            for row in session.reads.event_trees_trees_load_saved_work_5(agent_id)
            if row.semantic_source_event_id is not None
        }
        containments = {
            row.link_id: {
                "author": author,
                "content": {
                    "link_id": row.link_id,
                    "parent_event_id": row.contained_parent_id,
                    "child_event_id": row.contained_child_id,
                    "reason": row.reason,
                },
            }
            for row in session.reads.event_trees_trees_load_saved_work_5(agent_id)
            if row.contained_child_id is not None
        }
        return {
            "author": author,
            "nodes": nodes,
            "connections": {},
            "actions": actions,
            **{key: {} for key in CONTRIBUTION_KEYS},
            "relations": relations,
            "containments": containments,
        }

    def recover_work(self, snapshot: dict[str, Any]) -> None:
        """同 run 锁内只替换当前作者的贡献，不恢复全书快照"""
        author = str(snapshot["author"])
        self.nodes = {key: value for key, value in self.nodes.items() if value["author"] != author}
        self.connections = {key: value for key, value in self.connections.items() if value["author"] != author}
        self.nodes.update(deepcopy(snapshot["nodes"]))
        self.connections.update(deepcopy(snapshot["connections"]))
        self.actions = {key: value for key, value in self.actions.items() if value["author"] != author}
        self.actions.update(deepcopy(snapshot.get("actions", {})))
        for key in CONTRIBUTION_KEYS:
            target = getattr(self, key)
            retained = {identifier: value for identifier, value in target.items() if value["author"] != author}
            retained.update(deepcopy(snapshot.get(key, {})))
            setattr(self, key, retained)
        self.saved.add(author)
        self.stop(author)
        self._parents()
