"""不可变章级事件及其显式候选关系"""

from __future__ import annotations

from collections.abc import Sequence
from copy import deepcopy
from typing import Any

from src.event_trees.queues import QueueGraph
from src.event_trees.semantic import (
    best_paragraph_rank,
    paragraph_ranks,
    ranked_keys,
)
from src.storage import new_id
from src.storage.query_terms import query_search_terms, term_matches

CONTRIBUTION_KEYS = ("complete_events", "queues", "queue_references", "ownerships", "relations")


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
        self.queues: dict[str, dict[str, Any]] = {}
        self.queue_references: dict[str, dict[str, Any]] = {}
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
            if key in {"queues", "queue_references"}:
                for identifier in list(target):
                    if target[identifier]["author"] == author and identifier not in payloads.get(key, {}):
                        if author in self.saved:
                            raise ValueError("正式队列及父子引用不可撤回")
                        target.pop(identifier)
            for identifier, content in (payloads.get(key) or {}).items():
                current = target.get(identifier)
                if current is not None and (current["author"] != author or current["author"] in self.saved):
                    raise ValueError(f"{key}={identifier} 已属于其他或已保存执行")
                target[identifier] = {"author": author, "content": deepcopy(content)}
        self._parents()

    def drop_queue(self, author: str, tree_id: str) -> None:
        """用于撤回本执行尚未保存的事件树、成员事件及其连接"""
        if author not in self.executions:
            raise ValueError(f"事件执行已停止: {author}")
        content = self.queues.get(tree_id)
        if content is None:
            return
        if content["author"] != author or content["author"] in self.saved:
            raise ValueError("正式事件树不可撤回")
        for key, value in list(self.queue_references.items()):
            edge = value["content"]
            if tree_id in {edge["parent_tree_id"], edge["child_tree_id"]}:
                if value["author"] != author or value["author"] in self.saved:
                    raise ValueError("正式父子引用不可撤回")
                del self.queue_references[key]
        members = list(content["content"]["event_ids"])
        del self.queues[tree_id]
        for identifier in members:
            node = self.nodes.get(identifier)
            if node is None:
                continue
            if node["author"] != author or node["author"] in self.saved:
                raise ValueError("正式事件不可撤回")
            del self.nodes[identifier]
        doomed = set(members)
        for key, connection in list(self.connections.items()):
            if connection["parent"] in doomed or connection["child"] in doomed:
                if connection["author"] != author or connection["author"] in self.saved:
                    raise ValueError("正式事件连接不可撤回")
                del self.connections[key]
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

    def graph(
        self, author: str | None = None, *, require_complete: bool = False, include_unpublished: bool = False
    ) -> QueueGraph:
        def visible(value: dict[str, Any]) -> bool:
            return include_unpublished or value["author"] in self.saved or value["author"] == author

        queues = {key: value["content"]["event_ids"] for key, value in self.queues.items() if visible(value)}
        references = [
            (value["content"]["parent_tree_id"], value["content"]["child_tree_id"])
            for value in self.queue_references.values()
            if visible(value)
        ]
        return QueueGraph(
            queues,
            references,
            [key for key, value in self.nodes.items() if visible(value)],
            require_complete=require_complete,
        )

    def _parents(self) -> dict[str, list[str]]:
        graph = self.graph(include_unpublished=True)
        return {key: graph.event_parents(key) for key in graph.event_tree if graph.event_parents(key)}

    def read(self, node_id: str, *, author: str | None = None) -> dict[str, Any]:
        node = self.nodes.get(node_id)
        if node is None:
            raise ValueError(f"node_id={node_id} 当前不存在")
        if node["author"] not in self.saved and node["author"] != author:
            raise ValueError("不能读取其他执行尚未保存的事件或队列")
        content = deepcopy(node["content"])
        graph = self.graph(author)
        return {
            "run_id": self.run_id,
            "node_id": node_id,
            "event_id": node_id,
            "kind": "event",
            "producer_agent_id": node["author"],
            "chapter_id": node["chapter_id"],
            "saved": node["author"] in self.saved,
            "content": content,
            "tree_id": graph.event_tree.get(node_id),
            "tree_event_ids": list(graph.queues[graph.event_tree[node_id]]) if node_id in graph.event_tree else [],
            "event_line_ids": graph.event_lines(node_id) if node_id in graph.event_tree else [],
        }

    def search_ids(
        self,
        query: str = "",
        *,
        chapter_id: int | None = None,
        tree_id: str | None = None,
        isforeshadowing: bool | None = None,
        author: str | None = None,
        semantic_paragraph_ids: Sequence[int] | None = None,
    ) -> list[str]:
        """先筛选稳定节点 ID，分页读取详情时不复制整本书的节点正文；伏笔标记过滤在分页前生效

        query 按空白/标点拆分词项、任一命中即召回（% 匹配任意长度、_ 匹配单字符），
        召回面为标题/问题/概要/描述与参与者；semantic_paragraph_ids 命中的证据段落追加召回，
        词项命中排在语义命中之前；空查询不按词项过滤。
        """
        graph = self.graph(author)
        terms = query_search_terms(query)
        ranks = paragraph_ranks(semantic_paragraph_ids or [])
        values: list[str] = []
        semantic_nodes: list[dict[str, Any]] = []
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
            if node["author"] not in self.saved and node["author"] != author:
                continue
            if chapter_id is not None and node["chapter_id"] != chapter_id:
                continue
            if isforeshadowing is not None and bool(node["content"]["is_foreshadow_setup"]) != isforeshadowing:
                continue
            if tree_id is not None:
                if identifier not in graph.event_tree or (
                    graph.event_tree[identifier] != tree_id and tree_id not in graph.event_lines(identifier)
                ):
                    continue
            if not terms or any(term_matches(term, _event_search_text(node["content"])) for term in terms):
                values.append(identifier)
            elif ranks and best_paragraph_rank(node, ranks) is not None:
                semantic_nodes.append({**node, "event_id": identifier})
        if ranks:
            matched = set(values)
            values.extend(
                identifier
                for identifier in ranked_keys(semantic_nodes, ranks, lambda item: item["event_id"])
                if identifier not in matched
            )
        return values

    def _visible_nodes(self, author: str | None) -> dict[str, dict[str, Any]]:
        "本执行可见的事件节点：已保存事件与自己的草稿"
        return {
            identifier: node
            for identifier, node in self.nodes.items()
            if node["author"] in self.saved or node["author"] == author
        }

    def participant_names_for_paragraphs(
        self, paragraph_ids: Sequence[int], *, author: str | None = None
    ) -> list[str]:
        "语义命中段落所属事件的参与者名字，按段落相似顺序去重"
        ranks = paragraph_ranks(paragraph_ids)
        if not ranks:
            return []
        nodes = [
            {**node, "event_id": identifier}
            for identifier, node in self._visible_nodes(author).items()
            if best_paragraph_rank(node, ranks) is not None
        ]
        ordered = sorted(
            nodes,
            key=lambda item: (best_paragraph_rank(item, ranks), item["event_id"]),
        )
        names: list[str] = []
        seen: set[str] = set()
        for node in ordered:
            for item in node["content"].get("participants") or []:
                entity = item.get("entity") if isinstance(item, dict) else None
                name = entity.get("name") if isinstance(entity, dict) else entity
                if isinstance(name, str) and name and name not in seen:
                    seen.add(name)
                    names.append(name)
        return names

    def tree_ids_for_paragraphs(self, paragraph_ids: Sequence[int], *, author: str | None = None) -> list[str]:
        "语义命中段落所属事件树身份，按段落相似顺序去重"
        ranks = paragraph_ranks(paragraph_ids)
        if not ranks:
            return []
        graph = self.graph(author)
        nodes = [
            {**node, "event_id": identifier, "tree_id": graph.event_tree.get(identifier)}
            for identifier, node in self._visible_nodes(author).items()
            if best_paragraph_rank(node, ranks) is not None
        ]
        return ranked_keys(nodes, ranks, lambda item: item["tree_id"])

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
            current = self.read(identifier, author=author)
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

    def write_action(self, author: str, value: dict[str, Any]) -> str:
        "记录当前执行的显式伏笔动作，同一来源操作幂等保存"
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
        removed_trees = {key for key, value in self.queues.items() if value["author"] == author}
        for key in CONTRIBUTION_KEYS:
            setattr(self, key, {k: v for k, v in getattr(self, key).items() if v["author"] != author})
        # 其他 work 的父子引用不得指向已随回滚消失的事件树
        self.queue_references = {
            key: value
            for key, value in self.queue_references.items()
            if not ({value["content"]["parent_tree_id"], value["content"]["child_tree_id"]} & removed_trees)
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
        from src.text_processing.evidence import evidence_for

        actions = deepcopy({key: value for key, value in self.actions.items() if value["author"] == author})
        for node_id, node in self.nodes.items():
            if node["author"] != author or not node["content"]["is_foreshadow_setup"]:
                continue
            paragraph = next(row for row in paragraphs if row.paragraph_id == node["content"]["evidence_paragraph_id"])
            operation = f"setup/{node_id}"
            actions[self._identifier(self.run_id, author, operation)] = {
                "author": author,
                "source_event_id": node_id,
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
        queue_links: dict[str, list[Any]] = {}
        for row in session.reads.events.list_queue_links(self.run_id):
            queue_links.setdefault(str(row.producer_agent_id), []).append(row)
        tree_rows: dict[str, list[Any]] = {}
        for row in session.reads.events.list_execution_trees(
            [record.agent_id for record in records]
        ):
            tree_rows.setdefault(str(row.producer_agent_id), []).append(row)
        for record in records:
            author = str(record.agent_id)
            saved = self.load_saved_work(
                session,
                author,
                str(record.record_id),
                queue_links.get(author, []),
                tree_rows.get(author, []),
            )
            self.nodes.update(saved["nodes"])
            self.actions.update(saved["actions"])
            for key in CONTRIBUTION_KEYS:
                getattr(self, key).update(saved[key])
            self.saved.add(author)
        self._parents()

    def load_saved_work(
        self,
        session: Any,
        agent_id: str,
        annotation_id: str,
        queue_links: list[Any] | None = None,
        tree_rows: list[Any] | None = None,
    ) -> dict[str, Any]:
        """锁外取得已保存执行的原始事件、实际有效动作与来源候选关系"""
        from src.event_trees import storage_map as smap

        record = session.reads.annotations.get_output(annotation_id)
        if record is None or record.agent_id != agent_id:
            raise ValueError(f"事件保存身份不一致: {agent_id}")
        author = agent_id
        annotation_events = list(session.reads.events.list_output_events(annotation_id))
        source_event_ids = [row.event_id for row in annotation_events]
        participant_rows = (
            list(session.reads.events.list_saved_participants(source_event_ids)) if source_event_ids else []
        )
        names: dict[str, str] = {}
        if participant_rows:
            names = {
                row.entity_id: row.canonical_name
                for row in session.reads.graph.list_saved_participant_entities(participant_rows)
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
                "tree_id": None,
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
        action_rows = list(session.reads.events.list_execution_actions(agent_id)) if annotation_id else []
        action_evidence = smap.fetch_evidence(session, "foreshadow_action_id", [row.action_id for row in action_rows])
        for row in action_rows:
            actions[row.action_id] = {
                "author": author,
                "source_event_id": row.source_event_id,
                "target_event_id": row.target_event_id,
                "action_type": row.action_type,
                "chapter_id": chapter_id,
                "source_operation_id": row.source_operation_local_key,
                "operation_order": int(row.operation_order),
                "evidence": smap.evidence_payloads(session, self.run_id, action_evidence.get(row.action_id, [])),
            }
        producer_links = list(session.reads.events.list_producer_links(agent_id))
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
            for row in producer_links
            if row.semantic_source_event_id is not None
        }
        queue_references = {
            row.link_id: {
                "author": author,
                "content": {
                    "link_id": row.link_id,
                    "parent_tree_id": row.parent_tree_id,
                    "child_tree_id": row.child_tree_id,
                    "reason": row.reason,
                },
            }
            for row in producer_links
            if row.child_tree_id is not None
        }
        queues: dict[str, dict[str, Any]] = {}
        if tree_rows is None:
            tree_rows = list(session.reads.events.list_execution_trees([agent_id]))
        for row in tree_rows:
            if row.producer_agent_id == agent_id:
                queues[row.group_id] = {
                    "author": agent_id,
                    "content": {
                        "tree_id": row.group_id,
                        "tree_key": row.tree_key,
                        "title": row.title,
                        "description": row.description,
                        "event_ids": [],
                        "reason": "",
                        "member_rows": [],
                    },
                }
        if queue_links is None:
            queue_links = session.reads.events.list_queue_links(self.run_id)
        for row in queue_links:
            if row.tree_id is not None and row.producer_agent_id == agent_id:
                queues.setdefault(
                    row.tree_id,
                    {
                        "author": agent_id,
                        "content": {
                            "tree_id": row.tree_id,
                            "tree_key": None,
                            "title": "",
                            "description": "",
                            "event_ids": [],
                            "reason": row.reason,
                            "member_rows": [],
                        },
                    },
                )["content"]["member_rows"].append(row)
        for tree_id, value in queues.items():
            rows = value["content"].pop("member_rows")
            rows.sort(key=lambda row: row.position)
            value["content"]["event_ids"] = [row.member_event_id for row in rows]
            if rows and not value["content"]["reason"]:
                value["content"]["reason"] = rows[0].reason
            for row in rows:
                node = nodes.get(row.member_event_id)
                if node is not None:
                    node["content"]["tree_id"] = tree_id
        return {
            "author": author,
            "nodes": nodes,
            "connections": {},
            "actions": actions,
            **{key: {} for key in CONTRIBUTION_KEYS},
            "relations": relations,
            "queue_references": queue_references,
            "queues": queues,
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
