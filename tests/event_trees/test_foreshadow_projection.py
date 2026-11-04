"""伏笔挂载、原文证据和后端响应的无数据库验证"""

from dataclasses import replace
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from src.api.models.events import ForeshadowingActionResponse
from src.api.services.results_queries.event_projection import build_event_forest_response, serialize_snapshot_edges
from src.api.services.results_queries.foreshadowing_trees import _fetch_foreshadowing_trees
from src.event_trees.queues import QueueGraph
from src.event_trees.read import foreshadowing, forest
from src.event_trees.read.models import EventNodeRow
from src.event_trees.read.organization import EventTreeQuery
from src.event_trees.read.organization_models import EventView, ForeshadowingView, LinkView


@pytest.fixture
def query(monkeypatch):
    result = EventTreeQuery(SimpleNamespace(narrative=SimpleNamespace(fetch_evidence=lambda *_args: {})), "run")
    result._loaded = True
    result.organization_status = "pending_diagnosis"
    result.orders = {11: 1, 29: 2, 47: 3}
    result.chapters = [
        {"chapter_id": chapter, "chapter_order": order, "title": str(chapter)}
        for chapter, order in result.orders.items()
    ]
    result.paragraphs = {
        index: SimpleNamespace(paragraph_id=index, chapter_id=chapter, text=text)
        for index, chapter, text in [
            (0, 11, "众人启程"), (1, 11, "旧信暗示印章下落"),
            (2, 29, "线索再次出现"), (3, 29, "众人找到印章"), (4, 47, "其他事件"),
        ]
    }

    def evidence(paragraph_id):
        row = result.paragraphs[paragraph_id]
        return [{"chapter_id": row.chapter_id, "paragraph_id": paragraph_id,
                 "char_start": 0, "char_end": len(row.text), "text": row.text}]

    result.events = {}
    for position, (identifier, paragraph_id) in enumerate(
        [("head", 0), ("hint", 1), ("other", 0), ("shared", 2), ("target", 3), ("unrelated", 4)]
    ):
        chapter = result.paragraphs[paragraph_id].chapter_id
        result.events[identifier] = EventView(
            event_id=identifier, producer_agent_id="producer", local_key=identifier, reason="原文依据",
            title=identifier, problem="印章在哪里", summary=identifier, event_type="线索", status="ongoing",
            progress=None, first_text_position=position * 10, evidence=evidence(paragraph_id),
            source_agent_id="producer", annotation_record_id="annotation", from_chapter_id=chapter,
            to_chapter_id=chapter, chapter_id=chapter, chapter_order=result.orders[chapter], participants=[],
            is_foreshadowing_root=identifier == "hint", payoff_likelihood="high" if identifier == "hint" else None,
            char_start=position * 10, char_end=position * 10 + 1,
        )
    result.graph = QueueGraph(
        {"tA": ["head", "hint"], "tB": ["other"], "tC": ["shared", "target"],
         "tD": ["unrelated"]},
        [("tA", "tC"), ("tB", "tC")], result.events,
    )
    result._tree_titles = {"tA": "head", "tB": "other", "tC": "shared", "tD": "unrelated"}
    result._tree_descriptions = dict(result._tree_titles)
    result.event_line_ids = list(result.graph.unparented)
    result._line_members = {key: set(result.graph.tree_events(key)) for key in result.event_line_ids}
    result._structure_links = []
    result.outcomes = {}
    result.relations = []
    result.actions = [
        ForeshadowingView(
            action_id="payoff", action_type="payoff", endpoint_kind="event", source_event_id="hint",
            target_event_id="target", chapter_id=29, chapter_order=2, source_operation_id="payoff",
            operation_order=1, evidence=evidence(3),
        ),
        ForeshadowingView(
            action_id="setup", action_type="setup", endpoint_kind="event", source_event_id="hint",
            target_event_id="hint", chapter_id=11, chapter_order=1, source_operation_id="setup/hint",
            operation_order=0, evidence=evidence(1),
        ),
        ForeshadowingView(
            action_id="reinforce", action_type="reinforce", endpoint_kind="event", source_event_id="hint",
            target_event_id=None, chapter_id=29, chapter_order=2, source_operation_id="reinforce",
            operation_order=8, evidence=evidence(2),
        ),
    ]
    monkeypatch.setattr(foreshadowing, "EventTreeQuery", lambda *_args: result)
    return result


