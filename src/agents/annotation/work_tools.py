"""agent 内部业务工具，直接读取和修改三个全书域"""

from __future__ import annotations

import json
import unicodedata
from typing import Any, Literal

from langchain_core.tools import tool
from pydantic import TypeAdapter

from src.event_trees.models import ParticipantArg
from src.fact_graph.schema import EL_PATH_SEP, RESERVED_ROOT_KEY

from .ir_contract import ROLE_NAMESPACE_SEP
from .ir_validation import namespace_event_el
from .shared_tools import build_case_tools, build_finish_tool, build_state_read_tools
from .tool_factories import build_annotation_tools
from .tools import _forbid_undeclared_args


def build_work_tools(agent: Any, execution: Any, query_service: Any) -> list[Any]:
    ledger = execution.ledger
    author = execution.invocation_id
    tools = [
        candidate
        for candidate in build_annotation_tools(query_service, ledger)
        if candidate.name not in {"push_case", "finish", "write_event", "write_link"}
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

    def declaration_reference_id(identifier: str) -> str:
        """把模型的声明引用解析成来源 UUID，el 局部键按角色命名空间解析"""
        value = unicodedata.normalize("NFC", str(identifier)).strip()
        prefix = f"{ledger.role}{ROLE_NAMESPACE_SEP}"
        el = value if value.startswith(prefix) else namespace_event_el(ledger.role, value)
        tree_key, _, node_key = el.partition(EL_PATH_SEP)
        tree = ledger.event_trees.get(ledger.tree_key_index.get(tree_key.strip()) or "")
        if tree is not None:
            node_id = (tree.get("nodes") or {}).get(node_key.strip() or RESERVED_ROOT_KEY)
            if node_id:
                return str(node_id)
        return value

    def require_declaration(identifier: str) -> dict[str, Any]:
        node_id = declaration_reference_id(identifier)
        value = agent.event_trees.read(node_id)
        if execution.event_reads.get(node_id) != value:
            raise ValueError(f"declaration_id={identifier} 尚未读取当前内容，请先 read_event")
        if value["producer_agent_id"] != author and not value["saved"]:
            raise ValueError(f"declaration_id={identifier} 所属执行尚未保存")
        # 允许读取后文上下文不等于允许把后文事件记成本章已经披露的变化
        if query_service.chapter_orders[value["chapter_id"]] > query_service.current_chapter_order:
            raise ValueError(f"declaration_id={identifier} 来源章晚于当前章，不能写入本章变化")
        return value

    @tool
    def write_plotline(
        subject_title: str,
        description: str,
        after: str,
        evidence: int,
        before: str | None = None,
        subject_id: str | None = None,
        declaration_id: str | None = None,
    ) -> str:
        """记录本章明确的问题推进、目标改变或线索揭示；附真实段号与前后状态，不能把实体登记当推进"""

        if not all(value.strip() for value in (subject_title, description, after)) or before == after:
            raise ValueError("情节推进需要非空主体、描述和变化后的状态，前后不能相同")
        if ledger.role not in {"annotation", "event"}:
            raise ValueError("情节推进由事件角色写入")
        # 冻结载荷 event_id 仅为内部来源别名，落库写 source_declaration_id
        event_node_id = declaration_reference_id(declaration_id) if declaration_id else None
        if event_node_id:
            require_declaration(event_node_id)
        known = {
            item["operation"]["subject_id"]
            for owner, contribution in agent.fact_graph.contributions.items()
            if owner == author or owner in agent.fact_graph.saved
            for item in contribution.get("plotline_ops", [])
        }
        # 主体键是推进线索的稳定身份：填了本 work 或已保存 work 用过的 id 就沿用，否则（含模型误填
        # 实体 id）回退到按标题派生，避免同一条线索因乱填 id 而分裂或反复触发结构化拒绝
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
        return json.dumps(
            {"status": "written", "record": "plotline", "ref": {"subject_id": subject_id}}, ensure_ascii=False
        )

    @tool
    def write_foreshadowing_action(
        source_declaration_id: str,
        action_type: Literal["reinforce", "payoff"],
        evidence: int,
        target_declaration_id: str | None = None,
    ) -> str:
        """引用已埋伏笔（is_foreshadow_setup=True 的树根声明）记录强化或疑似回收；
        action_type 取 'reinforce'（强化）或 'payoff'（疑似回收）英文常量；
        引用前须先 read_event 读取声明；正式事件身份在诊断发布时绑定"""
        if ledger.role not in {"annotation", "event"}:
            raise ValueError("伏笔动作由事件角色写入")
        root_id = declaration_reference_id(source_declaration_id)
        root = require_declaration(source_declaration_id)
        if not root["content"]["is_foreshadow_setup"]:
            raise ValueError(
                f"source_declaration_id={source_declaration_id} 不是伏笔根（is_foreshadow_setup=False）："
                "伏笔来源只接受 write_event(isforeshadowing=True) 种下的树根，"
                "普通事件树根不能作伏笔来源；请改用 read_event 回执里"
                " is_foreshadow_setup=True 的 declaration_id，或跳过本动作"
            )
        target_id = declaration_reference_id(target_declaration_id) if target_declaration_id else None
        if target_declaration_id:
            require_declaration(target_declaration_id)
        evidence_rows = current_evidence(evidence)
        # 内部动作容器保留来源别名；正式 event_id 只由诊断发布填入
        identifier = agent.event_trees.write_action(
            author,
            {
                "source_operation_id": execution.call_id,
                "root_event_id": root_id,
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

    shared = build_state_read_tools(
        agent.fact_graph,
        agent.event_trees,
        event_reads=execution.event_reads,
        entity_ids=ledger.shared_entity_ids,
        case_reads=execution.case_reads,
        resolve_event=declaration_reference_id,
    )
    shared.extend(build_case_tools(agent.case_pool, author, on_claim=on_claim))

    @tool
    def write_event(
        el: str,
        title: str,
        problem: str,
        summary: str,
        event_type: str,
        status: str,
        evidence: int,
        progress: str | None = None,
        isforeshadowing: bool = False,
        confidence: str | None = None,
        characters: list[dict[str, Any]] | None = None,
    ) -> str:
        """保存本章事件声明，回执只发放声明身份；全书事件由诊断确认后发布"""
        record = ledger.apply_event(
            el=el,
            title=title,
            problem=problem,
            summary=summary,
            event_type=event_type,
            status=status,
            evidence=evidence,
            progress=progress,
            isforeshadowing=isforeshadowing,
            confidence=confidence,
            characters=TypeAdapter(list[ParticipantArg]).validate_python(characters)
            if characters is not None
            else None,
        )
        agent.event_trees.sync(author, ledger.current_chapter_id, ledger.bound_payloads.get("events", []))
        content = ledger.event_content(el=el, isroot="/" not in el)
        declaration_id = content["declaration_id"]
        read = agent.event_trees.read(declaration_id)
        execution.event_reads[declaration_id] = read

        # 登记进全书共享案例池（case_type=event），诊断期按事件并发派工时据此取材
        agent.case_pool.register_event_case(
            title=read["content"]["title"],
            summary=read["content"]["summary"],
            author=author,
        )
        return json.dumps(
            {"status": "written", "record": record, "content": read},
            ensure_ascii=False,
        )

    @tool
    def write_link(
        source_id: str,
        target_id: str,
        kind: Literal["causal", "foreshadowing", "same_entity", "different_entity", "relation_change", "contains"],
        relation_type: str | None = None,
        change_kind: Literal["assert", "reinforce", "weaken", "refine", "break", "supersede", "retract"] | None = None,
        reason: str | None = None,
        evidence: int | None = None,
    ) -> str:
        """明确关联已实际读取的事件或实体 ID；伏笔照应不合树，关系变化须明确类型、方向和原因"""
        if kind in {"causal", "foreshadowing", "contains"}:
            if relation_type is not None or change_kind is not None:
                raise ValueError("事件关联不接受 relation_type/change_kind")
            if not reason or not reason.strip() or evidence is None:
                raise ValueError("声明关联建议必须给原文理由和本章段首evidence")
            source_node = declaration_reference_id(source_id)
            target_node = declaration_reference_id(target_id)
            require_declaration(source_node)
            require_declaration(target_node)

            identifier = execution.identifier(execution.call_id, kind)
            ledger.events.apply_declaration_relation(
                ledger,
                source_kind="declaration",
                source_id=source_node,
                target_kind="declaration",
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
            write_link,
            *shared,
            finish,
        ]
    )
    for candidate in tools:
        _forbid_undeclared_args(candidate)
        from src.case_pool.tool_binding import bind_caseid

        bind_caseid(candidate)
    return tools
