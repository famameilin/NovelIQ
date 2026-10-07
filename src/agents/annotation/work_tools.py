"""agent 内部业务工具，直接读取和修改三个全书域"""

from __future__ import annotations

import json
from typing import Any, Literal

from langchain_core.tools import tool
from pydantic import TypeAdapter

from src.event_trees.models import ParticipantArg
from .tool_factories import build_annotation_tools
from .tools import _forbid_undeclared_args


def build_work_tools(agent: Any, execution: Any, query_service: Any) -> list[Any]:
    ledger = execution.ledger
    author = (execution.work_id, execution.invocation_id)
    tools = [
        candidate
        for candidate in build_annotation_tools(query_service, ledger)
        if candidate.name not in {"push_case", "finish", "write_event", "write_link"}
    ]

    @tool
    def push_case(description: str) -> str:
        """登记非空、100 字以内的普通文字案例，只接受 description"""
        return json.dumps(agent.case_pool.push(description, author), ensure_ascii=False)

    @tool
    def promise_case(case_id: str) -> str:
        """原子认领案例列表的真实案例 ID，被占用立即返回 busy"""
        result = agent.case_pool.promise(case_id, author)
        if result["status"] == "claimed":
            execution.case_connections = []
            execution.case_reads = []
        return json.dumps(result, ensure_ascii=False)

    @tool
    def search_cases() -> str:
        """读取全书案例 ID、说明及当前办理状态"""
        return json.dumps(agent.case_pool.search(), ensure_ascii=False)

    @tool
    def search_events(query: str = "") -> str:
        """读取全书事件节点，node_id 可用于 event 的 parent_ref/node_ref，原文须另行读取"""
        values = agent.event_trees.search(query)
        for value in values:
            execution.event_reads[value["node_id"]] = value
        execution.case_reads.extend(values)
        return json.dumps(values, ensure_ascii=False)

    @tool
    def search_graph(query: str = "") -> str:
        """读取全书事实图已登记实体与关系，不授权未读过的原文"""
        values = [
            {
                "id": agent.fact_graph.entity_id(name),
                "name": name,
                "entity_type": agent.fact_graph.entity_types[key],
                "attributes": agent.fact_graph.entity_attributes.get(key, {}),
            }
            for key, name in sorted(agent.fact_graph.entity_names.items())
            if query.casefold() in name.casefold()
        ]
        ledger.shared_entity_ids.update(value["id"] for value in values)
        execution.case_reads.extend(values)
        return json.dumps(
            {"entities": values, "relations": sorted(agent.fact_graph.active_relations)}, ensure_ascii=False
        )

    @tool
    def write_event(
        el: str | None = None,
        isroot: bool | None = None,
        description: str | None = None,
        evidence: int | None = None,
        isforeshadowing: bool = False,
        confidence: str | None = None,
        type: str | None = None,
        characters: list[dict[str, Any]] | None = None,
        parent_ref: str | None = None,
        node_ref: str | None = None,
    ) -> str:
        """创建节点或显式连接已读事件；连接已有节点时只填 node_ref/parent_ref/type"""
        if parent_ref is not None and type not in {"main", "secondary"}:
            raise ValueError(f"event.type={type!r}，连接父节点须明确 main/secondary")
        if node_ref is not None:
            if parent_ref is None or any(
                value is not None for value in (el, isroot, description, evidence, characters)
            ):
                raise ValueError("连接已有节点只填 node_ref、parent_ref、type")
            node_id = node_ref
        else:
            if el is None or isroot is None or description is None:
                raise ValueError("创建事件须填写 el/isroot/description")
            create_kind = None if isroot else type
            ledger.apply_event(
                el=el,
                isroot=isroot,
                description=description,
                evidence=evidence,
                isforeshadowing=isforeshadowing,
                confidence=confidence,
                node_type=create_kind,
                characters=(
                    TypeAdapter(list[ParticipantArg]).validate_python(characters) if characters is not None else None
                ),
            )
            agent.event_trees.sync(author, ledger.current_chapter_id, ledger.bound_payloads.get("events", []))
            content = ledger.event_content(el=el, isroot=isroot)
            node_id = content["id"]
            execution.event_reads[node_id] = agent.event_trees.read(node_id)
        connection_id = None
        if parent_ref is not None:
            authorized = set(ledger.authorized_text_paragraph_ids)
            authorized.update(ledger.paragraph_info.paragraph_ids)
            connection_id = agent.event_trees.connect(
                author, node_id, parent_ref, type, execution.event_reads, authorized
            )
            if agent.case_pool.active(author) is not None:
                execution.case_connections.append(connection_id)
        return json.dumps(
            {
                "status": "written",
                "record": el or node_id,
                "content": agent.event_trees.read(node_id),
                "connection_id": connection_id,
            },
            ensure_ascii=False,
        )

    @tool
    def write_link(
        source_id: str,
        target_id: str,
        kind: Literal["causal", "foreshadowing", "same_entity", "different_entity", "relation_change"],
        relation_type: str | None = None,
        change_kind: Literal["assert", "reinforce", "weaken", "refine", "break", "supersede", "retract"] | None = None,
        reason: str | None = None,
    ) -> str:
        """明确关联已实际读取的事件或实体 ID；伏笔照应不合树，关系变化须明确类型、方向和原因"""
        if kind in {"causal", "foreshadowing"}:
            if relation_type is not None or change_kind is not None:
                raise ValueError("事件关联不接受 relation_type/change_kind")
            authorized = set(ledger.authorized_text_paragraph_ids) | set(ledger.paragraph_info.paragraph_ids)
            identifier = agent.event_trees.connect(
                author,
                target_id,
                source_id,
                kind,
                execution.event_reads,
                authorized,
            )
            if agent.case_pool.active(author) is not None:
                execution.case_connections.append(identifier)
        else:
            from src.fact_graph.schema import RELATION_DEFINITIONS

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
                agent.fact_graph.entity_type(left) not in definition["from_types"]
                or agent.fact_graph.entity_type(right) not in definition["to_types"]
            ):
                raise ValueError(f"关系类型={relation} 与实体类型不匹配：{left}/{right}")
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

    @tool
    def finish(case_delivery: dict[str, Any] | None = None, complete: bool = True) -> str:
        """交付当前案例；complete=True 校验并关闭当前角色 work，False 继续当前会话"""
        if not complete and case_delivery is None:
            raise ValueError("finish(complete=False) 必须提供 case_delivery")
        if complete:
            execution.validate()
        if case_delivery is not None:
            agent.case_pool.deliver(
                case_delivery,
                author,
                call_id=execution.call_id,
                connections=execution.case_connections,
                reads=execution.case_reads,
            )
            execution.case_connections = []
            execution.case_reads = []
        elif agent.case_pool.active(author) is not None:
            raise ValueError(f"finish 当前 active case_id={agent.case_pool.active(author)}，必须明确交付")
        if complete:
            execution.finished = True
            execution.subagent.finished = True
            ledger.chapter_finished = True
        return json.dumps(
            {
                "status": "written",
                "record": "finish",
                "ref": {
                    "role": ledger.role,
                    "finished": complete,
                    "unjudged_candidates": [],
                    "missing_metric": False,
                },
            },
            ensure_ascii=False,
        )

    tools.extend([write_event, write_link, push_case, promise_case, search_cases, search_events, search_graph, finish])
    for candidate in tools:
        _forbid_undeclared_args(candidate)
    return tools