def test_inner_event_and_shared_target_keep_native_locations_and_single_actions(query):
    query._validate_saved_contract()
    before = (dict(query.graph.queues), query._reference_entries(), list(query.event_line_ids))
    data = query.fetch()
    actions = data["foreshadowing_actions"]
    assert [item["action_id"] for item in actions] == ["setup", "reinforce", "payoff"]
    assert len({item["action_id"] for item in actions}) == data["counts"]["foreshadowing_actions"] == 3
    payoff = actions[-1]
    assert payoff["source_event_id"] == "hint" and payoff["source_locator"]["tree_id"] == "tA"
    assert payoff["source_locator"]["event_line_ids"] == ["tA"]
    assert payoff["target_locator"]["tree_id"] == "tC"
    assert payoff["target_locator"]["event_line_ids"] == ["tA", "tB"]
    assert (dict(query.graph.queues), query._reference_entries(), list(query.event_line_ids)) == before
    assert all("root_event_id" not in item and "tree_id" not in item for item in actions)


def test_event_details_expose_source_trajectory_and_target_related_action(query):
    source = query.detail("hint")
    target = query.detail("target")
    assert source["is_foreshadowing_root"] is True and source["payoff_likelihood"] == "high"
    assert [item["action_id"] for item in source["foreshadowing_actions"]] == ["setup", "reinforce", "payoff"]
    assert [item["action_id"] for item in target["foreshadowing_actions"]] == ["payoff"]
    assert target["is_foreshadowing_root"] is False and target["payoff_likelihood"] is None
    assert query.detail("unrelated")["foreshadowing_actions"] == []
    assert query.export()["foreshadowing_actions"] == query.fetch()["foreshadowing_actions"]


def test_no_target_action_preserves_its_own_chapter_and_paragraph(query):
    query.actions = [action for action in query.actions if action.action_type != "payoff"]
    row = foreshadowing.fetch_foreshadowing_trees(query.session, "run")[0]
    assert row.source_event_id == "hint" and row.source_locator["tree_id"] == "tA"
    assert row.target_event_id is None and row.target_locator is None
    assert row.first_chapter_id == 11 and row.last_chapter_id == 29
    assert row.anchor_chapter_ids == [11, 29] and row.status == "reinforced" and row.active is True
    latest = row.actions[-1]
    assert latest["evidence"][0]["paragraph_id"] == 2
    assert latest["evidence"][0]["chapter_id"] == latest["chapter_id"] == 29
    assert latest["source_locator"]["evidence_position"] == 10
    assert row.latest_reason is None


def test_status_and_expectation_follow_passage_order_without_changing_event_state(query, monkeypatch):
    monkeypatch.setattr(foreshadowing, "_foreshadowing_roots", lambda *_args: ([query.events["hint"]], {}))
    monkeypatch.setattr(foreshadowing, "load_foreshadowing_actions", lambda *_args: query.actions)
    row = foreshadowing.fetch_foreshadowing_trees(query.session, "run")[0]
    assert row.status == "likely_paid_off" and row.active is False
    assert foreshadowing.calculate_foreshadow_expectation(query.session, "run") == pytest.approx(1.0)
    assert query.events["hint"].status == "ongoing"
    query.actions = [action for action in query.actions if action.action_type != "payoff"]
    query.events["hint"] = replace(query.events["hint"], status="resolved")
    assert foreshadowing.fetch_foreshadowing_trees(query.session, "run")[0].status == "reinforced"


def test_chapter_projection_uses_explicit_source_identity_and_action_chapter(query, monkeypatch):
    monkeypatch.setattr(foreshadowing, "load_foreshadowing_actions", lambda *_args: query.actions)
    monkeypatch.setattr(foreshadowing.smap, "run_events", lambda *_args: query.events)
    rows = foreshadowing.foreshadowing_by_chapter(query.session, "run")
    assert rows[11]["foreshadowing_source_event_id"] == rows[29]["foreshadowing_source_event_id"] == "hint"
    assert "foreshadowing_root_event_id" not in rows[11]
    assert 47 not in rows


