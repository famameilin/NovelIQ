"""正式章节局部图的稳定身份、关系幂等、操作日志与回滚测试

2026-10-13 身份=规范名+实体大类：实体键是复合键（entity_key(名, 大类)），
同名不同类是两条独立身份；关系端点、active_relations、id 查询都按复合键。
"""

from __future__ import annotations

import pytest

from src.fact_graph.graph import FactGraph, entity_key
from src.fact_graph.inputs import BoundRelationInput, EntityInput


def _key(name: str, entity_type: str = "character") -> str:
    return entity_key(name, entity_type)


def _entity(name: str, **attributes: object) -> EntityInput:
    return EntityInput(name=name, entity_type="character", **attributes)


def _relation(from_name: str = "顾霜", to_name: str = "顾老", relation_type: str = "同一人物") -> BoundRelationInput:
    return BoundRelationInput(from_entity=_key(from_name), to_entity=_key(to_name), relation_type=relation_type)


def test_entities_append_and_update_explicit_fields() -> None:
    graph = FactGraph()
    graph.register_entities([_entity("顾霜", tags=["主角"], description="青年", representative=True)])
    graph.register_entities([_entity("顾老"), _entity("顾霜", description="毕业后", representative=False)])
    assert graph.entity_type_of("顾霜", "character") == "character"
    assert graph.entity_type_of("顾老", "character") == "character"
    assert graph.entity_tags[_key("顾霜")] == ["主角"]
    assert graph.entity_attributes[_key("顾霜")] == {"description": "毕业后"}


def test_same_name_different_type_are_distinct_entities() -> None:
    """2026-10-13 同名不同大类各自登记为独立身份、独立 id，互不覆盖"""
    graph = FactGraph(run_scope="run-1")
    graph.register_entities([EntityInput(name="圣城", entity_type="organization")])
    graph.register_entities([EntityInput(name="圣城", entity_type="location")])
    organization = graph.entity_id("圣城", "organization")
    location = graph.entity_id("圣城", "location")
    assert organization is not None and location is not None
    assert organization != location
    assert graph.entity_type_of("圣城", "organization") == "organization"
    assert graph.entity_type_of("圣城", "location") == "location"
    # 同 (名, 类) 重登记幂等：id 不变、不新增身份
    graph.register_entities([EntityInput(name="圣城", entity_type="location")])
    assert graph.entity_id("圣城", "location") == location


def test_relations_are_idempotent_and_symmetric_when_bidirectional() -> None:
    graph = FactGraph()
    assert graph.apply_relation(_relation())
    assert not graph.apply_relation(_relation("顾老", "顾霜"))
    assert (_key("顾老"), _key("顾霜"), "同一人物") in graph.active_relations
    assert graph.relation_attributes[(_key("顾老"), _key("顾霜"), "同一人物")]["support_count"] == 1


def test_directional_relation_keeps_endpoint_order() -> None:
    graph = FactGraph()
    graph.apply_relation(_relation("顾霜", "贺府", "隶属"))
    assert (_key("顾霜"), _key("贺府"), "隶属") in graph.active_relations
    assert (_key("贺府"), _key("顾霜"), "隶属") not in graph.active_relations


def test_snapshot_restore_rolls_back_local_changes_and_logs() -> None:
    graph = FactGraph()
    graph.register_entities([_entity("顾霜")])
    baseline = graph.snapshot()
    graph.register_entities([_entity("顾老")])
    graph.apply_relation(_relation())
    graph.record_entity_ops([_entity("顾老")], chapter_id=1)
    graph.record_relation_asserts([_relation()], chapter_id=1)
    graph.restore(baseline)
    assert graph.entity_type_of("顾老", "character") is None
    assert graph.entity_type_of("顾霜", "character") == "character"
    assert not graph.active_relations
    assert graph.drain_ops() == {"entity_ops": [], "relation_assert_ops": []}


