"""agent 内部业务工具，直接读取和修改三个全书域"""

from __future__ import annotations

import json
import unicodedata
from copy import deepcopy
from typing import Any, Literal

from pydantic import TypeAdapter

from src.agents.annotation.event_inputs import AnnotationEventItem, ParticipantArg
from src.agents.tools import tool
from src.case_pool.policy import event_case_tree_id
from src.storage.ids import new_id

from .agent_constructors import build_batch_agent_events, normalize_event_el, register_agent_event
from .ir_contract import ROLE_NAMESPACE_SEP
from .ir_validation import namespace_event_el, namespace_event_el_once
from .semantic_lookup import SemanticLookup
from .shared_tools import build_case_tools, build_finish_tool, build_state_read_tools
from .tool_factories import build_annotation_tools
from .tools import _forbid_undeclared_args


class AnnotationEventSource:
    "按当前执行身份读取正式事件及自身草稿"

    def __init__(self, events: Any, author: str) -> None:
        self.events, self.author = events, author

    def read(self, identifier: str) -> dict[str, Any]:
        return self.events.read(identifier, author=self.author)

    def search_ids(self, *args: Any, **kwargs: Any) -> list[str]:
        return self.events.search_ids(*args, author=self.author, **kwargs)

    def participant_names_for_paragraphs(self, paragraph_ids: list[int]) -> list[str]:
        return self.events.participant_names_for_paragraphs(paragraph_ids, author=self.author)

    def tree_ids_for_paragraphs(self, paragraph_ids: list[int]) -> list[str]:
        return self.events.tree_ids_for_paragraphs(paragraph_ids, author=self.author)