def test_response_assembly_preserves_full_trajectory_and_rejects_old_identity(query):
    row = _fetch_foreshadowing_trees("run", query.session)[0]
    payload = row.model_dump()
    assert payload["source_event_id"] == "hint" and payload["source_locator"]["tree_id"] == "tA"
    assert payload["target_event_id"] == "target"
    assert payload["target_locator"]["event_line_ids"] == ["tA", "tB"]
    assert len(payload["actions"]) == 3 and "root_event_id" not in payload and "tree_id" not in payload
    action = payload["actions"][-1]
    action["root_event_id"] = action.pop("source_event_id")
    with pytest.raises(ValidationError, match="source_event_id"):
        ForeshadowingActionResponse.model_validate(action)


def test_semantic_foreshadowing_relation_does_not_create_or_close_actions(query):
    query.actions = []
    query.relations = [LinkView(
        relation_id="echo", source_kind="event", source_id="hint", target_kind="event", target_id="target",
        relation_type="foreshadowing", reason="原文照应", evidence=query.events["target"].evidence,
        producer_agent_id="producer", source_operation_id="echo",
    )]
    assert query.fetch()["counts"]["foreshadowing_actions"] == 0
    assert query.detail("hint")["foreshadowing_actions"] == []
    assert len(query.detail("hint")["relations"]) == 1
    assert foreshadowing.fetch_foreshadowing_trees(query.session, "run") == []


@pytest.mark.parametrize("field,value,message", [
    ("source_event_id", "missing", "不属于本运行"),
    ("source_event_id", "head", "缺少埋设标记"),
    ("target_event_id", "missing", "不属于本运行"),
    ("chapter_id", 47, "有效来源章节"),
    ("chapter_order", 3, "有效来源章节"),
])
def test_read_validation_rejects_invalid_source_target_and_chapter(query, field, value, message):
    query.actions = [replace(query.actions[0], **{field: value})]
    with pytest.raises(ValueError, match=message):
        query._validate_saved_contract()


def test_action_evidence_cannot_borrow_the_source_event_chapter(query):
    query.actions = [replace(query.actions[0], evidence=query.events["hint"].evidence)]
    with pytest.raises(ValueError, match="证据与实际来源章节不一致"):
        query._validate_saved_contract()


def test_chapter_snapshot_and_timeline_serialize_only_visible_actions(query, monkeypatch):
    query.session.forest = SimpleNamespace()
    monkeypatch.setattr(forest, "EventTreeQuery", lambda *_args: query)
    reader = forest.EventForestQuery(query.session)
    monkeypatch.setattr(reader, "resolve_chapter_boundary", lambda *_args, **_kwargs: SimpleNamespace(
        chapter_id=11, chapter_order=1,
    ))
    nodes = [EventNodeRow(
        event_id=event.event_id, chapter_id=11, chapter_order=1, from_chapter_id=11, to_chapter_id=11,
        description=event.summary, participants=[], anchor_paragraph_ids=[event.evidence[0]["paragraph_id"]],
        char_start=event.char_start, char_end=event.char_end, evidence=event.evidence, causal_event_refs=[],
        tree_id="tA", cause_role="root", parent_event_ids=[], evidence_scope="paragraph",
        payload_path=event.payload_path, event_ordinal=position,
    ) for position, event in enumerate([query.events["head"], query.events["hint"]])]
    monkeypatch.setattr(reader, "_event_nodes", lambda *_args, **_kwargs: nodes)
    snapshot = reader.fetch_snapshot("run")
    assert snapshot is not None
    assert len(snapshot.foreshadowing_edges) == 1
    edge = snapshot.foreshadowing_edges[0]
    assert edge.source_event_id == "hint" and edge.source_locator["tree_id"] == "tA"
    assert edge.status == "open" and [item["action_id"] for item in edge.actions] == ["setup"]
    response = build_event_forest_response(snapshot)
    _, timeline = serialize_snapshot_edges(snapshot)
    assert response.foreshadowing_edges[0].model_dump() == timeline[0].model_dump()
    assert "tree_id" not in timeline[0].model_dump()