def test_local_graphs_do_not_share_state_between_chapters() -> None:
    first = FactGraph(run_scope="run-1")
    first.register_entities([_entity("顾霜")])
    first.apply_relation(_relation())
    second = FactGraph(run_scope="run-1")
    assert second.entity_type_of("顾霜", "character") is None and not second.active_relations
    second.register_entities([_entity("顾霜")])
    assert first.entity_id("顾霜", "character") == second.entity_id("顾霜", "character")


def test_relation_replacement_resets_local_support_count() -> None:
    graph = FactGraph()
    graph.apply_relation(_relation())
    graph.reset_chapter_relations()
    assert not graph.active_relations and not graph.relation_attributes
    graph.apply_relation(_relation())
    assert graph.relation_attributes[(_key("顾老"), _key("顾霜"), "同一人物")]["support_count"] == 1


def _alias_graph(*, flagged: bool = True) -> FactGraph:
    graph = FactGraph()
    graph.register_entities([_entity("顾霜"), _entity("顾老", representative=flagged)])
    graph.apply_relation(_relation())
    return graph


def test_alias_resolution_uses_representative_flag() -> None:
    graph = _alias_graph()
    assert graph.resolve_name("顾霜", "character") == "顾老"
    assert graph.resolve_name("顾老", "character") == "顾老"
    assert graph.alias_group(_key("顾霜")) == ["顾老"]
    assert graph.alias_group(_key("路人")) == []


def test_alias_resolution_without_flag_uses_stable_identity() -> None:
    graph = _alias_graph(flagged=False)
    representative = min(graph.entity_names, key=lambda key: graph.entity_id_for_key(key) or "")
    assert graph.resolve_key(_key("顾老")) == representative
    assert not graph.apply_relation(_relation())
    assert graph.resolve_key(_key("顾霜")) == representative


def test_entity_ids_are_stable_normalized_and_scoped_to_run() -> None:
    graph = FactGraph(run_scope="run-1")
    assigned = graph.register_entities([_entity("Hero")])
    entity_id, display_name = assigned[0]
    assert display_name == "Hero" and entity_id == graph.entity_id("hero", "character")
    graph.register_entities([_entity("HERO")])
    assert graph.entity_id("Hero", "character") == entity_id
    replay = FactGraph(run_scope="run-1")
    replay.register_entities([_entity("hero")])
    assert replay.entity_id("hero", "character") == entity_id
    another = FactGraph(run_scope="run-2")
    another.register_entities([_entity("hero")])
    assert another.entity_id("hero", "character") != entity_id
    assert graph.entity_id("unknown", "character") is None


def test_entity_id_resolution_does_not_merge_aliases() -> None:
    graph = _alias_graph()
    entity_id = graph.entity_id("顾霜", "character")
    assert entity_id is not None
    key = graph.resolve_entity_id(entity_id, label="participant")
    assert graph.display_name(key) == "顾霜"


def test_rolled_back_registration_is_not_resolvable_and_retry_keeps_id() -> None:
    graph = FactGraph(run_scope="run-1")
    baseline = graph.snapshot()
    graph.register_entities([_entity("顾霜")])
    entity_id = graph.entity_id("顾霜", "character")
    assert entity_id is not None
    graph.restore(baseline)
    with pytest.raises(ValueError, match="未登记"):
        graph.resolve_entity_id(entity_id, label="participant")
    graph.register_entities([_entity("顾霜")])
    assert graph.entity_id("顾霜", "character") == entity_id


def test_operation_logs_keep_chapter_identity_and_drain_once() -> None:
    graph = FactGraph()
    graph.record_entity_ops([_entity("顾霜", tags=["主角"])], chapter_id=3)
    graph.record_entity_ops([_entity("顾老")], chapter_id=3)
    graph.record_relation_asserts([_relation()], chapter_id=3)
    operations = graph.drain_ops()
    assert [operation["name"] for operation in operations["entity_ops"]] == ["顾霜", "顾老"]
    assert all(operation["chapter_id"] == 3 for operation in operations["entity_ops"])
    assert operations["relation_assert_ops"] == [
        {"from_entity": _key("顾霜"), "to_entity": _key("顾老"), "relation_type": "同一人物", "chapter_id": 3}
    ]
    assert graph.drain_ops() == {"entity_ops": [], "relation_assert_ops": []}
