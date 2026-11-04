"""检索语义契约：多词任一命中、%/_ 通配符、语义相近原文追加召回

按行为面锁定三个检索工具一致的承诺语义。
"""

from __future__ import annotations

import json
from types import SimpleNamespace

from src.agents.annotation.shared_tools import build_case_tools, build_state_read_tools
from src.agents.diagnosis.read_context import DiagnosisAnnotationEventSource
from src.event_trees.models import BoundEvent, EventParticipantInput
from src.event_trees.trees import EventTrees
from src.fact_graph.graph import FactGraph
from src.fact_graph.inputs import EntityInput
from tests.support.storage_fixtures import fixture_id


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
        event_id=node_id,
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
        from_chapter_id=1,
        to_chapter_id=1,
    )


def _trees(*events: BoundEvent) -> EventTrees:
    trees = EventTrees("run-search")
    trees.begin(fixture_id(__name__, "exec-1"))
    trees.sync(fixture_id(__name__, "exec-1"), 8, list(events))
    trees.confirm(fixture_id(__name__, "exec-1"))
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


class _SemanticStub:
    "固定返回给定段落身份，None 表示语义检索不可用"

    def __init__(self, paragraph_ids):
        self._paragraph_ids = paragraph_ids

    def paragraph_ids(self, query: str, *, limit: int = 20):
        return self._paragraph_ids


def _state_tools(events, *, semantic=None, graph=None):
    graph = graph or SimpleNamespace(entity_names={}, entity_types={}, active_relations=[])
    tools = build_state_read_tools(
        graph,
        events,
        event_reads={},
        entity_ids=set(),
        case_reads=[],
        resolve_event=lambda identifier: identifier,
        semantic=semantic,
    )
    return {tool.name: tool for tool in tools}


def test_event_search_appends_semantic_paragraph_hits_and_notes_degradation() -> None:
    trees = _trees(_event("n-jin", title="素阳金幻象显乱世"), _event("n-snake", title="井底蛇影", paragraph=7))
    tools = _state_tools(trees, semantic=_SemanticStub([7]))
    payload = json.loads(tools["search_events"].invoke({"query": "毫无关系的词"}))
    assert [item["event_id"] for item in payload["events"]] == ["n-snake"]
    degraded = json.loads(
        _state_tools(trees, semantic=_SemanticStub(None))["search_events"].invoke({"query": "素阳金"})
    )
    assert degraded["semantic"] == "unavailable"


def _graph_tool_with_participants(*names: str):
    events = SimpleNamespace(
        search_ids=lambda *args, **kwargs: [],
        participant_names_for_paragraphs=lambda paragraph_ids: ["白芷"],
    )
    return _state_tools(events, semantic=_SemanticStub([3]), graph=_graph_with_name_entities(*names))["search_graph"]


def test_entity_search_appends_semantic_participant_names_and_notes_degradation() -> None:
    tool = _graph_tool_with_participants("白芷", "周凤兰")
    payload = json.loads(tool.invoke({"query": "不相干的词"}))
    assert [item["name"] for item in payload["entities"]] == ["白芷"]
    events = SimpleNamespace(
        search_ids=lambda *args, **kwargs: [],
        participant_names_for_paragraphs=lambda paragraph_ids: ["白芷"],
    )
    degraded = json.loads(
        _state_tools(events, semantic=_SemanticStub(None), graph=_graph_with_name_entities("白芷"))[
            "search_graph"
        ].invoke({"query": "不相干的词"})
    )
    assert degraded["semantic"] == "unavailable"


class _PoolStub:
    def __init__(self, cases):
        self.cases = cases

    def search(self, case_type=None):
        return [case for case in self.cases if case_type is None or case["case_type"] == case_type]

    def claims_for(self, author):
        return []


def _case_tool(semantic, tree_ids, cases):
    tools = build_case_tools(
        _PoolStub(cases),
        "exec",
        semantic=semantic,
        semantic_tree_ids=tree_ids,
    )
    return next(tool for tool in tools if tool.name == "search_cases")


def test_case_search_maps_semantic_paragraphs_to_tree_cases() -> None:
    cases = [
        {
            "case_id": "c-tree",
            "case_type": "event",
            "description": "事件树 t1 未归并",
            "submitted": False,
            "tree_id": "t1",
        },
        {"case_id": "c-other", "case_type": "character", "description": "核对顾霜身份", "submitted": False},
    ]
    tool = _case_tool(_SemanticStub([9]), lambda paragraph_ids: ["t1"], cases)
    payload = json.loads(tool.invoke({"query": "山门关闭"}))
    assert [case["case_id"] for case in payload["cases"]] == ["c-tree"]
    degraded = json.loads(_case_tool(_SemanticStub(None), lambda ids: [], cases).invoke({"query": "山门关闭"}))
    assert degraded["semantic"] == "unavailable"


def test_diagnosis_event_source_wildcards_terms_and_semantic_paragraphs() -> None:
    events = {
        "n-jin": {"event_id": "n-jin", "title": "素阳金幻象显乱世", "problem": "来历存疑", "summary": "槐叶讲解",
                  "evidence_paragraph_id": 4, "from": 1, "to": 1, "participants": []},
        "n-snake": {"event_id": "n-snake", "title": "井底蛇影", "problem": "是否现身", "summary": "黑袍男子消失",
                    "evidence_paragraph_id": 9, "from": 2, "to": 2, "participants": []},
    }
    draft = SimpleNamespace(
        read_view=lambda: (events, SimpleNamespace(event_tree={"n-jin": "t1", "n-snake": "t2"}, queues={})),
        _event_hierarchy=lambda key, parents: {},
        read_events=lambda ids: [events[identifier] for identifier in ids],
    )
    source = DiagnosisAnnotationEventSource(draft)
    identifiers, _ = source.search_page(
        "槐叶，黑袍", chapter_id=None, tree_id=None, isforeshadowing=None, offset=0, limit=0
    )
    assert identifiers == ["n-jin", "n-snake"]
    wildcard, _ = source.search_page(
        "素阳%乱世", chapter_id=None, tree_id=None, isforeshadowing=None, offset=0, limit=0
    )
    assert wildcard == ["n-jin"]
    semantic, _ = source.search_page(
        "无关查询", chapter_id=None, tree_id=None, isforeshadowing=None, offset=0, limit=0, semantic_paragraph_ids=[9]
    )
    assert semantic == ["n-snake"]
