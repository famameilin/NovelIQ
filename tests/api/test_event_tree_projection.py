"""事件树投影保留完整成员、真实层级和关系方向"""

from dataclasses import replace
from types import SimpleNamespace

import pytest

from src.event_trees.queues import QueueGraph
from src.event_trees.read.organization import EventTreeQuery
from src.event_trees.read.organization_models import EventView, LinkView


def event(identifier: str, position: int) -> EventView:
    return EventView(
        event_id=identifier,
        producer_agent_id="producer",
        local_key=identifier,
        reason="事件依据",
        title=identifier,
        problem="事件待解决的问题",
        summary="事件概要",
        event_type="行动",
        status="ongoing",
        progress=None,
        first_text_position=position,
        evidence=[],
        source_agent_id="producer",
        annotation_record_id=None,
        from_chapter_id=11,
        to_chapter_id=29,
        chapter_id=None,
        chapter_order=None,
        participants=[],
        is_foreshadowing_root=False,
        payoff_likelihood=None,
        char_start=position,
        char_end=position + 1,
    )


def loaded_query(monkeypatch, identifiers, links, *, queues=None, selected=None) -> EventTreeQuery:
    query = EventTreeQuery(object(), "run")
    query._loaded = True
    query.organization_status = "pending_diagnosis"
    query.chapters = [{"chapter_id": 11, "chapter_order": 1, "title": "起始"}]
    query.orders = {11: 1, 29: 2}
    query.events = {identifier: event(identifier, position) for position, identifier in enumerate(identifiers)}
    trees = {f"tree-{key}": list(members) for key, members in (queues or {key: [key] for key in identifiers}).items()}
    owner = {member: tree_id for tree_id, members in trees.items() for member in members}
    query.graph = QueueGraph(trees, [(owner[parent], owner[child]) for parent, child in links], identifiers)
    selected_trees = [owner.get(key, key) for key in selected] if selected is not None else list(query.graph.unparented)
    query.event_line_ids = selected_trees
    query._tree_titles = dict(zip(trees, trees, strict=True))
    query._tree_descriptions = dict.fromkeys(trees, "树说明")
    if selected is not None:
        query.organization_status = "ready"
        line_entries = {members[0] for tree_id in selected_trees for members in [trees[tree_id]]}
        query.events = {
            key: replace(value, is_event_line=key in line_entries) for key, value in query.events.items()
        }
    query._line_members = {key: set(query.graph.tree_events(key)) for key in query.event_line_ids}
    query._structure_links = [
        SimpleNamespace(parent_tree_id=owner[parent], child_tree_id=owner[child], reason="整体包含部分")
        for parent, child in links
    ]
    evidence = [[{"paragraph_id": 3, "quote": f"{parent}包含{child}"}] for parent, child in links]
    monkeypatch.setattr(query, "_structure_evidence_payloads", lambda: evidence)
    query.outcomes = {}
    query.relations = []
    query.actions = []
    return query


def relation(identifier, source, target):
    return LinkView(
        relation_id=identifier,
        source_kind="event",
        source_id=source,
        target_kind="event",
        target_id=target,
        relation_type="causal",
        reason="原文因果",
        evidence=[{"paragraph_id": 4}],
        producer_agent_id="producer",
        source_operation_id=identifier,
    )


def tree(key: str) -> str:
    return f"tree-{key}"


def test_full_projection_preserves_native_queue_order_and_event_identity(monkeypatch):
    query = loaded_query(
        monkeypatch,
        ["root", "child", "grandchild", "single"],
        [("root", "child")],
        queues={"root": ["root"], "child": ["child", "grandchild"], "single": ["single"]},
    )
    data = query.fetch()
    assert data["event_line_ids"] == [tree("root"), tree("single")]
    assert {q["tree_id"]: q["event_ids"] for q in data["queues"]}[tree("child")] == ["child", "grandchild"]
    assert [row["event_id"] for row in data["events"]] == ["root", "child", "grandchild", "single"]
    assert data["counts"]["trees"] == 3 and data["counts"]["all_events"] == 4
    assert query.detail("grandchild")["tree_position"] == 1
    assert query.detail("grandchild")["direct_parents"][0]["event_id"] == "child"
    assert data["next_cursor"] is None


