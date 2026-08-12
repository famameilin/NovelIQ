"""同 run 人物别名消歧解析测试"""

from __future__ import annotations

from types import SimpleNamespace

from src.knowledge.authority.alias import build_alias_resolution


def _relation(
    *,
    relation_semantics: str = "same_character",
    is_active: bool = True,
    from_entity_id: int,
    to_entity_id: int,
) -> SimpleNamespace:
    """2026-08-09 用于构造 alias 解析所需的稳定关系快照桩"""
    return SimpleNamespace(
        relation_semantics=relation_semantics,
        is_active=is_active,
        from_entity_id=from_entity_id,
        to_entity_id=to_entity_id,
    )


def _entity(entity_id: int, name: str, *, representative: bool = False) -> SimpleNamespace:
    """2026-08-11 用于构造带 is_representative 属性的实体快照桩"""
    return SimpleNamespace(
        entity_id=entity_id,
        name=name,
        attributes={"is_representative": True} if representative else {},
    )


def test_build_alias_resolution_merges_direct_aliases() -> None:
    """2026-08-11 用于验证同一人物关系直接把别名归一到代表实体"""
    relations = [
        _relation(from_entity_id=67, to_entity_id=97),
    ]
    entities = [
        _entity(38, "贺伯安"),
        _entity(67, "伯安", representative=True),
        _entity(97, "贺重明"),
    ]

    resolution = build_alias_resolution(relations, entities=entities)

    assert resolution.resolve_entity_id(67) == 67
    assert resolution.resolve_entity_id(97) == 67
    assert resolution.resolve_entity_id(38) == 38
    assert resolution.resolve_name("贺重明") == "伯安"
    assert resolution.resolve_name("贺伯安") == "贺伯安"
    assert resolution.aliases_by_representative[67] == ["贺重明"]


def test_build_alias_resolution_resolves_transitive_chain() -> None:
    """2026-08-11 用于验证别名链 A→B、B→C 收敛到同一代表"""
    relations = [
        _relation(from_entity_id=80, to_entity_id=70),
        _relation(from_entity_id=90, to_entity_id=80),
    ]
    entities = [
        _entity(70, "老李", representative=True),
        _entity(80, "李哥"),
        _entity(90, "李爷"),
    ]

    resolution = build_alias_resolution(relations, entities=entities)

    assert resolution.resolve_entity_id(90) == 70
    assert resolution.resolve_entity_id(80) == 70
    assert resolution.resolve_name("李爷") == "老李"
    assert resolution.resolve_name("李哥") == "老李"
    assert sorted(resolution.aliases_by_representative[70]) == ["李哥", "李爷"]


def test_build_alias_resolution_ignores_ordinary_and_inactive_relations() -> None:
    """2026-08-11 用于验证普通关系与非活动同一人物关系不参与归并"""
    relations = [
        _relation(relation_semantics="ordinary", from_entity_id=10, to_entity_id=20),
        _relation(from_entity_id=30, to_entity_id=40, is_active=False),
    ]
    entities = [
        _entity(10, "甲"),
        _entity(20, "乙"),
        _entity(30, "丙"),
        _entity(40, "丁"),
    ]

    resolution = build_alias_resolution(relations, entities=entities)

    assert resolution.representative_by_alias == {}
    assert resolution.name_to_representative == {}


def test_build_alias_resolution_falls_back_to_min_entity_id() -> None:
    """2026-08-11 用于验证缺失代表标记时回退到端点较小实体 ID"""
    relations = [
        _relation(from_entity_id=88, to_entity_id=55),
    ]
    entities = [
        _entity(55, "小五"),
        _entity(88, "老八"),
    ]

    resolution = build_alias_resolution(relations, entities=entities)

    assert resolution.resolve_entity_id(88) == 55
    assert resolution.resolve_name("老八") == "小五"


def test_build_alias_resolution_maps_same_name_alias_to_representative() -> None:
    """2026-08-12 用于验证别名与代表同名时 name 映射与别名注册不丢失

    别名 id 归并到代表 id 的同时，name 映射必须保留（恒等映射），
    否则边端点的 id 已归并而 name 未归并，造成 id/name 不一致。
    """
    relations = [
        _relation(from_entity_id=67, to_entity_id=99),
    ]
    entities = [
        _entity(67, "伯安", representative=True),
        _entity(99, "伯安"),
    ]

    resolution = build_alias_resolution(relations, entities=entities)

    assert resolution.resolve_entity_id(99) == 67
    assert resolution.resolve_entity_id(67) == 67
    assert resolution.name_to_representative["伯安"] == "伯安"
    assert "伯安" in resolution.aliases_by_representative[67]