def build_work_tools(agent: Any, execution: Any, query_service: Any) -> list[Any]:
    ledger = execution.ledger
    author = execution.invocation_id
    tools = [
        candidate
        for candidate in build_annotation_tools(query_service, ledger)
        if candidate.name
        not in {
            "push_case",
            "claim_case",
            "claim_random_case",
            "submit_case",
            "search_cases",
            "finish",
            "write_event",
            "write_link",
        }
    ]

    def current_evidence(visible_id: int) -> list[dict[str, Any]]:
        from src.utils.identity import text_digest

        mapping = dict(zip(ledger.paragraph_info.visible_ids(), ledger.paragraph_info.paragraph_ids, strict=True))
        if isinstance(visible_id, bool) or visible_id not in mapping:
            raise ValueError(f"evidence={visible_id}，期望本章段首可见号 {list(mapping)}")
        paragraph = next(
            row for row in execution.receipt.payload["paragraphs"] if row.paragraph_id == mapping[visible_id]
        )
        return [
            {
                "chapter_id": ledger.current_chapter_id,
                "paragraph_id": paragraph.paragraph_id,
                "char_start": 0,
                "char_end": len(paragraph.text),
                "text_hash": text_digest(paragraph.text),
                "text": paragraph.text,
            }
        ]

    def annotation_event_reference_id(identifier: str) -> str:
        """把模型的事件引用解析成来源 UUID，el 引用 id 按角色命名空间解析"""
        value = unicodedata.normalize("NFC", str(identifier)).strip()
        prefix = f"{ledger.role}{ROLE_NAMESPACE_SEP}"
        el = value if value.startswith(prefix) else namespace_event_el(ledger.role, value)
        return str(ledger.events.event_ids_by_el.get(el) or value)

    def require_annotation_event(identifier: str) -> dict[str, Any]:
        node_id = annotation_event_reference_id(identifier)
        if node_id not in agent.event_trees.nodes:
            written = "、".join(ledger.events.local_els()) or "（本执行还没写事件）"
            raise ValueError(
                f"event_id={identifier} 无法解析为可引用事件；本执行已写的 el：{written}；"
                "已保存事件用 read_event/search_events 返回的真实 UUID"
            )
        value = agent.event_trees.read(node_id, author=author)
        if execution.event_reads.get(node_id) != value:
            raise ValueError(f"event_id={identifier} 尚未读取当前内容，请先 read_event")
        if value["producer_agent_id"] != author and not value["saved"]:
            raise ValueError(f"event_id={identifier} 所属执行尚未保存")
        # 允许读取后文上下文不等于允许把后文事件记成本章已经披露的变化
        if query_service.chapter_orders[value["chapter_id"]] > query_service.current_chapter_order:
            raise ValueError(f"event_id={identifier} 来源章晚于当前章，不能写入本章变化")
        endpoint = value["content"]["to_chapter_id"]
        if query_service.chapter_orders[endpoint] > query_service.current_chapter_order:
            raise ValueError(f"event_id={identifier} 终点章节晚于当前章")
        return value

    @tool
    def write_plotline(
        subject_title: str,
        description: str,
        after: str,
        evidence: int,
        before: str | None = None,
        subject_id: str | None = None,
        event_id: str | None = None,
    ) -> str:
        """记录本章明确的问题推进、目标改变或线索揭示；附真实段号与前后状态，不能把实体登记当推进

        subject_id 只接受本章或已保存的推进线索身份；未知值按标题派生并在回执 warnings 说明
        """

        if not all(value.strip() for value in (subject_title, description, after)) or before == after:
            raise ValueError("情节推进需要非空主体、描述和变化后的状态，前后不能相同")
        ledger.require_domain("plotline")
        # 冻结载荷 event_id 仅为内部来源别名，落库写 source_event_id
        event_node_id = annotation_event_reference_id(event_id) if event_id else None
        if event_node_id:
            require_annotation_event(event_node_id)
        known = {
            item["operation"]["subject_id"]
            for owner, contribution in agent.fact_graph.contributions.items()
            if owner == author or owner in agent.fact_graph.saved
            for item in contribution.get("plotline_ops", [])
        }
        # 主体键是推进线索的稳定身份：填了本 work 或已保存 work 用过的 id 就沿用，否则（含模型误填
        # 实体 id）回退到按标题派生，避免同一条线索因乱填 id 而分裂或反复触发结构化拒绝
        requested_subject_id = subject_id
        if subject_id not in known:
            subject_id = None
        subject_id = (
            subject_id
            or next(
                (
                    item["operation"]["subject_id"]
                    for owner, contribution in agent.fact_graph.contributions.items()
                    if owner == author or owner in agent.fact_graph.saved
                    for item in contribution.get("plotline_ops", [])
                    if item["operation"]["subject_title"].strip() == subject_title.strip()
                ),
                None,
            )
            or execution.identifier("plotline_subject", subject_title.strip())
        )
        warnings: list[dict[str, Any]] = []
        if requested_subject_id is not None and requested_subject_id != subject_id:
            warnings.append(
                {
                    "record": "plotline",
                    "field": "subject_id",
                    "input": requested_subject_id,
                    "used": subject_id,
                    "message": "subject_id 不在本章或已保存的推进线索中，已按标题或同名线索沿用",
                }
            )
        item = {
            "source_operation_id": execution.call_id,
            "event_id": event_node_id,
            "operation": {
                "subject_id": subject_id,
                "subject_title": subject_title.strip(),
                "description": description.strip(),
                "before": before,
                "after": after,
            },
            "evidence": current_evidence(evidence),
        }
        operations = agent.fact_graph.contributions[author].setdefault("plotline_ops", [])
        existing = next((value for value in operations if value["source_operation_id"] == execution.call_id), None)
        if existing and existing != item:
            raise ValueError("同一来源操作的情节推进内容冲突")
        if existing is None:
            operations.append(item)
        receipt: dict[str, Any] = {"status": "written", "record": "plotline", "ref": {"subject_id": subject_id}}
        if warnings:
            receipt["warnings"] = warnings
        return json.dumps(receipt, ensure_ascii=False)

    @tool
    def write_foreshadowing_action(
        source_event_id: str,
        action_type: Literal["reinforce", "payoff"],
        evidence: int,
        target_event_id: str | None = None,
    ) -> str:
        """引用 is_foreshadow_setup=True 的埋设事件记录强化或疑似回收，可位于树内任意位置
        action_type 取 'reinforce' 或 'payoff'；来源与可选目标均须先 read_event
        evidence 指本次动作原文段落，不以来源事件证据代替"""
        ledger.require_domain("foreshadow_action")
        root_id = annotation_event_reference_id(source_event_id)
        root = require_annotation_event(source_event_id)
        if not root["content"]["is_foreshadow_setup"]:
            raise ValueError(
                f"source_event_id={source_event_id} 不是伏笔根（is_foreshadow_setup=False）："
                "伏笔来源只接受 write_event(isforeshadowing=True) 标记的埋设事件，"
                "未标记的事件不能作伏笔来源；请改用 read_event 回执里"
                " is_foreshadow_setup=True 的 event_id，或跳过本动作"
            )
        target_id = annotation_event_reference_id(target_event_id) if target_event_id else None
        if target_event_id:
            require_annotation_event(target_event_id)
        evidence_rows = current_evidence(evidence)
        identifier = agent.event_trees.write_action(
            author,
            {
                "source_operation_id": execution.call_id,
                "source_event_id": root_id,
                "target_event_id": target_id,
                "action_type": action_type,
                "chapter_id": ledger.current_chapter_id,
                "evidence": evidence_rows,
                "operation_order": 1 + sum(value["author"] == author for value in agent.event_trees.actions.values()),
            },
        )
        return json.dumps(
            {"status": "written", "record": "foreshadow_action", "ref": {"action_id": identifier}}, ensure_ascii=False
        )

    def on_claim() -> None:
        execution.case_reads.clear()

    def before_submit(case_id: str) -> None:
        case = agent.case_pool.cases.get(case_id)
        if case is None or case["case_type"] != "event":
            return
        tree_id = event_case_tree_id(case["description"])
        if tree_id is None:
            return
        graph = agent.event_trees.graph(author, include_unpublished=True)
        if tree_id not in graph.queues:
            raise ValueError("事件案例指向的事件树不属于本运行，不能提交")

    event_source = AnnotationEventSource(agent.event_trees, author)
    session_factory = getattr(agent, "session_factory", None)
    semantic = SemanticLookup(session_factory(), agent.run_id) if callable(session_factory) else None
    shared = build_state_read_tools(
        agent.fact_graph,
        event_source,
        event_reads=execution.event_reads,
        entity_ids=ledger.shared_entity_ids,
        case_reads=execution.case_reads,
        resolve_event=annotation_event_reference_id,
        semantic=semantic,
    )
    shared.extend(
        build_case_tools(
            agent.case_pool,
            author,
            on_claim=on_claim,
            before_submit=before_submit,
            semantic=semantic,
            semantic_tree_ids=event_source.tree_ids_for_paragraphs,
        )
    )

    def apply_event(
        el: str,
        title: str,
        problem: str,
        summary: str,
        event_type: str,
        status: str,
        evidence: int,
        progress: str | None = None,
        from_chapter_id: int | None = None,
        to_chapter_id: int | None = None,
        reason: str | None = None,
        isforeshadowing: bool = False,
        confidence: str | None = None,
        characters: list[dict[str, Any]] | None = None,
    ) -> str:
        """创建正式事件并返回事件身份，起止章节缺省当前章，终点不得晚于当前章"""
        start = ledger.current_chapter_id if from_chapter_id is None else from_chapter_id
        end = ledger.current_chapter_id if to_chapter_id is None else to_chapter_id
        orders = query_service.chapter_orders
        if start not in orders or end not in orders or orders[start] > orders[end]:
            raise ValueError("事件起止章节必须属于本运行且顺序有效")
        if orders[end] > query_service.current_chapter_order:
            raise ValueError("标注事件不能引用未来章节")
        record = ledger.apply_event(
            el=el,
            title=title,
            problem=problem,
            summary=summary,
            event_type=event_type,
            status=status,
            evidence=evidence,
            progress=progress,
            from_chapter_id=from_chapter_id,
            to_chapter_id=to_chapter_id,
            reason=reason,
            isforeshadowing=isforeshadowing,
            confidence=confidence,
            characters=TypeAdapter(list[ParticipantArg]).validate_python(characters)
            if characters is not None
            else None,
        )
        agent.event_trees.sync(author, ledger.current_chapter_id, ledger.bound_payloads.get("events", []))
        content = ledger.event_content(el=el)
        event_id = content["event_id"]
        read = agent.event_trees.read(event_id, author=author)
        execution.event_reads[event_id] = read

        return json.dumps(
            {"status": "written", "record": record, "content": read},
            ensure_ascii=False,
        )

    def apply_event_members(
        event_ids: list[str],
        reason: str = "",
        evidence: int | None = None,
        tree_id: str | None = None,
        tree_key: str | None = None,
        title: str | None = None,
        description: str | None = None,
    ) -> str:
        "提交树成员：新建树或本执行未保存的树在队尾追加，空树只建树"
        from src.event_trees.queues import QueueGraph

        ledger.require_domain("queue")
        identifiers = [annotation_event_reference_id(value) for value in event_ids]
        for identifier in identifiers:
            require_annotation_event(identifier)
        if not identifiers and not (tree_key and title):
            raise ValueError("空事件树必须给 tree_key 和 title")
        key = tree_id
        previous = ledger.events.queues.get(key) if key is not None else None
        if previous is None and tree_key is not None:
            found = next(
                (value for value in ledger.events.queues.values() if value.get("tree_key") == tree_key),
                None,
            )
            if found is not None:
                previous = found
                key = found["tree_id"]
        if previous is None and identifiers:
            found = next(
                (value for value in ledger.events.queues.values() if set(value["event_ids"]) & set(identifiers)),
                None,
            )
            if found is not None:
                previous = found
                key = found["tree_id"]
        if key is None:
            key = new_id()
        if previous is not None:
            if not identifiers:
                return key
            members = list(previous["event_ids"])
            extended = members + [value for value in identifiers if value not in members]
            if extended[: len(members)] != members:
                raise ValueError("同一事件树的成员顺序不可改写")
            content = {**previous, "event_ids": extended}
            # 空树先建后追加时补上首个成员的树理由与证据，已有值不改写
            if not str(previous.get("reason") or "").strip() and reason.strip():
                content["reason"] = reason
            if not previous.get("evidence") and evidence is not None:
                content["evidence"] = current_evidence(evidence)
        else:
            first = agent.event_trees.read(identifiers[0], author=author)["content"] if identifiers else None
            content = {
                "tree_id": key,
                "tree_key": tree_key,
                "title": title or (first["title"] if first else ""),
                "description": description or (first["summary"] if first else ""),
                "event_ids": identifiers,
                "reason": reason,
                "evidence": current_evidence(evidence) if evidence is not None else [],
                "producer_agent_id": author,
            }
        graph = agent.event_trees.graph(author)
        queues = dict(graph.queues)
        if key in queues and tuple(content["event_ids"][: len(queues[key])]) != queues[key]:
            raise ValueError("正式事件树成员和顺序不可改写")
        queues[key] = content["event_ids"]
        QueueGraph(
            queues,
            [(parent, child) for parent, children in graph.children.items() for child in children],
            [
                identifier
                for identifier, value in agent.event_trees.nodes.items()
                if value["author"] == author or value["author"] in agent.event_trees.saved
            ],
            require_complete=False,
            event_line_ids=graph.event_line_ids,
        )
        ledger.events.queues[key] = content
        return key

    @tool
    def write_event(
        items: list[AnnotationEventItem] | None = None,
        tree_id: str | None = None,
        tree_key: str | None = None,
        title: str | None = None,
        description: str | None = None,
    ) -> str:
        """提交一棵事件树；items 为空时按 tree_key/title 新建空树，非空时 items 顺序即树内成员顺序；
        每项 el 是本执行内引用 id，不表示父子层级；本执行内同一棵树可继续追加，已写事件只接受原样重交"""
        values = TypeAdapter(list[AnnotationEventItem]).validate_python(items or [])
        el_values = [namespace_event_el_once(ledger.role, normalize_event_el(item.el)) for item in values]
        registered = build_batch_agent_events(
            execution.agent,
            role=ledger.role,
            paragraph_text_by_id=ledger.paragraph_info.text_by_visible_id(),
            items=values,
        )

        snapshots = ledger.snapshot(), agent.fact_graph.snapshot(), agent.event_trees.snapshot(author)
        reads = deepcopy(execution.event_reads)
        try:
            results = []
            warnings: list[dict[str, Any]] = []
            for item, el in zip(values, el_values, strict=True):
                payload = item.model_dump(exclude_unset=True)
                payload["el"] = el
                results.append(json.loads(apply_event(**payload)))
                warnings.extend(ledger.pop_warnings())
            identifiers = [result["content"]["event_id"] for result in results]
            # 成员校验读的是事件读取快照，先按当前状态刷新，避免旧快照把重交判成未读
            for identifier in identifiers:
                execution.event_reads[identifier] = agent.event_trees.read(identifier, author=author)
            first = values[0] if values else None
            submitted_tree_id = apply_event_members(
                identifiers,
                reason=(first.reason or first.problem) if first else "",
                evidence=first.evidence if first else None,
                tree_id=tree_id,
                tree_key=tree_key,
                title=title,
                description=description,
            )
            agent.event_trees.sync_contributions(author, ledger.events.contribution_payloads())
            # 追加会改变既有成员所在树的组成，成员读取快照按新树整体刷新
            for identifier in ledger.events.queues.get(submitted_tree_id, {}).get("event_ids", identifiers):
                execution.event_reads[identifier] = agent.event_trees.read(identifier, author=author)
            for identifier, result in zip(identifiers, results, strict=True):
                result["content"] = agent.event_trees.read(identifier, author=author)
                execution.event_reads[identifier] = result["content"]
                ledger.written_record_keys.add(result["record"])
        except BaseException:
            ledger.restore(snapshots[0])
            agent.fact_graph.restore(snapshots[1])
            agent.event_trees.restore(snapshots[2])
            execution.event_reads.clear()
            execution.event_reads.update(reads)
            raise
        for result, registered_item in zip(results, registered, strict=True):
            result["el"] = registered_item.el
            register_agent_event(execution.agent, registered_item)
        receipt: dict[str, Any] = {
            "status": "written",
            "tree_id": submitted_tree_id,
            "results": results,
            "failed": [],
        }
        if warnings:
            receipt["warnings"] = warnings
        return json.dumps(receipt, ensure_ascii=False)

    @tool
    def retract_structure(kind: Literal["queue", "reference"], identifier: str, reason: str, evidence: int) -> str:
        "撤回本执行尚未保存的队列或父子引用；撤回队列同时删除该树的草稿事件"
        ledger.require_domain("retract")
        if not reason.strip():
            raise ValueError("撤回必须给出原文理由")
        current_evidence(evidence)
        if author in agent.event_trees.saved:
            raise ValueError("正式队列和父子引用不可撤回")
        records = ledger.events.queues if kind == "queue" else ledger.events.queue_references
        key = identifier
        if kind == "queue" and key not in records:
            event_id = annotation_event_reference_id(identifier)
            key = next(
                (tree_id for tree_id, value in records.items() if event_id in value["event_ids"]),
                key,
            )
        if key not in records:
            label = "事件树" if kind == "queue" else "父子引用"
            available = "、".join(sorted(records)[:20]) or f"（本执行还没有可撤回的{label}草稿）"
            raise ValueError(f"只能撤回本执行实际创建的草稿；可撤回的{label}：{available}")
        if kind == "queue" and any(
            key in {value["parent_tree_id"], value["child_tree_id"]}
            for value in ledger.events.queue_references.values()
        ):
            raise ValueError("请先撤回本执行指向该草稿事件树的父子引用")
        dropped: list[str] = []
        if kind == "queue":
            members, dropped = ledger.events.drop_queue(key)
            agent.event_trees.drop_queue(author, key)
            for identifier in members:
                execution.event_reads.pop(identifier, None)
            prefix = f"{ledger.role}{ROLE_NAMESPACE_SEP}"
            removed = {el[len(prefix) :] if el.startswith(prefix) else el for el in dropped}
            execution.agent.events[:] = [item for item in execution.agent.events if item.el not in removed]
        else:
            del records[key]
        receipt: dict[str, Any] = {"status": "withdrawn", "kind": kind, "identifier": key}
        if dropped:
            receipt["events"] = len(dropped)
        return json.dumps(receipt, ensure_ascii=False)

    @tool
    def write_link(
        source_id: str,
        target_id: str,
        kind: Literal["causal", "foreshadowing", "same_entity", "different_entity", "relation_change", "parent_child"],
        relation_type: str | None = None,
        change_kind: Literal["assert", "reinforce", "weaken", "refine", "break", "supersede", "retract"] | None = None,
        reason: str | None = None,
        evidence: int | None = None,
    ) -> str:
        """明确关联已实际读取的事件或实体 ID；伏笔照应不合树，关系变化须明确类型、方向和原因

        causal/foreshadowing 的两端是事件：先 read_event 读取，须给非空 reason 与本章段首 evidence；
        parent_child 的两端是事件树 ID，空树也可连接，只须给非空 reason；same_entity/different_entity
        固定用「同一人物」，两端须是 character；relation_change 须给 change_kind 与非空 reason。
        实体端点用 search_graph/read_entity 读回的真实 UUID，本次 invocation 没读过的端点会被拒收。
        """
        if kind == "parent_child":
            ledger.require_domain("reference")
        elif kind in {"causal", "foreshadowing"}:
            ledger.require_domain("event")
        else:
            ledger.require_domain("relation")
        if kind in {"causal", "foreshadowing", "parent_child"}:
            if relation_type is not None or change_kind is not None:
                raise ValueError("事件关联不接受 relation_type/change_kind")
            if not reason or not reason.strip():
                raise ValueError("事件关联建议必须给原文理由")
            if kind != "parent_child" and evidence is None:
                raise ValueError("事件关联建议必须给本章段首evidence")
            source_node = annotation_event_reference_id(source_id)
            target_node = annotation_event_reference_id(target_id)

            if kind == "parent_child":
                from src.event_trees.queues import QueueGraph

                graph = agent.event_trees.graph(author)
                source_node, target_node = source_id, target_id
                link_evidence = current_evidence(evidence) if evidence is not None else []
                for value in agent.event_trees.queue_references.values():
                    edge = value["content"]
                    if (edge["parent_tree_id"], edge["child_tree_id"]) == (source_node, target_node):
                        if value["author"] != author or value["author"] in agent.event_trees.saved:
                            raise ValueError("父子引用已由其他执行或正式记录写出，请引用原判断")
                        if edge["reason"] != reason or edge["evidence"] != link_evidence:
                            raise ValueError("本执行已有不同父子判断，请先撤回草稿引用")
                for key in (source_node, target_node):
                    if key not in graph.queues:
                        raise ValueError("父子引用端点必须是完整事件树 ID")
                pairs = [(parent, child) for parent, children in graph.children.items() for child in children]
                if (source_node, target_node) not in pairs:
                    pairs.append((source_node, target_node))
                QueueGraph(graph.queues, pairs, graph.event_tree, require_complete=True)
                identifier = execution.identifier("queue_reference", source_node, target_node)
                ledger.events.queue_references[identifier] = {
                    "link_id": identifier,
                    "parent_tree_id": source_node,
                    "child_tree_id": target_node,
                    "reason": reason,
                    "evidence": link_evidence,
                    "producer_agent_id": author,
                }
                return json.dumps({"status": "written", "kind": kind, "connection_id": identifier}, ensure_ascii=False)
            require_annotation_event(source_node)
            require_annotation_event(target_node)
            identifier = execution.identifier(execution.call_id, kind)
            ledger.events.apply_annotation_event_relation(
                ledger,
                source_kind="event",
                source_id=source_node,
                target_kind="event",
                target_id=target_node,
                relation_type=kind,
                reason=reason,
                evidence=evidence,
                source_operation_id=identifier,
            )
        else:
            from src.fact_graph.vocabulary import RELATION_DEFINITIONS

            for identifier in (source_id, target_id):
                if identifier not in ledger.shared_entity_ids:
                    raise ValueError(f"entity_id={identifier} 当前 invocation 尚未读取，请 search_graph")
            left = agent.fact_graph.resolve_entity_id(source_id, label="source_id")
            right = agent.fact_graph.resolve_entity_id(target_id, label="target_id")
            relation = "同一人物" if kind in {"same_entity", "different_entity"} else relation_type
            if relation not in RELATION_DEFINITIONS or source_id == target_id:
                raise ValueError(f"关系类型={relation!r} 或端点={source_id}/{target_id} 无效")
            if kind == "relation_change" and (change_kind is None or not reason or not reason.strip()):
                raise ValueError("relation_change 必须提供 change_kind 和非空 reason")
            if kind != "relation_change" and (relation_type is not None or change_kind is not None):
                raise ValueError("身份关联不接受 relation_type/change_kind")
            definition = RELATION_DEFINITIONS[relation]
            if (
                agent.fact_graph.entity_type_by_key(left) not in definition["from_types"]
                or agent.fact_graph.entity_type_by_key(right) not in definition["to_types"]
            ):
                raise ValueError(
                    f"关系类型={relation} 与实体类型不匹配："
                    f"{agent.fact_graph.display_name(left)}/{agent.fact_graph.display_name(right)}"
                )
            op = {
                "from_entity": left,
                "to_entity": right,
                "relation_type": relation,
                "chapter_id": ledger.current_chapter_id,
                "change_kind": "break" if kind == "different_entity" else change_kind or "assert",
                "reason": reason,
            }
            if kind in {"same_entity", "different_entity"}:
                op["identity_kind"] = "different" if kind == "different_entity" else "same"
            operations = agent.fact_graph.contributions[author].setdefault("relation_link_ops", [])
            if op not in operations:
                operations.append(op)
            agent.fact_graph._fold()
            identifier = f"{source_id}/{relation}/{target_id}"
        return json.dumps({"status": "written", "kind": kind, "connection_id": identifier}, ensure_ascii=False)

    def request_end() -> dict[str, Any]:
        """请求结束当前回合，完整性由程序统一检查"""
        execution.end_requested = True
        ledger.end_requested = True
        body: dict[str, Any] = {
            "status": "written",
            "record": "finish",
            "ref": {"role": ledger.role, "end_requested": True},
        }
        return body

    finish = build_finish_tool(request_end)
    tools.extend(
        [
            write_plotline,
            write_foreshadowing_action,
            write_event,
            retract_structure,
            write_link,
            *shared,
            finish,
        ]
    )
    for candidate in tools:
        _forbid_undeclared_args(candidate)
        from src.case_pool.tool_binding import bind_caseid

        if candidate.name not in {"claim_case", "claim_random_case", "submit_case"}:
            bind_caseid(candidate)
    return tools
