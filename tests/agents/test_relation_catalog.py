"""关系目录与端点类型合同测试"""

from src.agents.annotation.schema import (
    RELATION_DEFINITIONS,
    RelationInput,
    RelationState,
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


def test_relation_input_state_contract() -> None:
    state_field = RelationInput.model_fields["state"]
    assert state_field.default == RelationState.PRESENT
    assert set(RelationState) == {
        RelationState.PRESENT,
        RelationState.WEAKENED,
        RelationState.ENDED,
    }


def test_system_prompt_relation_state_aligned() -> None:
    from src.agents.annotation.prompts import SYSTEM_PROMPT_TEMPLATE

    assert "relation state（present/weakened/ended）" in SYSTEM_PROMPT_TEMPLATE
