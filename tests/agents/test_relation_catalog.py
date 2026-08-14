"""关系目录与端点类型合同测试"""

from src.agents.annotation.schema import (
    RELATION_DEFINITIONS,
    RelationInput,
    relation_catalog_text,
)


def test_leader_relation_defined() -> None:
    definition = RELATION_DEFINITIONS["领导"]
    assert definition["directionality"] == "directed"
    assert definition["from_types"] == ("character", "organization")
    assert definition["to_types"] == ("character", "organization")


def test_located_supports_location_containment() -> None:
    definition = RELATION_DEFINITIONS["位于"]
    assert "location" in definition["from_types"]
    assert definition["to_types"] == ("location",)


def test_relation_catalog_text_contains_semantics() -> None:
    text = relation_catalog_text()
    assert "领导" in text
    assert "双向" in text or "单向" in text
    assert "位于" in text
    assert "同一人物" in text


def test_relation_input_description_embeds_catalog() -> None:
    description = RelationInput.model_fields["relation_type"].description or ""
    assert "领导" in description
    assert "位于" in description


def test_relation_input_is_three_field_edge_contract() -> None:
    """2026-08-12 用于验证关系合同只提交本章确认存在的边（无 state 字段）"""
    assert set(RelationInput.model_fields) == {
        "from_entity",
        "to_entity",
        "relation_type",
    }


def test_system_prompt_relation_semantics_aligned() -> None:
    from src.agents.annotation.prompts import SYSTEM_PROMPT_TEMPLATE

    assert "relation state（present/weakened/ended）" not in SYSTEM_PROMPT_TEMPLATE
    assert "write_relations 只提交本章确认存在的边" in SYSTEM_PROMPT_TEMPLATE
    assert "skipped_existing" in SYSTEM_PROMPT_TEMPLATE
