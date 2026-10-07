"""agent 内部业务工具，直接读取和修改三个全书域"""

from __future__ import annotations

import json
from typing import Annotated, Any, Literal

from langchain_core.tools import tool
from pydantic import Field, TypeAdapter

from src.event_trees.models import ParticipantArg
from src.fact_graph.schema import EntityType

from .search_projection import SHARED_SEARCH_MAX_CHARS
from .tool_factories import build_annotation_tools
from .tools import _forbid_undeclared_args

SearchLimit = Annotated[int, Field(ge=1, le=20)]
SearchOffset = Annotated[int, Field(ge=0)]


def _search_page(values: list[Any], *, offset: int, limit: int, budget: int) -> tuple[list[Any], int | None]:
    """按整项预算分页，保留返回项的完整引用，下一页从实际未返回的位置继续"""
    page: list[Any] = []
    size = 2
    for value in values[offset:offset + limit]:
        encoded = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
        if size + len(encoded) + 1 > budget:
            break
        page.append(value)
        size += len(encoded) + 1
    next_offset = offset + len(page)
    if not page and offset < len(values):
        raise ValueError("检索单项超过预览预算，请按 ID 读取详情")
    return page, next_offset if next_offset < len(values) else None


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
    def search_events(
        query: str = "", chapter_id: int | None = None, tree_id: str | None = None,
        limit: SearchLimit = 5, offset: SearchOffset = 0,
    ) -> str:
        """分页预览事件，可筛选章/树；events 为本页，next_offset 为续页位置，read_event 读取详情"""
        identifiers = agent.event_trees.search_ids(query, chapter_id=chapter_id, tree_id=tree_id)
        reads = [agent.event_trees.read(identifier) for identifier in identifiers[offset:offset + limit]]
        previews = [{
            "node_id": value["node_id"], "chapter_id": value["chapter_id"], "saved": value["saved"],
            "tree_id": value["content"]["tree_id"], "parent_node_id": value["content"]["parent_node_id"],
            "evidence_paragraph_id": value["content"]["evidence_paragraph_id"],
            "description": value["content"]["description"][:160],
        } for value in reads]
        page, _ = _search_page(previews, offset=0, limit=limit, budget=SHARED_SEARCH_MAX_CHARS - 600)
        # 只授权实际返回页，完整快照留在服务端用于生产者与内容新鲜度校验
        for value in reads[:len(page)]:
            execution.event_reads[value["node_id"]] = value
        execution.case_reads.extend(page)
        next_offset = offset + len(page)
        return json.dumps({
            "events": page, "total": len(identifiers),
            "next_offset": next_offset if next_offset < len(identifiers) else None,
        }, ensure_ascii=False, separators=(",", ":"))

    @tool
    def read_event(node_id: str) -> str:
        """按实际节点 ID 读取完整事件详情；原文证据仍须 read_text/read_chapter_text 授权"""
        value = agent.event_trees.read(node_id)
        execution.event_reads[node_id] = value
        execution.case_reads.append(value)
        return json.dumps(value, ensure_ascii=False)

    @tool
    def search_graph(
        query: str = "", entity_type: EntityType | None = None,
        limit: SearchLimit = 5, offset: SearchOffset = 0, relation_offset: SearchOffset = 0,
    ) -> str:
        """分页预览实体和命中端点的关系；两组 next_offset 独立续页，read_entity 读取完整属性"""
        matching = {
            key for key, name in agent.fact_graph.entity_names.items()
            if query.casefold() in name.casefold()
            and (entity_type is None or str(agent.fact_graph.entity_types[key]) == entity_type)
        }
        values = [
            {
                "id": agent.fact_graph.entity_id(name),
                "name": name[:160],
                "entity_type": agent.fact_graph.entity_types[key],
            }
            for key, name in sorted(agent.fact_graph.entity_names.items())
            if key in matching
        ]
        relations = [{
            "source_id": agent.fact_graph.entity_id(left), "target_id": agent.fact_graph.entity_id(right),
            "relation_type": kind,
        } for left, right, kind in sorted(agent.fact_graph.active_relations) if left in matching or right in matching]
        entities_page, next_offset = _search_page(values, offset=offset, limit=limit, budget=2600)
        relations_page, next_relation_offset = _search_page(
            relations, offset=relation_offset, limit=limit, budget=2600,
        )
        ledger.shared_entity_ids.update(value["id"] for value in entities_page)
        ledger.shared_entity_ids.update(
            value[field] for value in relations_page for field in ("source_id", "target_id")
        )
        execution.case_reads.extend([*entities_page, *relations_page])
        return json.dumps({
            "entities": entities_page, "relations": relations_page, "total_entities": len(values),
            "total_relations": len(relations), "next_offset": next_offset,
            "next_relation_offset": next_relation_offset,
        }, ensure_ascii=False, separators=(",", ":"))

    @tool
    def read_entity(entity_id: str) -> str:
        """按实体 UUID 读取完整名称、类型和属性，不授权未读过的原文"""
        name = agent.fact_graph.resolve_entity_id(entity_id, label="entity_id")
        key = next(key for key, identifier in agent.fact_graph.entity_ids.items() if identifier == entity_id)
        value = {
            "id": entity_id, "name": name, "entity_type": agent.fact_graph.entity_types[key],
            "attributes": agent.fact_graph.entity_attributes.get(key, {}),
        }
        ledger.shared_entity_ids.add(entity_id)
        execution.case_reads.append(value)
        return json.dumps(value, ensure_ascii=False)

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
            if content.get("deferred"):
                if parent_ref is not None:
                    raise ValueError(f"event/{el} 尚未建根，不能连接 parent_ref={parent_ref}")
                return json.dumps({"status": "deferred", "record": el, "content": content}, ensure_ascii=False)
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

    tools.extend([
        write_event, write_link, push_case, promise_case, search_cases, search_events, search_graph,
        read_event, read_entity, finish,
    ])
    for candidate in tools:
        _forbid_undeclared_args(candidate)
    return tools
