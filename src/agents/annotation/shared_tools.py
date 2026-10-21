"""标注与诊断共用的状态读取、案例办理和结束工具"""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Annotated, Any, Literal

from langchain_core.tools import tool
from pydantic import Field

from src.fact_graph.vocabulary import EntityType
from src.storage.query_terms import query_search_terms, term_matches

SearchLimit = Annotated[int, Field(ge=1, le=20)]
# 紧凑索引只回一行式字段，单页体量小，允许到 100 条（详情预览仍限 20，由工具内校验）
EventSearchLimit = Annotated[int, Field(ge=1, le=100)]
SearchOffset = Annotated[int, Field(ge=0)]
ObjectKind = Literal["event", "arc", "outcome"]


def _search_page(values: list[Any], *, offset: int, limit: int, budget: int) -> tuple[list[Any], int | None]:
    """按整项预算分页，保留完整身份，不截断为不可续读的半条记录"""
    page: list[Any] = []
    size = 2
    for value in values[offset : offset + limit]:
        encoded = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
        if size + len(encoded) + 1 > budget:
            break
        page.append(value)
        size += len(encoded) + 1
    if not page and offset < len(values):
        raise ValueError("检索单项超过预览预算，请按 ID 读取详情")
    next_offset = offset + len(page)
    return page, next_offset if next_offset < len(values) else None


def build_state_read_tools(
    graph: Any,
    events: Any,
    *,
    event_reads: dict[str, Any],
    entity_ids: set[str],
    case_reads: list[Any],
    resolve_event: Callable[[str], str],
    organization: Any = None,
) -> list[Any]:
    """同一份分页、授权及实体读取实现；数据来源由真实执行上下文装配"""

    @tool
    def search_events(
        query: str = "",
        chapter_id: int | None = None,
        tree_id: str | None = None,
        limit: EventSearchLimit = 5,
        offset: SearchOffset = 0,
        kind: ObjectKind = "event",
        isforeshadowing: bool | None = None,
        compact: bool = False,
    ) -> str:
        """按条数分页读取简洁索引，除末页外返回 limit 条；详情用 read_event，续页用 next_offset；
        isforeshadowing=True 只返回伏笔根事件（False 只返回非伏笔根），不填不过滤；
        compact=True 读取紧凑索引（事件附章号与伏笔标记，诊断对象返回简洁索引行），每页最多 100 条；
        compact=False 的详情预览每页最多 20 条"""
        if kind != "event":
            if organization is None:
                raise ValueError(f"本执行不提供 kind={kind} 的诊断对象")
            if not compact and limit > 20:
                raise ValueError(
                    f"limit={limit} 越界：详情预览每页最多 20 条，紧凑索引请用 compact=True（最多 100 条）"
                )
            values = organization.search(kind, query, chapter_id=chapter_id, tree_id=tree_id)
            page = values[offset : offset + limit]
            next_offset = offset + len(page)
            case_reads.extend(page)
            return json.dumps(
                {
                    "kind": kind,
                    "events": page,
                    "total": len(values),
                    "next_offset": next_offset if next_offset < len(values) else None,
                },
                ensure_ascii=False,
            )
        if not compact and limit > 20:
            raise ValueError(f"limit={limit} 越界：详情预览每页最多 20 条，精简一页请用 compact=True（最多 100 条）")
        identifiers = events.search_ids(query, chapter_id=chapter_id, tree_id=tree_id, isforeshadowing=isforeshadowing)
        reads = [events.read(identifier) for identifier in identifiers[offset : offset + limit]]
        if compact:
            previews = [
                {
                    "event_id": value["event_id"],
                    "from": value["content"].get("from", value["content"].get("from_chapter_id")),
                    "to": value["content"].get("to", value["content"].get("to_chapter_id")),
                    "chapter_id": value["chapter_id"],
                    "saved": value["saved"],
                    "is_foreshadow_setup": value["content"]["is_foreshadow_setup"],
                    "title": value["content"]["title"][:60],
                    "event_type": value["content"]["event_type"],
                    "status": value["content"]["status"],
                }
                for value in reads
            ]
        else:
            previews = [
                {
                    "event_id": value["event_id"],
                    "from": value["content"].get("from", value["content"].get("from_chapter_id")),
                    "to": value["content"].get("to", value["content"].get("to_chapter_id")),
                    "chapter_id": value["chapter_id"],
                    "saved": value["saved"],
                    "is_foreshadow_setup": value["content"]["is_foreshadow_setup"],
                    "evidence_paragraph_id": value["content"]["evidence_paragraph_id"],
                    "title": value["content"]["title"][:160],
                    "problem": value["content"]["problem"][:160],
                    "summary": value["content"]["summary"][:160],
                    "event_type": value["content"]["event_type"],
                    "status": value["content"]["status"],
                    "evidence": [{"paragraph_id": value["content"]["evidence_paragraph_id"]}]
                    if value["content"]["evidence_paragraph_id"] is not None
                    else [],
                }
                for value in reads
            ]
        # 条数是唯一分页口径；索引不带无界人物列表，详情仍在 read_event 中完整保留
        page = previews
        for value in reads:
            event_reads[value["node_id"]] = value
        case_reads.extend(page)
        next_offset = offset + len(page)
        return json.dumps(
            {
                "events": page,
                "total": len(identifiers),
                "next_offset": next_offset if next_offset < len(identifiers) else None,
            },
            ensure_ascii=False,
            separators=(",", ":"),
        )

    @tool
    def read_event(node_id: str, kind: ObjectKind = "event") -> str:
        """按实际事件身份读取详情，叙事线与结果使用各自 kind"""
        if kind != "event":
            if organization is None:
                raise ValueError(f"本执行不提供 kind={kind} 的诊断对象")
            value = organization.read(kind, node_id)
        else:
            resolved = resolve_event(node_id)
            value = events.read(resolved)
            event_reads[resolved] = value
        case_reads.append(value)
        return json.dumps(value, ensure_ascii=False)

    @tool
    def search_graph(
        query: str = "",
        entity_type: EntityType | None = None,
        limit: SearchLimit = 5,
        offset: SearchOffset = 0,
        relation_offset: SearchOffset = 0,
    ) -> str:
        """分页预览实体和命中端点的关系，两组续页独立，read_entity 读取完整属性

        query 按空白/标点拆分词项、任一命中实体名即召回（% 匹配任意长度、_ 匹配单字符），
        不填不按词项过滤。
        """
        terms = query_search_terms(query)
        matching = {
            key
            for key, name in graph.entity_names.items()
            if (not terms or any(term_matches(term, name) for term in terms))
            and (entity_type is None or str(graph.entity_types[key]) == entity_type)
        }
        values = [
            {"id": graph.entity_id_for_key(key), "name": name[:160], "entity_type": graph.entity_types[key]}
            for key, name in sorted(graph.entity_names.items())
            if key in matching
        ]
        relations = [
            {
                "source_id": graph.entity_id_for_key(left),
                "target_id": graph.entity_id_for_key(right),
                "relation_type": kind,
            }
            for left, right, kind in sorted(graph.active_relations)
            if left in matching or right in matching
        ]
        entities_page, next_offset = _search_page(values, offset=offset, limit=limit, budget=2600)
        relations_page, next_relation_offset = _search_page(relations, offset=relation_offset, limit=limit, budget=2600)
        entity_ids.update(value["id"] for value in entities_page)
        entity_ids.update(value[field] for value in relations_page for field in ("source_id", "target_id"))
        case_reads.extend([*entities_page, *relations_page])
        return json.dumps(
            {
                "entities": entities_page,
                "relations": relations_page,
                "total_entities": len(values),
                "total_relations": len(relations),
                "next_offset": next_offset,
                "next_relation_offset": next_relation_offset,
            },
            ensure_ascii=False,
            separators=(",", ":"),
        )

    @tool
    def read_entity(entity_id: str) -> str:
        """按真实实体 UUID 读取规范名、类型与属性，不授权未读过的原文"""
        key = graph.resolve_entity_id(entity_id, label="entity_id")
        value = {
            "id": entity_id,
            "name": graph.display_name(key),
            "entity_type": graph.entity_types[key],
            "attributes": graph.entity_attributes.get(key, {}),
        }
        entity_ids.add(entity_id)
        case_reads.append(value)
        return json.dumps(value, ensure_ascii=False)

    return [search_events, read_event, search_graph, read_entity]


