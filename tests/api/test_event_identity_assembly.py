"""实体身份装配保持事件来源与章节边界"""

from copy import deepcopy
from types import SimpleNamespace

import pytest

from src.api.services.results_queries import event_trees as assembly
from src.fact_graph.read.alias import AliasResolution
from src.fact_graph.read.references import EntityReferenceProjection


@pytest.fixture
def event_reader(monkeypatch):
    participants = [
        {"entity": {"entity_id": "alias", "name": "旧称"}, "role": "主体", "emotion": 1},
        {"entity": {"entity_id": "alias", "name": "旧称"}, "role": "主体", "emotion": -1},
    ]
    raw = deepcopy(participants)
    reader = SimpleNamespace(
        detail=lambda event_id: {"event_id": event_id, "characters": [], "evidence": []},
        participant_references=lambda event_id: deepcopy(participants),
        chapter_detail=lambda chapter_id, event_id: {"event_id": event_id, "participants": deepcopy(participants)},
        export=lambda: {"details": [{"event_id": "event", "characters": []}]},
    )
    monkeypatch.setattr(assembly, "EventTreeQuery", lambda storage, run_id: reader)
    return participants, raw


def identity_projection(name):
    return EntityReferenceProjection(
        {"representative": SimpleNamespace(entity_id="representative", name=name, entity_type="character")},
        AliasResolution(representative_by_alias={"alias": "representative"}),
    )


def test_detail_and_export_share_identity_snapshot_without_changing_events(monkeypatch, event_reader):
    loads = []

    def load(storage, run_id, **kwargs):
        loads.append((run_id, kwargs))
        return identity_projection("规范名")

    monkeypatch.setattr(assembly.EntityReferenceProjection, "load", load)
    service = assembly.EventTreeReadService(object(), "run")
    expected = [{"entity_id": "representative", "name": "规范名", "role": "主体"}]
    assert service.detail("event")["characters"] == expected
    assert service.export()["details"][0]["characters"] == expected
    assert loads == [("run", {})]
    assert event_reader[0] == event_reader[1]


def test_chapter_projection_uses_explicit_boundary_and_keeps_distinct_states(monkeypatch, event_reader):
    boundary = object()
    monkeypatch.setattr(
        assembly,
        "graph_projection",
        lambda graph: SimpleNamespace(resolve_chapter_boundary=lambda run_id, chapter_id: boundary),
    )

    def load(storage, run_id, **kwargs):
        assert kwargs == {"boundary": boundary}
        return identity_projection("本章规范名")

    monkeypatch.setattr(assembly.EntityReferenceProjection, "load", load)
    service = assembly.EventTreeReadService(SimpleNamespace(graph=object()), "run")
    result = service.chapter_detail(11, "event")
    assert [item["emotion"] for item in result["participants"]] == [1, -1]
    assert all(item["entity"]["name"] == "本章规范名" for item in result["participants"])
    assert event_reader[0] == event_reader[1]
