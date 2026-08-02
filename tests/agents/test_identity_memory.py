"""
身份记忆单元测试（消歧集成进 agent 循环的载体）
"""

from src.agents.annotation.memory import IdentityMemory


def test_apply_decisions_keeps_independent_names() -> None:
    memory = IdentityMemory()
    memory.apply_decisions(
        [
            {"name": "顾霜", "canonical": "顾霜", "entity_type": "character", "confidence": "high"},
        ]
    )
    assert "顾霜" in memory.known_canonical_names
    assert memory.alias_map == {}
    assert memory.entity_types == {"顾霜": "character"}


def test_apply_decisions_merges_aliases() -> None:
    memory = IdentityMemory()
    memory.apply_decisions(
        [
            {"name": "阿顾", "canonical": "顾霜", "entity_type": "character", "confidence": "high"},
        ]
    )
    assert memory.alias_map == {"阿顾": "顾霜"}
    assert "顾霜" in memory.known_canonical_names
    assert memory.entity_types == {"顾霜": "character"}


def test_apply_decisions_ignores_empty_entries() -> None:
    memory = IdentityMemory()
    memory.apply_decisions(
        [
            {"name": "", "canonical": "顾霜", "entity_type": "character", "confidence": "high"},
            {"name": "阿顾", "canonical": "", "entity_type": "character", "confidence": "high"},
        ]
    )
    assert memory.alias_map == {}
    assert memory.known_canonical_names == set()


def test_to_dict_roundtrip() -> None:
    memory = IdentityMemory()
    memory.apply_decisions(
        [
            {"name": "阿顾", "canonical": "顾霜", "entity_type": "character", "confidence": "high"},
            {"name": "贺重明", "canonical": "贺重明", "entity_type": "character", "confidence": "high"},
        ]
    )

    restored = IdentityMemory.from_dict(memory.to_dict())

    assert restored.alias_map == {"阿顾": "顾霜"}
    assert restored.known_canonical_names == {"顾霜", "贺重明"}
    assert restored.entity_types == {"顾霜": "character", "贺重明": "character"}
    assert restored.discovered_names == {"阿顾", "顾霜", "贺重明"}


def test_apply_decisions_multiple_aliases_same_canonical() -> None:
    memory = IdentityMemory()
    memory.apply_decisions(
        [
            {"name": "阿顾", "canonical": "顾霜", "entity_type": "character", "confidence": "high"},
            {"name": "霜儿", "canonical": "顾霜", "entity_type": "character", "confidence": "high"},
        ]
    )
    assert memory.alias_map == {"阿顾": "顾霜", "霜儿": "顾霜"}
    assert "顾霜" in memory.known_canonical_names