def test_projection_preserves_parent_references_and_semantic_direction(monkeypatch):
    query = loaded_query(monkeypatch, ["root", "child", "other"], [("root", "child")])
    query.relations = [relation("cause", "child", "other")]
    data = query.fetch()
    assert data["queue_references"] == [
        {
            "parent_tree_id": tree("root"),
            "child_tree_id": tree("child"),
            "reason": "整体包含部分",
            "evidence": [{"paragraph_id": 3, "quote": "root包含child"}],
        }
    ]
    entry = data["relations"][0]
    assert (entry["source_id"], entry["target_id"], entry["relation_type"]) == ("child", "other", "causal")
    assert query.detail("child")["event_line_ids"] == [tree("root")]
    assert entry["locator"]["event_line_ids"] == [tree("other")]


def test_pending_projection_does_not_truncate_more_than_one_hundred_events(monkeypatch):
    roots = [f"root-{index}" for index in range(23)]
    children = [f"child-{index}" for index in range(125)]
    query = loaded_query(monkeypatch, roots + children, [(roots[0], child) for child in children])
    data = query.fetch()
    assert len(data["event_line_ids"]) == 23
    assert len(data["events"]) == len({row["event_id"] for row in data["events"]}) == 148
    assert len(data["queue_references"]) == 125


def test_semantic_edges_do_not_merge_event_lines(monkeypatch):
    query = loaded_query(monkeypatch, ["a", "a-child", "b", "b-child"], [("a", "a-child"), ("b", "b-child")])
    before = query.fetch()
    query.relations = [relation("a-to-b", "a-child", "b-child"), relation("b-to-a", "b-child", "a-child")]
    after = query.fetch()
    for key in ("event_line_ids", "queues", "queue_references", "events"):
        assert after[key] == before[key]
    assert after["counts"]["relations"] == 2
    entries = {item["relation_id"]: item for item in query.detail("a-child")["relations"]}
    assert set(entries) == {"a-to-b", "b-to-a"}
    assert all(entry["locator"]["target_id"] == "b-child" for entry in entries.values())


def test_shared_queue_keeps_one_native_identity_and_all_parent_contexts(monkeypatch):
    query = loaded_query(
        monkeypatch,
        ["a", "b", "shared", "leaf"],
        [("a", "shared"), ("b", "shared")],
        queues={"a": ["a"], "b": ["b"], "shared": ["shared", "leaf"]},
    )
    data = query.fetch()
    assert data["event_line_ids"] == [tree("a"), tree("b")]
    assert [row["event_id"] for row in data["events"]].count("shared") == 1
    assert {item["event_id"] for item in query.detail("shared")["direct_parents"]} == {"a", "b"}
    for identifier in ("shared", "leaf"):
        detail = query.detail(identifier)
        assert detail["tree_id"] == tree("shared") and detail["event_line_ids"] == [tree("a"), tree("b")]
    assert query.detail("leaf")["direct_parents"][0]["event_id"] == "shared"


def test_multiple_parent_rows_are_accepted_without_repair(monkeypatch):
    links = [("first", "child"), ("second", "child")]
    query = loaded_query(monkeypatch, ["first", "second", "child"], links)
    assert len(query.fetch()["queue_references"]) == 2
    assert links == [("first", "child"), ("second", "child")]
    with pytest.raises(ValueError, match="成环"):
        QueueGraph({key: [key] for key in query.events}, [*links, ("child", "first")], query.events)


def test_selected_inner_tree_preserves_all_data_and_maps_shared_contexts(monkeypatch):
    query = loaded_query(
        monkeypatch,
        ["prefix", "entry", "branch", "shared", "leaf", "unselected"],
        [("prefix", "shared"), ("branch", "shared")],
        queues={
            "prefix": ["prefix", "entry"],
            "branch": ["branch"],
            "shared": ["shared", "leaf"],
            "unselected": ["unselected"],
        },
        selected=["entry", "branch"],
    )
    data = query.fetch()
    assert data["event_line_ids"] == [tree("prefix"), tree("branch")]
    assert len(data["events"]) == 6 and len(data["queues"]) == 4
    assert {row["event_id"] for row in data["events"] if row["is_event_line"]} == {"prefix", "branch"}
    assert query.detail("leaf")["event_line_ids"] == [tree("prefix"), tree("branch")]
    assert query.detail("prefix")["event_line_ids"] == [tree("prefix")]
    assert query.detail("unselected")["event_line_ids"] == []
    assert query.detail("entry")["tree_id"] == tree("prefix")
    assert query.detail("entry")["is_event_line"] is False