def build_case_tools(
    pool: Any,
    author: str,
    *,
    on_claim: Callable[[], None] | None = None,
    case_view: Callable[[dict[str, Any]], dict[str, Any]] | None = None,
) -> list[Any]:
    """案例池登记、接手承诺与检索共用实现，作者是实际执行身份（真实执行号或程序 work 身份）"""

    @tool
    def push_case(
        case_type: Annotated[
            Literal["character", "relation", "dialogue", "event"],
            Field(description="案例类型：人物/关系/对话/事件四类之一"),
        ],
        description: str,
    ) -> str:
        """登记非空、100字以内的文字案例并显式归入人物/关系/对话/事件之一"""
        return json.dumps(pool.push(case_type, description, author), ensure_ascii=False)

    @tool
    def promise_case(case_id: str) -> str:
        """接手承诺一个真实案例：承诺即视为解决，随后由你调用写入工具完成处置；
        已被他人承诺返回 taken；只填 search_cases 返回的真实 case_id"""
        result = pool.promise(case_id, author)
        if result["status"] == "promised" and on_claim is not None:
            on_claim()
        return json.dumps(result, ensure_ascii=False)

    @tool
    def search_cases(case_type: str | None = None, unresolved_only: bool = False) -> str:
        """读取当前 run 的案例 ID、说明及 claimed/submitted；unresolved_only=true 只返回未提交案例"""
        cases = pool.search(case_type=case_type)
        if unresolved_only:
            cases = [case for case in cases if not case["submitted"]]
        if case_view is not None:
            cases = [case_view(case) for case in cases]
        return json.dumps(cases, ensure_ascii=False)

    return [push_case, promise_case, search_cases]


def build_finish_tool(request_end: Callable[[], dict[str, Any]]) -> Any:
    """复用结束请求入口，完整性与保存由对应 agent 负责"""

    @tool
    def finish() -> str:
        """请求本批次执行完毕后的完整性检查，不提交报告、不自动保存"""
        return json.dumps(request_end(), ensure_ascii=False)

    return finish
