"""不可变章级事件声明及其显式候选关系，正式事件由诊断一次发布"""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from sqlalchemy.orm import Session

from src.event_trees.contributions import EventContribution
from src.storage.query_terms import query_search_terms, term_matches
from src.utils.identity import stable_uuid

# 完整事件域集合名：快照/回滚/冻结/保存共用同一份声明
CONTRIBUTION_KEYS = (
    "complete_events",
    "revisions",
    "containments",
    "ownerships",
    "relations",
    "conflicts",
)


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
        self.nodes: dict[str, dict[str, Any]] = {}
        self.connections: dict[str, dict[str, Any]] = {}
        self.executions: set[str] = set()
        self.saved: set[str] = set()
        self.actions: dict[str, dict[str, Any]] = {}
        # 完整事件域：event_id/revision_id/child_event_id/process_id/structure_id/
        # relation_id/conflict_id → {"author": execution_id, "content": {...}}
        self.complete_events: dict[str, dict[str, Any]] = {}
        self.revisions: dict[str, dict[str, Any]] = {}
        self.containments: dict[str, dict[str, Any]] = {}
        self.ownerships: dict[str, dict[str, Any]] = {}
        self.relations: dict[str, dict[str, Any]] = {}
        self.conflicts: dict[str, dict[str, Any]] = {}

    def begin(self, execution_id: str) -> None:
        self.executions.add(execution_id)

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
                    "declaration_id",
                    "title",
                    "problem",
                    "summary",
                    "event_type",
                    "status",
                    "progress",
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

    def confirmed_complete_event_index(self, *, through_paragraph_id: int | None = None) -> dict[str, dict[str, Any]]:
        """按真实原文可见范围读取已确认当前版本，未来来源整项拒绝，不回退旧版本"""
        result = {
            key: deepcopy(value["content"])
            for key, value in self.complete_events.items()
            if value["author"] in self.saved
        }
        for identifier, value in result.items():
            author = self.complete_events[identifier]["author"]
            value["producer_invocation_id"] = author
            value["revisions"] = [
                {
                    "summary": value["summary"],
                    "progress": value["progress"],
                    "status": value["status"],
                    "producer_invocation_id": author,
                    "source_operation_id": f"create/{value['local_key']}",
                    "evidence_paragraph_id": value["evidence_paragraph_id"],
                }
            ]
            value["current_revision"] = value["revisions"][0]
            value["current_revision_id"] = stable_uuid(
                self.run_id, author, "event_revision", f"create/{value['local_key']}"
            )
        revisions = [
            {**value["content"], "producer_invocation_id": value["author"]}
            for value in self.revisions.values()
            if value["author"] in self.saved
        ]
        pending = list(revisions)
        while pending:
            ready = [
                value
                for value in pending
                if value["previous_revision_id"] is None
                or value["previous_revision_id"] == result[value["event_id"]]["current_revision_id"]
            ]
            if not ready:
                raise ValueError("已确认事件版本链无法恢复")
            for value in ready:
                result[value["event_id"]].update({key: value[key] for key in ("summary", "progress", "status")})
                result[value["event_id"]]["current_revision_id"] = value["revision_id"]
                result[value["event_id"]]["revisions"].append(value)
                result[value["event_id"]]["current_revision"] = value
                pending.remove(value)
        if through_paragraph_id is not None:
            # 段号仅限制原文来源，不推断事实发生时间；初始声明和版本链都必须当前可见
            result = {
                identifier: value
                for identifier, value in result.items()
                if all(
                    type(revision.get("evidence_paragraph_id")) is int
                    and 0 <= revision["evidence_paragraph_id"] <= through_paragraph_id
                    for revision in value["revisions"]
                )
            }
        return result

    def confirmed_declaration_ids(self) -> set[str]:
        """本 run 已确认的章级声明来源，供跨章候选关系和伏笔引用授权"""
        return {key for key, value in self.nodes.items() if value["author"] in self.saved}

    def confirmed_containment_parents(self) -> dict[str, str]:
        """本 run 已确认包含关系（child_event_id → parent_event_id）"""
        return {
            key: str(value["content"]["parent_event_id"])
            for key, value in self.containments.items()
            if value["author"] in self.saved
        }

    def write_action(self, author: str, value: dict[str, Any]) -> str:
        """明确动作沿用来源操作身份，同章多次动作分别保留"""
        if author not in self.executions or author in self.saved:
            raise ValueError(f"事件执行已停止: {author}")
        identifier = stable_uuid(self.run_id, author, value["source_operation_id"])
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
        content = deepcopy(node["content"])
        return {
            "run_id": self.run_id,
            "node_id": node_id,
            "declaration_id": node_id,
            "kind": "declaration",
            "producer_invocation_id": node["author"],
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
            if read["producer_invocation_id"] != current["producer_invocation_id"]:
                raise ValueError(
                    f"node_id={identifier} 读取生产者={read['producer_invocation_id']} "
                    f"当前生产者={current['producer_invocation_id']}，请重新读取"
                )
            if read["content"] != current["content"]:
                raise ValueError(f"node_id={identifier} 当前业务内容已变化，请重新读取")
            if self.nodes[identifier]["author"] != author and not current["saved"]:
                raise ValueError(
                    f"node_id={identifier} 属于其他未成功保存执行={current['producer_invocation_id']}"
                )
            paragraph_id = current["content"]["evidence_paragraph_id"]
            if paragraph_id not in authorized_paragraphs:
                raise ValueError(f"node_id={identifier} 原文 paragraph_id={paragraph_id} 尚未实际读取")
        connection_id = stable_uuid(self.run_id, author, parent, child, kind)
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

    def stop(self, author: str) -> None:
        self.executions.discard(author)

    def confirm(self, execution_id: str) -> None:
        self.saved.add(execution_id)
        self.stop(execution_id)

    def rollback(self, execution_id: str) -> None:
        author = execution_id
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
        self.revisions = {
            key: value for key, value in self.revisions.items() if value["content"]["event_id"] not in removed_events
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
            actions[stable_uuid(self.run_id, author, operation)] = {
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
        """只保存章级声明与动作来源，全书事件及其正式端点等待诊断发布

        声明进 event_declarations，参与者进 declaration_participants，证据进
        source_evidence（declaration 所有者列）；伏笔动作进 event_foreshadowing_actions
        （证据 owner 为动作）。
        """
        from sqlalchemy import text

        from src.event_trees import storage_map as smap
        from src.fact_graph.evidence import evidence_for
        from src.fact_graph.graph import entity_uuid
        from src.storage.models import (
            ChapterAnnotation,
            DeclarationParticipant,
            EventDeclaration,
            EventForeshadowingAction,
            GraphFact,
        )

        session.execute(
            text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"), {"key": f"event_trees:{self.run_id}"}
        )
        contribution = frozen.snapshot()
        # 正式来源必须是本执行的真实标注记录；标注行存在即成功保存事实
        record = session.get(ChapterAnnotation, annotation_id)
        if (
            record is None
            or record.execution_id != frozen.execution_id
            or record.contract_version != "event-tree-declarations-v1"
        ):
            raise ValueError("事件保存必须引用本执行的真实标注记录")
        source = smap.declaration_record_source(session, annotation_id)
        if source is None or source[0] != frozen.execution_id or source[1] != self.run_id:
            raise ValueError("事件保存的标注记录不属于本执行或本 run")
        for declaration_id, node in contribution["nodes"].items():
            content = node["content"]
            paragraph = next(row for row in frozen.paragraphs if row.paragraph_id == content["evidence_paragraph_id"])
            refs = contribution.get("process_evidence", {}).get(declaration_id) or evidence_for(
                frozen.paragraphs, paragraph.paragraph_id
            )
            participants = [
                {**item, "entity": frozen.entities()[entity_uuid(self.run_id, str(item["entity"]))]}
                for item in content["participants"]
            ]
            # local_key 优先取生产账本的真实 EL 本地地址；账本未随贡献下传时退回来源容器键
            local_key = str(contribution.get("event_local_keys", {}).get(declaration_id) or content["node_id"])
            session.add(
                EventDeclaration(
                    declaration_id=declaration_id,
                    record_id=annotation_id,
                    local_key=local_key[:255],
                    title=content["title"],
                    problem=content["problem"],
                    summary=content["summary"],
                    event_type=content["event_type"],
                    status=content["status"],
                    progress=content["progress"],
                    is_foreshadowing_root=bool(content["is_foreshadow_setup"]),
                    payoff_likelihood=content["payoff_likelihood"],
                )
            )
            # 声明行必须先落库：参与者与其观测事实的外键没有 ORM relationship 可推导插入顺序
            session.flush()
            for ordinal, item in enumerate(participants):
                entity = item.get("entity") or {}
                entity_id = str(entity.get("entity_id") or entity.get("name") or "")
                if not entity_id:
                    raise ValueError(f"声明参与者缺少正式实体身份: declaration_id={declaration_id}")
                narrative_role = item.get("narrative_role")
                action = item.get("action")
                emotion = None if item.get("emotion") is None else int(item["emotion"])
                participant_id = str(stable_uuid("declaration_participant", declaration_id, str(ordinal)))
                session.add(
                    DeclarationParticipant(
                        participant_id=participant_id,
                        declaration_id=declaration_id,
                        participant_ordinal=ordinal,
                        entity_id=entity_id,
                        role=str(item.get("role") or ""),
                        narrative_role=narrative_role,
                        action=action,
                        emotion=emotion,
                    )
                )
                # 参与者事实随声明与参与者同事务写一行，不按三态取值筛选；作者与实体从
                # 参与者来源取，不另填生产执行或操作序号
                session.flush()
                fact = GraphFact(participant_id=participant_id)
                session.add(fact)
                # 事实自身携带原文证据：与其余事实形状走同一证据路径
                session.flush()
                smap.write_evidence_rows(session, {"graph_fact_id": fact.graph_fact_id}, refs)
            smap.write_evidence_rows(session, {"declaration_id": declaration_id}, refs)
        session.flush()
        for identifier, action in contribution.get("actions", {}).items():
            source_row = session.get(EventDeclaration, action["root_event_id"])
            if source_row is None or not source_row.is_foreshadowing_root:
                raise ValueError(f"source_declaration_id={action['root_event_id']} 缺少有效伏笔声明")
            # 端点可以来自本 run 任意 work 的已保存声明（跨章伏笔的强化/回收）：
            # 声明只在记录提交后存在，记录链有效即为"来源 work 已有效保存"，
            # 不区分同 work/跨 work
            for field, endpoint_id in (
                ("source_declaration_id", action["root_event_id"]),
                ("target_declaration_id", action.get("target_event_id")),
            ):
                if endpoint_id is None:
                    continue
                endpoint = session.get(EventDeclaration, endpoint_id)
                endpoint_source = (
                    smap.declaration_record_source(session, endpoint.record_id) if endpoint is not None else None
                )
                if endpoint_source is None or endpoint_source[1] != self.run_id:
                    raise ValueError(f"{field}={endpoint_id} 不属于本运行")
                if endpoint_source[3] > frozen.chapter_order:
                    raise ValueError(f"{field}={endpoint_id} 来源章晚于当前章")
            allowed_paragraphs = {row.paragraph_id for row in frozen.paragraphs}
            if not action["evidence"] or any(
                ref.get("paragraph_id") not in allowed_paragraphs for ref in action["evidence"]
            ):
                raise ValueError("伏笔动作须引用当前work真实原文段落")
            session.add(
                EventForeshadowingAction(
                    action_id=identifier,
                    producer_execution_id=frozen.execution_id,
                    source_operation_local_key=str(action["source_operation_id"])[:128],
                    operation_order=int(action["operation_order"]),
                    action_type=action["action_type"],
                    source_declaration_id=action["root_event_id"],
                    target_declaration_id=action.get("target_event_id"),
                )
            )
            smap.write_evidence_rows(session, {"foreshadow_action_id": identifier}, action["evidence"])
        from src.event_trees.persistence import save_declaration_contribution

        save_declaration_contribution(session, frozen, annotation_id)
        session.flush()

    def rebuild_storage(self, session: Any) -> None:
        """章级来源不可变，恢复不折叠或回写正式结构和伏笔状态"""
        session.flush()

    def discard_storage(self, session: Any, execution_ids: set[str]) -> None:
        """只撤销本执行尚未进入正式发布的声明、动作与来源候选"""
        from sqlalchemy import delete, select

        from src.storage.models import (
            ChapterAnnotation,
            EventDeclaration,
            EventForeshadowingAction,
            GraphFact,
        )

        identifiers = list(
            session.execute(
                select(EventDeclaration.declaration_id).where(
                    EventDeclaration.record_id.in_(
                        select(ChapterAnnotation.record_id).where(
                            ChapterAnnotation.execution_id.in_(sorted(execution_ids))
                        )
                    )
                )
            ).scalars()
        )
        from src.event_trees.persistence import discard_declaration_contributions

        discard_declaration_contributions(session, self.run_id, execution_ids, identifiers)
        session.execute(delete(GraphFact).where(GraphFact.declaration_id.in_(identifiers)))
        session.execute(
            delete(EventForeshadowingAction).where(
                (EventForeshadowingAction.producer_execution_id.in_(sorted(execution_ids)))
                | (EventForeshadowingAction.source_declaration_id.in_(identifiers))
                | (EventForeshadowingAction.target_declaration_id.in_(identifiers))
            )
        )
        session.execute(delete(EventDeclaration).where(EventDeclaration.declaration_id.in_(identifiers)))

    def restore_storage(self, session: Any, records: list[Any]) -> None:

        self.nodes.clear()
        self.connections.clear()
        self.actions.clear()
        self.saved.clear()
        for key in CONTRIBUTION_KEYS:
            getattr(self, key).clear()
        self.executions.clear()
        for record in records:
            author = str(record.execution_id)
            saved = self.load_saved_work(session, str(record.execution_id), str(record.record_id))
            self.nodes.update(saved["nodes"])
            self.actions.update(saved["actions"])
            for key in CONTRIBUTION_KEYS:
                getattr(self, key).update(saved[key])
            self.saved.add(author)
        self._parents()

    def load_saved_work(self, session: Any, execution_id: str, annotation_id: str) -> dict[str, Any]:
        """锁外取得已保存执行的原始声明、实际有效动作与来源候选关系"""
        from sqlalchemy import select

        from src.event_trees import storage_map as smap
        from src.storage.models import (
            ChapterAnnotation,
            DeclarationParticipant,
            EventDeclaration,
            EventForeshadowingAction,
            GraphEntity,
            NarrativeLink,
        )

        record = session.get(ChapterAnnotation, annotation_id)
        if (
            record is None
            or record.execution_id != execution_id
            or record.contract_version != "event-tree-declarations-v1"
        ):
            raise ValueError(f"事件保存身份不一致: {execution_id}")
        author = execution_id
        declarations = list(
            session.scalars(select(EventDeclaration).where(EventDeclaration.record_id == annotation_id))
        )
        declaration_ids = [row.declaration_id for row in declarations]
        participant_rows = (
            list(
                session.scalars(
                    select(DeclarationParticipant)
                    .where(DeclarationParticipant.declaration_id.in_(declaration_ids))
                    .order_by(DeclarationParticipant.declaration_id, DeclarationParticipant.participant_ordinal)
                )
            )
            if declaration_ids
            else []
        )
        names: dict[str, str] = {}
        if participant_rows:
            names = {
                row.entity_id: row.canonical_name
                for row in session.scalars(
                    select(GraphEntity).where(GraphEntity.entity_id.in_({row.entity_id for row in participant_rows}))
                )
            }
        from src.storage.models import SourceEvidence

        evidence = smap.fetch_evidence(session, SourceEvidence.declaration_id, declaration_ids)
        source = smap.declaration_record_source(session, annotation_id)
        chapter_id = source[2] if source is not None else None
        nodes: dict[str, Any] = {}
        for row in declarations:
            payloads = smap.evidence_payloads(session, self.run_id, evidence.get(row.declaration_id, []))
            content = {
                "declaration_id": row.declaration_id,
                "node_id": row.declaration_id,
                "title": row.title,
                "problem": row.problem,
                "summary": row.summary,
                "event_type": row.event_type,
                "status": row.status,
                "progress": row.progress,
                "tree_id": row.declaration_id,
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
                    if item.declaration_id == row.declaration_id
                ],
                "is_foreshadow_setup": bool(row.is_foreshadowing_root),
                "payoff_likelihood": row.payoff_likelihood,
            }
            nodes[row.declaration_id] = {"author": author, "chapter_id": chapter_id, "content": deepcopy(content)}
        actions: dict[str, Any] = {}
        action_rows = (
            list(
                session.scalars(
                    select(EventForeshadowingAction).where(
                        EventForeshadowingAction.producer_execution_id == execution_id
                    )
                )
            )
            if annotation_id
            else []
        )
        action_evidence = smap.fetch_evidence(
            session, SourceEvidence.foreshadow_action_id, [row.action_id for row in action_rows]
        )
        for row in action_rows:
            actions[row.action_id] = {
                "author": author,
                "root_event_id": row.source_declaration_id,
                "target_event_id": row.target_declaration_id,
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
                    "source_kind": "declaration",
                    "source_id": row.semantic_source_declaration_id,
                    "target_kind": "declaration",
                    "target_id": row.semantic_target_declaration_id,
                    "relation_type": row.relation_type,
                    "reason": row.reason,
                    "source_operation_id": row.source_operation_local_key,
                },
            }
            for row in session.scalars(
                select(NarrativeLink).where(
                    NarrativeLink.producer_execution_id == execution_id,
                    NarrativeLink.semantic_source_declaration_id.is_not(None),
                )
            )
        }
        return {
            "author": author,
            "nodes": nodes,
            "connections": {},
            "actions": actions,
            **{key: {} for key in CONTRIBUTION_KEYS},
            "relations": relations,
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
