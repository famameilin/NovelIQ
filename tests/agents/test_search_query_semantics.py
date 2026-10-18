"""检索语义契约：多词任一命中、%/_ 通配符、事件与实体召回面

按行为面锁定三个检索工具一致的承诺语义。
"""

from __future__ import annotations

import json
from types import SimpleNamespace

from src.agents.annotation.shared_tools import build_state_read_tools
from src.event_trees.models import BoundEvent, EventParticipantInput
from src.event_trees.trees import EventTrees
from src.fact_graph.graph import FactGraph
from src.fact_graph.inputs import EntityInput


def _event(
    node_id: str,
    *,
    title: str = "众人动身",
    problem: str = "事件问题",
    summary: str = "事件概要",
    description: str = "事件描述",
    paragraph: int = 1,
    participants: list[EventParticipantInput] | None = None,
) -> BoundEvent:
    """构造单根事件声明，正文各字段可单独给检索词"""
    return BoundEvent(
        declaration_id=node_id,
        node_id=node_id,
        tree_id=f"tree-{node_id}",
        parent_node_id=None,
        cause_role="root",
        title=title,
        problem=problem,
        summary=summary,
        event_type="行动",
        status="ongoing",
        description=description,
        evidence_paragraph_id=paragraph,
        participants=participants or [],
    )


def _trees(*events: BoundEvent) -> EventTrees:
    trees = EventTrees("run-search")
    trees.begin("exec-1")
    trees.sync("exec-1", 8, list(events))
    return trees


def test_event_search_recalls_title_problem_summary_and_description() -> None:
    trees = _trees(
        _event("n-title", title="素阳金幻象显乱世"),
        _event("n-problem", problem="素阳金来历存疑"),
        _event("n-summary", summary="槐叶提到素阳金"),
        _event("n-description", description="素阳金沉入井底"),
        _event("n-control", title="无关联事件"),
    )
    assert set(trees.search_ids("素阳金")) == {"n-title", "n-problem", "n-summary", "n-description"}


def test_event_search_splits_terms_and_matches_any() -> None:
    trees = _trees(
        _event("n-huaiye", summary="槐叶讲解来历"),
        _event("n-heipao", description="黑袍男子消失"),
        _event("n-control", title="无关联事件"),
    )
    assert set(trees.search_ids("槐叶，黑袍")) == {"n-huaiye", "n-heipao"}


def test_event_search_wildcards_and_literal_control() -> None:
    trees = _trees(_event("n-jin", title="素阳金幻象显乱世"))
    assert trees.search_ids("素阳%乱世") == ["n-jin"]
    assert trees.search_ids("素阳_幻象") == ["n-jin"]
    assert trees.search_ids("素阳幻象") == []


def test_event_search_recalls_participant_names() -> None:
    trees = _trees(
        _event(
            "n-party",
            participants=[EventParticipantInput(entity="白芷", role="主体", action="当众揭示身世")],
        )
    )
    assert trees.search_ids("白芷") == ["n-party"]


def test_event_search_empty_query_returns_all_and_unknown_term_hits_nothing() -> None:
    trees = _trees(_event("n-a"), _event("n-b"))
    assert set(trees.search_ids("")) == {"n-a", "n-b"}
    assert trees.search_ids("查无此词") == []


def _search_graph_tool(graph: FactGraph):
    """单独装配实体检索工具，只验证 search_graph 的名字匹配语义"""
    events = SimpleNamespace(search_ids=lambda *args, **kwargs: [])
    tools = build_state_read_tools(
        graph,
        events,
        event_reads={},
        entity_ids=set(),
        case_reads=[],
        resolve_event=lambda identifier: identifier,
    )
    return next(tool for tool in tools if tool.name == "search_graph")


def _graph_with_name_entities(*names: str) -> FactGraph:
    graph = FactGraph(run_scope="run-search")
    graph.register_entities([EntityInput(name=name, entity_type="character") for name in names])
    return graph


def test_entity_search_multi_name_any_hit() -> None:
    tool = _search_graph_tool(_graph_with_name_entities("周凤兰", "赵兰英", "柳婉儿", "黑袍男子"))
    payload = json.loads(tool.invoke({"query": "周凤兰 赵兰英 柳婉儿"}))
    assert {item["name"] for item in payload["entities"]} == {"周凤兰", "赵兰英", "柳婉儿"}


def test_entity_search_wildcards_and_empty_query() -> None:
    tool = _search_graph_tool(_graph_with_name_entities("周凤兰", "赵兰英"))
    assert [item["name"] for item in json.loads(tool.invoke({"query": "周_"}))["entities"]] == ["周凤兰"]
    assert {item["name"] for item in json.loads(tool.invoke({"query": ""}))["entities"]} == {"周凤兰", "赵兰英"}
