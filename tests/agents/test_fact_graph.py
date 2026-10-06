"""正式章节局部图的稳定身份、关系幂等、操作日志与回滚测试"""

from __future__ import annotations

import pytest

from src.agents.annotation.schema import EntityInput, RelationInput
from src.fact_graph.graph import FactGraph


def _entity(name: str, **attributes: object) -> EntityInput:
    return EntityInput(name=name, entity_type="character", **attributes)


def _relation(from_name: str = "顾霜", to_name: str = "顾老", relation_type: str = "同一人物") -> RelationInput:
    return RelationInput(from_entity=from_name, to_entity=to_name, relation_type=relation_type)


def test_entities_append_and_update_attributes() -> None:
    graph = FactGraph()
    graph.register_entities([_entity("顾霜", tags=["主角"], description="青年",
                                     attributes={"status": "active", "nickname": "小顾"})])
    graph.register_entities([_entity("顾老"), _entity("顾霜", attributes={"status": "retired", "nickname": None})])
    assert graph.entity_type("顾霜") == "character" and graph.entity_type("顾老") == "character"
    assert graph.entity_tags["顾霜"] == ["主角"]
    assert graph.entity_attributes["顾霜"] == {"description": "青年", "status": "retired"}


def test_relations_are_idempotent_and_symmetric_when_bidirectional() -> None:
    graph = FactGraph()
    assert graph.apply_relation(_relation())
    assert not graph.apply_relation(_relation("顾老", "顾霜"))
    assert ("顾老", "顾霜", "同一人物") in graph.active_relations
    assert graph.relation_attributes[("顾老", "顾霜", "同一人物")]["support_count"] == 1


def test_directional_relation_keeps_endpoint_order() -> None:
    graph = FactGraph()
    graph.apply_relation(_relation("顾霜", "贺府", "隶属"))
    assert ("顾霜", "贺府", "隶属") in graph.active_relations
    assert ("贺府", "顾霜", "隶属") not in graph.active_relations


def test_snapshot_restore_rolls_back_local_changes_and_logs() -> None:
    graph = FactGraph()
    graph.register_entities([_entity("顾霜")])
    baseline = graph.snapshot()
    graph.register_entities([_entity("顾老")])
    graph.apply_relation(_relation())
    graph.record_entity_ops([_entity("顾老")], chapter_id=1)
    graph.record_relation_asserts([_relation()], chapter_id=1)
    graph.restore(baseline)
    assert graph.entity_type("顾老") is None and graph.entity_type("顾霜") == "character"
    assert not graph.active_relations
    assert graph.drain_ops() == {"entity_ops": [], "relation_assert_ops": []}


def test_local_graphs_do_not_share_state_between_chapters() -> None:
    first = FactGraph(run_scope="run-1")
    first.register_entities([_entity("顾霜")])
    first.apply_relation(_relation())
    second = FactGraph(run_scope="run-1")
    assert second.entity_type("顾霜") is None and not second.active_relations
    second.register_entities([_entity("顾霜")])
    assert first.entity_id("顾霜") == second.entity_id("顾霜")


def test_relation_replacement_resets_local_support_count() -> None:
    graph = FactGraph()
    graph.apply_relation(_relation())
    graph.reset_chapter_relations()
    assert not graph.active_relations and not graph.relation_attributes
    graph.apply_relation(_relation())
    assert graph.relation_attributes[("顾老", "顾霜", "同一人物")]["support_count"] == 1


def _alias_graph(*, flagged: bool = True) -> FactGraph:
    graph = FactGraph()
    graph.register_entities([_entity("顾霜"), _entity("顾老", attributes={"is_representative": flagged})])
    graph.apply_relation(_relation())
    return graph


def test_alias_resolution_uses_representative_flag() -> None:
    graph = _alias_graph()
    assert graph.resolve_name("顾霜") == "顾老"
    assert graph.resolve_name("顾老") == "顾老"
    assert graph.alias_group("顾霜") == ["顾老"]
    assert graph.alias_group("路人") == []


def test_alias_resolution_without_flag_uses_registration_order() -> None:
    graph = _alias_graph(flagged=False)
    assert graph.resolve_name("顾老") == "顾霜"
    assert not graph.apply_relation(_relation())
    assert graph.resolve_name("顾老") == "顾霜"


def test_entity_ids_are_stable_normalized_and_scoped_to_run() -> None:
    graph = FactGraph(run_scope="run-1")
    assigned = graph.register_entities([_entity("Hero")])
    entity_id, display_name = assigned[0]
    assert display_name == "Hero" and entity_id == graph.entity_id("hero")
    graph.register_entities([_entity("HERO")])
    assert graph.entity_id("Hero") == entity_id
    replay = FactGraph(run_scope="run-1")
    replay.register_entities([_entity("hero")])
    assert replay.entity_id("hero") == entity_id
    another = FactGraph(run_scope="run-2")
    another.register_entities([_entity("hero")])
    assert another.entity_id("hero") != entity_id
    assert graph.entity_id("unknown") is None


def test_entity_id_resolution_does_not_merge_aliases() -> None:
    graph = _alias_graph()
    entity_id = graph.entity_id("顾霜")
    assert entity_id is not None
    assert graph.resolve_entity_id(entity_id, label="participant") == "顾霜"


def test_rolled_back_registration_is_not_resolvable_and_retry_keeps_id() -> None:
    graph = FactGraph(run_scope="run-1")
    baseline = graph.snapshot()
    graph.register_entities([_entity("顾霜")])
    entity_id = graph.entity_id("顾霜")
    assert entity_id is not None
    graph.restore(baseline)
    with pytest.raises(ValueError, match="未登记"):
        graph.resolve_entity_id(entity_id, label="participant")
    graph.register_entities([_entity("顾霜")])
    assert graph.entity_id("顾霜") == entity_id


def test_operation_logs_keep_chapter_identity_and_drain_once() -> None:
    graph = FactGraph()
    graph.record_entity_ops([_entity("顾霜", tags=["主角"])], chapter_id=3)
    graph.record_entity_ops([_entity("顾老")], chapter_id=3)
    graph.record_relation_asserts([_relation()], chapter_id=3)
    operations = graph.drain_ops()
    assert [operation["name"] for operation in operations["entity_ops"]] == ["顾霜", "顾老"]
    assert all(operation["chapter_id"] == 3 for operation in operations["entity_ops"])
    assert operations["relation_assert_ops"] == [
        {"from_entity": "顾霜", "to_entity": "顾老", "relation_type": "同一人物", "chapter_id": 3}
    ]
    assert graph.drain_ops() == {"entity_ops": [], "relation_assert_ops": []}
